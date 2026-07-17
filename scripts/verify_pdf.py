# -*- coding: utf-8 -*-
"""美術小老師 — 第 4 步:反向驗證(不可略過)

從產出的 PDF 把編號抽回來,確認無重複 / 無缺漏 / 順序正確 / 版面等距 / 樣式一致。
「腳本沒報錯」不等於「印出來是對的」——150 張券錯一張就要重印全部。

用法:
  py scripts/verify_pdf.py out.pdf --prefix HMS --digits 3 --start 1 --count 150
                           [--cols 2] [--rows 6] [--proof proof]

坑:setCharSpace 會讓 PyMuPDF 把每個字元切成獨立 span/word,
   直接用 get_text('words') 找 "HMS001" 會抓到 0 個。必須用「行層級 join 後去空白」。
"""
import sys, io, re, argparse
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import fitz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf')
    ap.add_argument('--prefix', required=True)
    ap.add_argument('--digits', type=int, default=3)
    ap.add_argument('--start', type=int, default=1)
    ap.add_argument('--count', type=int, required=True)
    ap.add_argument('--cols', type=int, default=None)
    ap.add_argument('--rows', type=int, default=None)
    ap.add_argument('--proof', default=None, help='輸出首/末頁預覽 png 前綴')
    ap.add_argument('--dpi', type=int, default=110)
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    pat = re.compile(r'%s\d{%d}' % (re.escape(args.prefix), args.digits))

    # 先找出編號用的字型(排除頁尾標示)
    fonts = Counter()
    for pno in range(doc.page_count):
        for b in doc[pno].get_text('dict')['blocks']:
            if b.get('type') != 0:
                continue
            for ln in b['lines']:
                t = ''.join(sp['text'] for sp in ln['spans']).replace(' ', '')
                if pat.fullmatch(t):
                    for sp in ln['spans']:
                        fonts[sp['font']] += 1
    if not fonts:
        raise SystemExit('PDF 中找不到任何符合 %s%s 的編號' % (args.prefix, '#' * args.digits))
    code_font = fonts.most_common(1)[0][0]

    found = []
    for pno in range(doc.page_count):
        for b in doc[pno].get_text('dict')['blocks']:
            if b.get('type') != 0:
                continue
            for ln in b['lines']:
                spans = ln['spans']
                t = ''.join(sp['text'] for sp in spans).replace(' ', '')
                if {sp['font'] for sp in spans} != {code_font}:
                    continue
                if not pat.fullmatch(t):
                    continue
                found.append((pno + 1, t, round(ln['bbox'][0], 1), round(ln['bbox'][1], 1),
                              spans[0]['font'], round(spans[0]['size'], 2), spans[0]['color']))

    codes = [c for _, c, *_ in found]
    expect = ['%s%0*d' % (args.prefix, args.digits, i)
              for i in range(args.start, args.start + args.count)]

    ok = True
    print('=== 編號 ===')
    print('編號字型 : %s' % code_font)
    print('總數     : %d  (應 %d)' % (len(codes), args.count))
    print('唯一數   : %d' % len(set(codes)))
    dup = [c for c, n in Counter(codes).items() if n > 1]
    mis = sorted(set(expect) - set(codes))
    ext = sorted(set(codes) - set(expect))
    print('重複     : %s' % (dup or '無'))
    print('缺漏     : %s' % (mis[:10] if mis else '無'))
    print('多餘     : %s' % (ext[:10] if ext else '無'))
    seq = codes == expect
    print('順序完全等於 %s..%s : %s' % (expect[0], expect[-1], seq))
    ok &= seq and not dup and not mis and not ext

    print('\n=== 每頁 ===')
    per = Counter(p for p, *_ in found)
    for p in sorted(per):
        ps = [c for pp, c, *_ in found if pp == p]
        print('  第%2d頁: %2d 張   %s ~ %s' % (p, per[p], ps[0], ps[-1]))

    print('\n=== 版面 ===')
    xs = sorted({x for _, _, x, *_ in found})
    ys = sorted({y for _, _, _, y, *_ in found})
    print('欄 x 值 : %d 種 %s' % (len(xs), xs))
    print('列 y 值 : %d 種 %s' % (len(ys), ys))
    if len(ys) > 1:
        gaps = [round(ys[i + 1] - ys[i], 2) for i in range(len(ys) - 1)]
        print('列間距  : %s %s' % (gaps, '(等距 ✓)' if len(set(gaps)) <= 2 else '!! 不等距'))
    if args.cols:
        good = len(xs) == args.cols
        print('欄數符合 --cols %d : %s' % (args.cols, good)); ok &= good
    if args.rows:
        good = len(ys) == args.rows
        print('列數符合 --rows %d : %s' % (args.rows, good)); ok &= good

    print('\n=== 樣式一致性 ===')
    fs = {x[4] for x in found}; ss = {x[5] for x in found}; cs = {x[6] for x in found}
    print('字型 : %s' % fs)
    print('字級 : %s' % ss)
    print('顏色 : %s' % {'#%06X' % c for c in cs})
    style = len(fs) == 1 and len(ss) == 1 and len(cs) == 1
    print('全部編號樣式一致 : %s' % style)
    ok &= style

    print('\n=== 影像嵌入 ===')
    xrefs = {i[0] for p in range(doc.page_count) for i in doc[p].get_images(full=True)}
    print('不重複影像物件數 : %d  %s' % (len(xrefs),
          '(底圖只嵌一次 ✓)' if len(xrefs) == 1 else '(>1,檔案會變大)'))

    if args.proof:
        for pno, tag in [(0, 'first'), (doc.page_count - 1, 'last')]:
            f = '%s_%s.png' % (args.proof, tag)
            doc[pno].get_pixmap(dpi=args.dpi).save(f)
            print('預覽 -> %s' % f)

    print('\n>>> 全部檢查通過: %s' % ok)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
