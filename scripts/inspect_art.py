# -*- coding: utf-8 -*-
"""美術小老師 — 第 1 步:讀圖

找出圖上既有的編號文字、逐字元量測、並判斷「能不能無痕塗掉」。

用法:
  py scripts/inspect_art.py <圖檔> --text HMS001 [--color FF3131] [--region top-right]
                            [--pad 8] [--out inspect.json]

--region 限縮搜尋範圍(極重要,見 references/pitfalls.md「紅色偵測抓到整張圖」):
  top-right / top-left / bottom-right / bottom-left / all
  或直接給 x0,y0,x1,y1
"""
import sys, io, json, argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from PIL import Image
import numpy as np


def parse_region(spec, W, H):
    presets = {
        'all':          (0, 0, W, H),
        'top-right':    (W // 2, 0, W, H // 3),
        'top-left':     (0, 0, W // 2, H // 3),
        'bottom-right': (W // 2, H * 2 // 3, W, H),
        'bottom-left':  (0, H * 2 // 3, W // 2, H),
        'top':          (0, 0, W, H // 3),
        'bottom':       (0, H * 2 // 3, W, H),
    }
    if spec in presets:
        return presets[spec]
    p = [int(v) for v in spec.split(',')]
    if len(p) != 4:
        raise SystemExit('--region 需為預設值或 x0,y0,x1,y1')
    return tuple(p)


def color_mask(a, rgb, tol):
    """與目標色距離在 tol 內"""
    d = np.abs(a - np.array(rgb)).sum(axis=2)
    return d <= tol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--text', required=True, help='圖上既有的編號字串,例 HMS001')
    ap.add_argument('--color', default=None, help='編號顏色 hex,例 FF3131;省略則自動偵測')
    ap.add_argument('--region', default='all')
    ap.add_argument('--tol', type=int, default=90, help='顏色容差(RGB 絕對差總和)')
    ap.add_argument('--pad', type=int, default=8, help='遮罩外擴 px')
    ap.add_argument('--out', default='inspect.json')
    args = ap.parse_args()

    im = Image.open(args.image).convert('RGB')
    W, H = im.size
    a = np.asarray(im).astype(int)
    print('圖檔     : %s' % args.image)
    print('尺寸     : %d x %d  (長寬比 %.4f)' % (W, H, W / H))

    rx0, ry0, rx1, ry1 = parse_region(args.region, W, H)
    reg = np.zeros((H, W), bool)
    reg[ry0:ry1, rx0:rx1] = True
    print('搜尋範圍 : %s -> x%d..%d y%d..%d' % (args.region, rx0, rx1, ry0, ry1))

    if args.color:
        rgb = tuple(int(args.color.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
        mask = color_mask(a, rgb, args.tol) & reg
    else:
        # 自動偵測:在搜尋範圍內,取「非背景」且出現次數夠多的最飽和色
        sub = a[ry0:ry1, rx0:rx1].reshape(-1, 3)
        uniq, cnt = np.unique(sub, axis=0, return_counts=True)
        sat = uniq.max(axis=1) - uniq.min(axis=1)          # 飽和度近似
        ok = (cnt > 200) & (sat > 60)
        if not ok.any():
            raise SystemExit('自動偵測失敗,請用 --color 指定顏色')
        rgb = tuple(int(v) for v in uniq[ok][cnt[ok].argmax()])
        mask = color_mask(a, rgb, args.tol) & reg
        print('自動偵測顏色 -> #%02X%02X%02X' % rgb)

    if mask.sum() == 0:
        raise SystemExit('在指定範圍找不到該顏色的像素,請調 --region / --color / --tol')
    print('編號顏色 : #%02X%02X%02X  (命中 %d px)' % (rgb + (int(mask.sum()),)))

    ys, xs = np.nonzero(mask)
    X0, X1, Y0, Y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    print('\n整串 bbox: x%d..%d y%d..%d  (w=%d h=%d)' % (X0, X1, Y0, Y1, X1 - X0 + 1, Y1 - Y0 + 1))
    if (X1 - X0 + 1) > (rx1 - rx0) * 0.95:
        print('  !! bbox 幾乎等於搜尋範圍寬度 —— 很可能誤抓到圖中其他同色物件,請縮小 --region')

    # 依欄空隙切字元
    colhas = mask[:, X0:X1 + 1].any(axis=0)
    runs, st = [], None
    for i, v in enumerate(colhas):
        if v and st is None:
            st = i
        elif not v and st is not None:
            runs.append((st + X0, i - 1 + X0)); st = None
    if st is not None:
        runs.append((st + X0, X1))

    print('切出 %d 個字元 (預期 %d):' % (len(runs), len(args.text)))
    glyphs = []
    for i, (cx0, cx1) in enumerate(runs):
        gy = np.nonzero(mask[:, cx0:cx1 + 1].any(axis=1))[0]
        ch = args.text[i] if i < len(args.text) else '?'
        glyphs.append(dict(ch=ch, x0=int(cx0), x1=int(cx1), y0=int(gy.min()), y1=int(gy.max())))
        print('  %s : x%5d..%-5d (w=%3d)  y%5d..%-5d (h=%3d)'
              % (ch, cx0, cx1, cx1 - cx0 + 1, gy.min(), gy.max(), gy.max() - gy.min() + 1))
    if len(runs) != len(args.text):
        print('  !! 切出的字元數與 --text 不符;字距太窄會黏在一起,字距太寬可能誤切。')

    # cap height 以「平頂平底」的字元為準(見 pitfalls:bbox 高 != 字高)
    flat = [g for g in glyphs if g['ch'] in 'HMNEFTILKXYZ1234567']
    ref = flat[0] if flat else glyphs[0]
    capH = ref['y1'] - ref['y0'] + 1
    baseline = ref['y1'] + 1
    print('\n基準字元 : %s  -> cap height = %d px ; 基線 y = %d' % (ref['ch'], capH, baseline))
    if capH != (Y1 - Y0 + 1):
        print('  (整串 bbox 高 %d > cap height %d:圓形字元 O/0/S/C 有 overshoot,正常)'
              % (Y1 - Y0 + 1, capH))

    # 遮罩可行性:外框一圈必須同色
    p = args.pad
    bx0, by0, bx1, by1 = X0 - p, Y0 - p, X1 + p + 1, Y1 + p + 1
    if bx0 < 0 or by0 < 0 or bx1 > W or by1 > H:
        raise SystemExit('遮罩框超出圖片邊界,請減小 --pad')
    box = a[by0:by1, bx0:bx1]
    ring = np.concatenate([box[0, :, :], box[-1, :, :], box[:, 0, :], box[:, -1, :]])
    ring_u = np.unique(ring, axis=0)
    dom = ring_u[0] if len(ring_u) == 1 else None
    same = len(ring_u) == 1
    print('\n遮罩框   : x%d..%d y%d..%d (pad=%d)' % (bx0, bx1, by0, by1, p))
    print('外框一圈 : %d 種顏色 -> %s'
          % (len(ring_u), '單一色 #%02X%02X%02X ✓ 可無痕塗掉' % tuple(dom) if same
             else '非單一色 ✗ 直接塗會露出補丁'))
    if not same:
        vals, cs = np.unique(ring, axis=0, return_counts=True)
        print('  外框顏色分佈(前5):')
        for i in cs.argsort()[::-1][:5]:
            print('    #%02X%02X%02X  x%d (%.1f%%)'
                  % (tuple(vals[i]) + (cs[i], 100.0 * cs[i] / cs.sum())))
        print('  -> 對策見 references/pitfalls.md「底不是純色怎麼辦」')

    cfg = dict(art=args.image, size=[W, H], code_text=args.text,
               code_color=[int(v) for v in rgb], code_bbox=[X0, Y0, X1, Y1],
               glyphs=glyphs, cap_height=int(capH), baseline=int(baseline),
               ink_left=int(X0), mask_pad=p, mask_box=[bx0, by0, bx1, by1],
               mask_ring_uniform=bool(same),
               mask_fill=[int(v) for v in dom] if same else None)
    json.dump(cfg, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n-> %s' % args.out)
    if not same:
        sys.exit(2)


if __name__ == '__main__':
    main()
