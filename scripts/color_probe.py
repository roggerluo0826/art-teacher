# -*- coding: utf-8 -*-
"""美術小老師 — 色彩管線診斷頁

什麼時候用:印出來跟參考檔顏色不一樣,但你已經確認
  - CMYK 色值比對到 0 差
  - 渲染出來的平均色也一樣
  - ICC / OutputIntent 都對
卻還是有差。那問題就在「PDF 用哪條管線把像素送給印表機」。

本腳本把**同一張圖**用五種管線畫在同一張 A4 上。印一次,看哪一列不一樣。

  A vector CMYK      整張圖不用,改用向量色塊(只畫主色)——測「向量 vs 影像」
  B img CMYK Flate   無損,原始解析度(本工具的預設做法)
  C img CMYK JPEG    有損 DCTDecode(Canva 的做法)
  D img CMYK 低解析  降到約 390 DPI(Canva 的解析度)
  E img RGB          完全不轉 CMYK

判讀:
  B 跟 C 不一樣  -> 編碼(Flate vs JPEG)是兇手
  B 跟 D 不一樣  -> 解析度是兇手
  A 跟 B 不一樣  -> 驅動對「嵌入影像」和「向量」的處理不同
  E 最接近你要的 -> 別轉 CMYK,直接送 RGB
  五列都一樣     -> 檔案不是問題,去查印表機/驅動設定

用法:
  py scripts/color_probe.py <乾淨底圖.png> --cmyk profile.icc --out probe.pdf
     [--width 90] [--rows-only B,C,D]

注意:reportlab 會依影像內容去重,所以每一列的影像必須真的不同
(不同編碼/不同解析度會產生不同的解碼結果,足以避開去重)。
本腳本會在最後驗證 PDF 裡的影像數,不對會警告。
"""
import sys, io, os, argparse

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from PIL import Image
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from impose import to_cmyk, add_output_intent   # noqa: E402

ROWS = [
    ('B  img CMYK Flate  (my default)', 'flate_hi'),
    ('C  img CMYK JPEG   (Canva style)', 'jpeg'),
    ('D  img CMYK Flate  390dpi', 'flate_lo'),
    ('E  img RGB         (no CMYK)', 'rgb'),
]


def make(src, mode, icc, tmp, target_w_mm):
    im = Image.open(src).convert('RGB')
    if mode == 'flate_lo':
        px = int(target_w_mm / 25.4 * 390)
        im = im.resize((px, int(px * im.height / im.width)), Image.LANCZOS)
    p = os.path.join(tmp, 'probe_%s.%s' % (mode, 'jpg' if mode == 'jpeg' else
                                           ('png' if mode == 'rgb' else 'tif')))
    if mode == 'rgb':
        im.save(p)
        return p
    cm, _ = to_cmyk(im, icc)
    if mode == 'jpeg':
        cm.save(p, 'JPEG', quality=95)
    else:
        cm.save(p, 'TIFF')
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('art', help='乾淨底圖(impose.py 產生的 *_base.png/tif,或原圖)')
    ap.add_argument('--cmyk', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--width', type=float, default=90, help='每張樣本寬度 mm')
    args = ap.parse_args()

    tmp = os.path.join(os.path.dirname(os.path.abspath(args.out)) or '.', '_probe_tmp')
    os.makedirs(tmp, exist_ok=True)

    src = Image.open(args.art)
    W = args.width * mm
    H = W * src.height / src.width

    PW, PH = A4
    c = rl_canvas.Canvas(args.out, pagesize=A4)
    c.setTitle('color pipeline probe')
    c.setFillColorCMYK(0, 0, 0, 1)
    c.setFont('Helvetica-Bold', 12)
    c.drawString(12 * mm, PH - 14 * mm, 'COLOR PIPELINE PROBE  -  print once, compare the rows')
    c.setFont('Helvetica', 8)
    c.drawString(12 * mm, PH - 19 * mm,
                 'Same artwork, 4 different PDF pipelines. Whichever row looks different '
                 'from the reference is the culprit.')

    y = PH - 28 * mm
    for label, mode in ROWS:
        p = make(args.art, mode, args.cmyk, tmp, args.width)
        y -= H
        c.drawImage(ImageReader(p), 12 * mm, y, width=W, height=H)
        c.setFillColorCMYK(0, 0, 0, 1)
        c.setFont('Helvetica-Bold', 8.5)
        c.drawString(12 * mm + W + 3 * mm, y + H / 2, label)
        y -= 5 * mm

    c.setFont('Helvetica', 7.5)
    for k, t in enumerate([
        'B vs C differ  -> encoding (lossless Flate vs lossy JPEG) is the culprit',
        'B vs D differ  -> image resolution is the culprit',
        'E looks right  -> do not convert to CMYK; send RGB instead',
        'all rows equal -> the PDF is not the problem; check printer/driver settings',
    ]):
        c.drawString(12 * mm, 20 * mm - k * 4 * mm, t)
    c.showPage()
    c.save()

    desc = add_output_intent(args.out, args.cmyk)

    # 驗證:每一列必須是不同的影像物件(reportlab 會依內容去重)
    import fitz
    doc = fitz.open(args.out)
    xrefs = {i[0] for i in doc[0].get_images(full=True)}
    print('OutputIntent : %s' % desc)
    print('影像物件數   : %d  (應為 %d,每列一個)' % (len(xrefs), len(ROWS)))
    if len(xrefs) != len(ROWS):
        print('  !! 有列被 reportlab 依內容去重合併了,該列的測試無效')
    for x in sorted(xrefs):
        info = doc.extract_image(x)
        print('    xref=%-3d %4dx%-4d cs=%s ext=%s'
              % (x, info['width'], info['height'], info.get('colorspace'), info.get('ext')))
    print('\n輸出: %s  (%.2f MB)' % (args.out, os.path.getsize(args.out) / 1e6))
    print('印一張,跟你的參考檔並排比較,看哪一列對得上。')


if __name__ == '__main__':
    main()
