# -*- coding: utf-8 -*-
"""美術小老師 — 第 2 步:配字體

原圖的字體通常不在你電腦裡(Canva/Illustrator 用的雲端字體)。
本腳本用「像素疊合 IoU」客觀挑出最接近的系統字型,並算出
字級 / 字距 / 基線,讓新編號長得跟原本那組一模一樣。

用法:
  py scripts/match_font.py inspect.json [--fonts a.ttf,b.ttf] [--out font.json]
                           [--overlay overlay.png]

不要用肉眼猜字體。IoU 會抓到肉眼容易忽略的差異(例:某些字體的「1」有底座橫畫)。
"""
import sys, io, json, argparse, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from PIL import Image, ImageDraw, ImageFont
import numpy as np

FONT_DIR = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts')

# 預設候選:涵蓋常見無襯線 bold。可變字型用 "檔案|實例名"
DEFAULT_FONTS = [
    'arialbd.ttf', 'ariblk.ttf', 'segoeuib.ttf', 'seguisb.ttf',
    'calibrib.ttf', 'trebucbd.ttf', 'verdanab.ttf', 'tahomabd.ttf',
    'NotoSansTC-VF.ttf|Bold', 'NotoSansTC-VF.ttf|Medium',
    'NotoSansHK-VF.ttf|Bold', 'msjhbd.ttc',
]


def load(spec, size):
    """spec = 路徑 或 '路徑|可變字型實例名'"""
    path, _, var = spec.partition('|')
    if not os.path.isabs(path):
        path = os.path.join(FONT_DIR, path)
    f = ImageFont.truetype(path, size)
    if var:
        f.set_variation_by_name(var)
    return f, path, var


