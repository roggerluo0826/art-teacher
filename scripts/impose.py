# -*- coding: utf-8 -*-
"""美術小老師 — 第 3 步:拼版出 PDF

把原圖的舊編號無痕塗掉,重新以向量文字印上流水號,並拼成 N-up 印刷 PDF。

用法:
  py scripts/impose.py inspect.json font.json --prefix HMS --digits 3 \
     --start 1 --count 150 --cols 2 --rows 6 --out out.pdf [--margin 8] [--page A4]

尺寸(三選一,都保持原圖長寬比):
  --margin 8            由左右邊界反推券寬(預設)
  --coupon-height 45    直接指定券高 mm,寬由比例算出
  --coupon-width 96     直接指定券寬 mm,高由比例算出

色彩:
  --cmyk <profile.icc>  用 ICC 把底圖與編號色轉成 DeviceCMYK(送印刷廠用)
                        不給則維持 DeviceRGB(桌上型印表機通常這樣比較準)

關鍵:底圖只嵌入 PDF 一次(同一個 ImageReader 重複引用),編號是向量文字。
150 張券的檔案因此只有 0.2MB 而非數百 MB,且編號放到多大都銳利。
"""
import sys, io, json, argparse, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from PIL import Image, ImageCms
import numpy as np
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib import pagesizes
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

SRGB_ICC = os.path.join(os.environ.get('WINDIR', r'C:\Windows'),
                        r'System32\spool\drivers\color\sRGB Color Space Profile.icm')


def to_cmyk(img, icc, intent=None):
    """用 ICC 把 RGB 影像轉成 CMYK。回傳 (CMYK影像, transform)"""
    if intent is None:
        intent = ImageCms.Intent.PERCEPTUAL
    tr = ImageCms.buildTransformFromOpenProfiles(
        ImageCms.getOpenProfile(SRGB_ICC), ImageCms.getOpenProfile(icc),
        'RGB', 'CMYK', renderingIntent=intent)
    return ImageCms.applyTransform(img, tr), tr


def rgb_to_cmyk_color(rgb, icc, intent=None):
    """單一顏色走同一條 ICC 路徑,確保編號色與底圖同調"""
    one = Image.new('RGB', (1, 1), tuple(rgb))
    c, _ = to_cmyk(one, icc, intent)
    return tuple(v / 255.0 for v in c.getpixel((0, 0)))


def add_output_intent(pdf_path, icc_path):
    """把 ICC 以 OutputIntent 寫進 PDF。

    沒有 OutputIntent 的 DeviceCMYK PDF 等於「一堆沒有單位的數字」——
    印表機/RIP 只能自己猜是哪個 CMYK 空間,顏色就飄了。印刷廠也會退件。
    """
    import fitz
    icc = open(icc_path, 'rb').read()
    desc = os.path.splitext(os.path.basename(icc_path))[0]
    doc = fitz.open(pdf_path)

    x_icc = doc.get_new_xref()
    doc.update_object(x_icc, '<< /N 4 >>')
    doc.update_stream(x_icc, icc, compress=True)

    x_oi = doc.get_new_xref()
    doc.update_object(x_oi, '<< /Type /OutputIntent /S /GTS_PDFX '
                            '/OutputConditionIdentifier (%s) /OutputCondition (%s) '
                            '/Info (%s) /RegistryName (http://www.color.org) '
                            '/DestOutputProfile %d 0 R >>' % (desc, desc, desc, x_icc))
    doc.xref_set_key(doc.pdf_catalog(), 'OutputIntents', '[ %d 0 R ]' % x_oi)

    tmp = pdf_path + '.tmp'
    doc.save(tmp, garbage=0, deflate=True)
    doc.close()
    os.replace(tmp, pdf_path)
    return desc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inspect_json')
    ap.add_argument('font_json')
    ap.add_argument('--prefix', required=True)
    ap.add_argument('--digits', type=int, default=3)
    ap.add_argument('--start', type=int, default=1)
    ap.add_argument('--count', type=int, required=True)
    ap.add_argument('--cols', type=int, required=True)
    ap.add_argument('--rows', type=int, required=True)
    ap.add_argument('--page', default='A4')
    ap.add_argument('--margin', type=float, default=8, help='左右邊界 mm(未指定券尺寸時用)')
    ap.add_argument('--coupon-height', type=float, default=None, help='直接指定券高 mm')
    ap.add_argument('--coupon-width', type=float, default=None, help='直接指定券寬 mm')
    ap.add_argument('--cmyk', default=None, help='CMYK ICC 描述檔路徑;不給則維持 RGB')
    ap.add_argument('--no-output-intent', action='store_true',
                    help='不要把 ICC 嵌成 OutputIntent(檔案會小很多,但送印刷廠會被退)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--no-cropmarks', action='store_true')
    ap.add_argument('--title', default=None)
    args = ap.parse_args()

    if args.coupon_height and args.coupon_width:
        raise SystemExit('--coupon-height 與 --coupon-width 只能擇一(另一邊由原圖比例決定)')

    ins = json.load(open(args.inspect_json, encoding='utf-8'))
    fj = json.load(open(args.font_json, encoding='utf-8'))

    if not ins.get('mask_ring_uniform'):
        raise SystemExit('inspect.json 顯示遮罩框外框非單一色,直接塗會露餡。'
                         '請調整 --pad 或見 references/pitfalls.md')

    # ---------- 1. 塗掉舊編號 ----------
    im = Image.open(ins['art']).convert('RGB')
    IW, IH = im.size
    bx0, by0, bx1, by1 = ins['mask_box']
    fill = tuple(ins['mask_fill'])
    clean = im.copy()
    clean.paste(fill, (bx0, by0, bx1, by1))

    # 驗證真的清乾淨(在轉色前先驗,RGB 比對才準)
    ca = np.asarray(clean).astype(int)
    rgb = np.array(ins['code_color'])
    X0, Y0, X1, Y1 = ins['code_bbox']
    left = int((np.abs(ca[Y0:Y1 + 1, X0:X1 + 1] - rgb).sum(axis=2) <= 90).sum())
    print('舊編號殘留像素: %d  (應為 0)' % left)
    assert left == 0, '舊編號沒清乾淨'

    # ---------- 1b. 色彩 ----------
    R, G, B = [v / 255.0 for v in ins['code_color']]
    code_cmyk = None
    if args.cmyk:
        if not os.path.exists(args.cmyk):
            raise SystemExit('找不到 ICC 描述檔: %s' % args.cmyk)
        clean, _ = to_cmyk(clean, args.cmyk)
        code_cmyk = rgb_to_cmyk_color(ins['code_color'], args.cmyk)
        # 存 TIFF:reportlab 會以無損 Flate 嵌成 DeviceCMYK
        # (存 JPEG 也是 DeviceCMYK,但大色塊平面設計會出現壓縮雜訊)
        base = os.path.splitext(args.out)[0] + '_base.tif'
        clean.save(base, 'TIFF')
        print('色彩    : DeviceCMYK  <- %s' % os.path.basename(args.cmyk))
        print('  編號色 #%02X%02X%02X -> C%.0f%% M%.0f%% Y%.0f%% K%.0f%%'
              % (*ins['code_color'], *[v * 100 for v in code_cmyk]))
    else:
        base = os.path.splitext(args.out)[0] + '_base.png'
        clean.save(base)
        print('色彩    : DeviceRGB')
    print('乾淨底圖: %s' % base)

    # ---------- 2. 版面 ----------
    PW, PH = getattr(pagesizes, args.page.upper())
    if args.coupon_height:                  # 指定高 -> 寬由比例算
        ch = args.coupon_height * mm
        cw = ch * IW / IH
    elif args.coupon_width:                 # 指定寬 -> 高由比例算
        cw = args.coupon_width * mm
        ch = cw * IH / IW
    else:                                   # 由邊界反推
        cw = (PW - 2 * args.margin * mm) / args.cols
        ch = cw * IH / IW                   # 保持原圖比例,絕不變形
    bw, bh = cw * args.cols, ch * args.rows
    if bw > PW:
        raise SystemExit('%d 欄放不下:所需 %.1fmm > 頁寬 %.1fmm' % (args.cols, bw / mm, PW / mm))
    if bh > PH:
        raise SystemExit('%d 列放不下:所需 %.1fmm > 頁高 %.1fmm。減少 --rows 或券尺寸'
                         % (args.rows, bh / mm, PH / mm))
    MX = (PW - bw) / 2                      # 水平置中
    my = (PH - bh) / 2
    s = cw / IW                             # 影像 px -> pt

    print('\n--- 版面 ---')
    print('頁面    : %s  %.1f x %.1f mm' % (args.page, PW / mm, PH / mm))
    print('單張    : %.2f x %.2f mm  (比例 %.4f,與原圖相同)' % (cw / mm, ch / mm, IW / IH))
    print('拼版區  : %.2f x %.2f mm ; 左右 %.2f / 上下 %.2f mm'
          % (bw / mm, bh / mm, MX / mm, my / mm))
    print('有效解析度: %.0f DPI' % (IW / (cw / mm / 25.4)))
    if IW / (cw / mm / 25.4) < 300:
        print('  !! 低於印刷建議的 300 DPI,原圖解析度不足')

    pdfmetrics.registerFont(TTFont('CodeFont', fj['path']))
    fsize = fj['size'] * s
    cspace = fj['spacing'] * s
    print('編號    : %.2f pt ; 字距 %.2f pt' % (fsize, cspace))

    # ---------- 3. 產生 ----------
    per = args.cols * args.rows
    codes = ['%s%0*d' % (args.prefix, args.digits, i)
             for i in range(args.start, args.start + args.count)]
    pages = [codes[i:i + per] for i in range(0, len(codes), per)]

    img = ImageReader(base)                 # 同一物件 -> 只嵌入一次
    c = rl_canvas.Canvas(args.out, pagesize=(PW, PH))
    c.setTitle(args.title or ('%s%0*d-%s' % (args.prefix, args.digits, args.start, codes[-1])))
    placed = []

    for pno, chunk in enumerate(pages):
        for idx, code in enumerate(chunk):
            r, col = divmod(idx, args.cols)
            X = MX + col * cw
            Y = PH - my - (r + 1) * ch
            c.drawImage(img, X, Y, width=cw, height=ch)
            to = c.beginText(X + (ins['ink_left'] - fj['lsb']) * s,
                             Y + ch - ins['baseline'] * s)
            to.setFont('CodeFont', fsize)
            to.setCharSpace(cspace)          # 注意:setCharSpace 在 text object,不在 canvas
            if code_cmyk:
                to.setFillColorCMYK(*code_cmyk)
            else:
                to.setFillColorRGB(R, G, B)
            to.textOut(code)
            c.drawText(to)
            placed.append((pno + 1, code))

        if not args.no_cropmarks:
            # CMYK 檔裡不要混用 RGB 色,裁切線用純黑版
            if code_cmyk:
                c.setStrokeColorCMYK(0, 0, 0, 1)
            else:
                c.setStrokeColorRGB(0, 0, 0)
            c.setLineWidth(0.25)
            nrow = (len(chunk) + args.cols - 1) // args.cols
            top, bot = PH - my, PH - my - nrow * ch
            for i in range(args.cols + 1):
                x = MX + i * cw
                c.line(x, top + 1 * mm, x, top + 1 * mm + 4 * mm)
                c.line(x, bot - 1 * mm, x, bot - 1 * mm - 4 * mm)
            for j in range(nrow + 1):
                y = PH - my - j * ch
                c.line(MX - 1 * mm, y, MX - 1 * mm - 4 * mm, y)
                c.line(MX + bw + 1 * mm, y, MX + bw + 1 * mm + 4 * mm, y)

        c.setFont('Helvetica', 6)
        if code_cmyk:
            c.setFillColorCMYK(0, 0, 0, .45)
        else:
            c.setFillColorRGB(.55, .55, .55)
        c.drawString(MX, my / 2, '%s  p.%d/%d   %s - %s   (%d)'
                     % (args.prefix, pno + 1, len(pages), chunk[0], chunk[-1], len(chunk)))
        c.showPage()
    c.save()

    print('\n--- 結果 ---')
    print('頁數    : %d  (每頁 %d 張)' % (len(pages), per))
    print('總張數  : %d' % len(placed))
    if len(codes) % per:
        print('  末頁只有 %d 張 (%d 不是 %d 的倍數)' % (len(codes) % per, args.count, per))
    print('編號    : %s ~ %s' % (codes[0], codes[-1]))
    if args.cmyk and not args.no_output_intent:
        sz = os.path.getsize(args.out)
        desc = add_output_intent(args.out, args.cmyk)
        print('OutputIntent: 已嵌入 %s  (%.2f -> %.2f MB)'
              % (desc, sz / 1e6, os.path.getsize(args.out) / 1e6))
    elif args.cmyk:
        print('OutputIntent: 未嵌入 (--no-output-intent) !! 送印刷廠可能被退件')

    print('檔案    : %s  (%.2f MB)' % (args.out, os.path.getsize(args.out) / 1e6))
    print('\n下一步: py scripts/verify_pdf.py %s --prefix %s --digits %d --start %d --count %d'
          % (args.out, args.prefix, args.digits, args.start, args.count))


if __name__ == '__main__':
    main()