def render(font, text, spacing, mode='L'):
    """逐字繪製套用字距,回傳緊裁後的二值遮罩"""
    tmp = Image.new(mode, (4000, 500), 0)
    d = ImageDraw.Draw(tmp)
    x = 120
    for ch in text:
        d.text((x, 250), ch, font=font, fill=255, anchor='ls')
        x += d.textlength(ch, font=font) + spacing
    arr = np.asarray(tmp)
    ys, xs = np.nonzero(arr > 128)
    if not len(xs):
        return None
    return arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1] > 128


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inspect_json')
    ap.add_argument('--fonts', default=None, help='逗號分隔;省略用預設候選')
    ap.add_argument('--out', default='font.json')
    ap.add_argument('--overlay', default='font_overlay.png')
    args = ap.parse_args()

    cfg = json.load(open(args.inspect_json, encoding='utf-8'))
    TEXT = cfg['code_text']
    X0, Y0, X1, Y1 = cfg['code_bbox']
    capH = cfg['cap_height']
    target_w = X1 - X0 + 1

    im = Image.open(cfg['art']).convert('RGB')
    a = np.asarray(im).astype(int)
    rgb = np.array(cfg['code_color'])
    d = np.abs(a - rgb).sum(axis=2)
    omask = (d <= 90)[Y0:Y1 + 1, X0:X1 + 1]
    OH, OW = omask.shape
    print('原圖遮罩 : %dx%d  (%d px)  cap height=%d' % (OW, OH, int(omask.sum()), capH))

    # 基準字元(平頂平底)用來定字級
    flat = [g for g in cfg['glyphs'] if g['ch'] in 'HMNEFTILKXYZ1234567']
    ref_ch = (flat[0] if flat else cfg['glyphs'][0])['ch']
    print('基準字元 : %s' % ref_ch)

    cands = args.fonts.split(',') if args.fonts else DEFAULT_FONTS
    results = []
    for spec in cands:
        try:
            # 1) 找字級使基準字元高度 = capH
            size = None
            for s in range(8, 200):
                try:
                    f, path, var = load(spec, s)
                except Exception:
                    raise
                m = render(f, ref_ch, 0)
                if m is not None and m.shape[0] >= capH:
                    size = s
                    break
            if size is None:
                print('%-28s 找不到合適字級' % spec); continue
            f, path, var = load(spec, size)
            got_h = render(f, ref_ch, 0).shape[0]

            # 2) 二分字距使整串寬 = target_w
            lo, hi = -10.0, 120.0
            for _ in range(45):
                mid = (lo + hi) / 2
                m = render(f, TEXT, mid)
                if m is None or m.shape[1] < target_w:
                    lo = mid
                else:
                    hi = mid
            spacing = (lo + hi) / 2
            m = render(f, TEXT, spacing)
            if m is None:
                print('%-28s 渲染失敗' % spec); continue

            # 3) IoU(尺寸對齊到原圖遮罩)
            mm = np.array(Image.fromarray(m.astype(np.uint8) * 255)
                          .resize((OW, OH), Image.LANCZOS)) > 128
            iou = (mm & omask).sum() / (mm | omask).sum()

            # 4) 定位參數:lsb 與 cap top
            bb = f.getbbox(ref_ch, anchor='ls')
            results.append(dict(spec=spec, path=path, var=var, size=size, spacing=spacing,
                                iou=float(iou), lsb=float(bb[0]), cap_top=float(bb[1]),
                                ref_h=int(got_h), str_w=int(m.shape[1]), mask=mm))
            print('%-28s IoU=%.4f  字級=%3d 字距=%6.2f  (%s高 %d/%d, 串寬 %d/%d)'
                  % (spec, iou, size, spacing, ref_ch, got_h, capH, m.shape[1], target_w))
        except Exception as e:
            print('%-28s 略過 (%s)' % (spec, e))

    if not results:
        raise SystemExit('沒有可用字型')
    results.sort(key=lambda r: -r['iou'])
    best = results[0]
    print('\n=== 最接近: %s  (IoU %.4f) ===' % (best['spec'], best['iou']))
    if best['iou'] < 0.6:
        print('!! IoU 偏低,字形差異明顯。考慮安裝原字體(Canva 常用 Poppins/Montserrat,'
              'Google Fonts 可免費下載)後用 --fonts 指定。')

    # 等寬檢查:所有編號寬度是否一致(見 pitfalls)
    f, _, _ = load(best['spec'], best['size'])
    dd = ImageDraw.Draw(Image.new('L', (8, 8)))
    widths = {round(sum(dd.textlength(c, font=f) for c in TEXT[:len(TEXT)]) , 3)}
    digits = ''.join(c for c in TEXT if c.isdigit())
    if digits:
        dw = {round(dd.textlength(str(i), font=f), 3) for i in range(10)}
        print('數字等寬 : %s  (%d 種寬度 %s)'
              % ('是 ✓ 所有編號可左對齊' if len(dw) == 1 else '否 !! 不同編號寬度會不一致',
                 len(dw), sorted(dw)))

    # 疊合圖
    S = 3
    rows = results[:4]
    rh = OH * S + 30
    canvas = Image.new('RGB', (320 + OW * S + 30, rh * len(rows) + 20), 'white')
    dr = ImageDraw.Draw(canvas)
    try:
        lf = ImageFont.truetype(os.path.join(FONT_DIR, 'msjh.ttc'), 16)
    except Exception:
        lf = ImageFont.load_default()
    for i, r in enumerate(rows):
        vis = np.full((OH, OW, 3), 255, np.uint8)
        mm = r['mask']
        vis[omask & ~mm] = (255, 60, 60)      # 原圖獨有
        vis[mm & ~omask] = (60, 180, 60)      # 候選獨有
        vis[mm & omask] = (250, 210, 40)      # 重合
        y = 10 + i * rh
        dr.text((10, y + rh // 2 - 14), '%s\nIoU %.3f' % (r['spec'], r['iou']), font=lf, fill=(0, 0, 0))
        canvas.paste(Image.fromarray(vis).resize((OW * S, OH * S), Image.NEAREST), (320, y + 10))
    canvas.save(args.overlay)
    print('疊合圖   : %s  (紅=原圖獨有 綠=候選獨有 黃=重合)' % args.overlay)

    out = {k: v for k, v in best.items() if k != 'mask'}
    out['ranking'] = [dict(spec=r['spec'], iou=round(r['iou'], 4)) for r in results]
    json.dump(out, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('-> %s' % args.out)


if __name__ == '__main__':
    main()
