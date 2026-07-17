# -*- coding: utf-8 -*-
"""美術小老師 — 雙面:把背面圖交錯進正面 PDF

產出 F1,B1,F2,B2,... 的順序,直接丟給印表機雙面列印即可。

用法:
  py scripts/duplex.py <正面.pdf> <背面圖> --out duplex.pdf [--flip long|short]

**翻頁方向是關鍵,搞錯背面就對不準。**

  --flip long  (預設,對應印表機的「長邊翻頁」)
      沿垂直軸翻(像翻書)。背面的「欄」要左右鏡射,「列」不變。
  --flip short (對應「短邊翻頁」)
      沿水平軸翻(像翻月曆)。背面要整個旋轉 180 度。

正面若左右對稱、且每格背面都一樣,long 的鏡射看起來沒差別 ——
**但最後一頁通常不滿版**(例:12 格只放 6 張),這時候翻頁方向就會露餡:
short 會把背面翻到空白的那三列去。所以務必跟使用者講清楚要選哪個。

券格是直接從正面 PDF 的影像擺放位置讀出來的,不是重算 ——
保證背面與正面逐格對齊。
"""
import sys, io, os, argparse

if __name__ == '__main__':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import fitz
from PIL import Image


def cells_of(page):
    """從頁面上的影像擺放位置取出券格(去重、依列→欄排序)"""
    seen, out = set(), []
    for i in page.get_image_info(xrefs=True):
        b = tuple(round(v, 2) for v in i['bbox'])
        if b in seen:
            continue
        seen.add(b)
        out.append(fitz.Rect(b))
    out.sort(key=lambda r: (round(r.y0, 1), round(r.x0, 1)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('front_pdf')
    ap.add_argument('back_img')
    ap.add_argument('--out', required=True)
    ap.add_argument('--flip', choices=['long', 'short'], default='long')
    args = ap.parse_args()

    front = fitz.open(args.front_pdf)
    bi = Image.open(args.back_img)
    print('正面 : %s  (%d 頁)' % (os.path.basename(args.front_pdf), front.page_count))
    print('背面 : %s  %s %s  長寬比 %.4f'
          % (os.path.basename(args.back_img), bi.mode, bi.size, bi.width / bi.height))

    out = fitz.open()
    total_cells = 0
    for i in range(front.page_count):
        fp = front[i]
        PW, PH = fp.rect.width, fp.rect.height
        cells = cells_of(fp)
        total_cells += len(cells)

        # --- 正面(整頁原樣搬過來,向量與影像都保留) ---
        p = out.new_page(width=PW, height=PH)
        p.show_pdf_page(p.rect, front, i)

        # --- 背面 ---
        b = out.new_page(width=PW, height=PH)
        for r in cells:
            if args.flip == 'long':          # 沿垂直軸翻 -> 欄鏡射,列不變
                rect = fitz.Rect(PW - r.x1, r.y0, PW - r.x0, r.y1)
                rot = 0
            else:                            # 沿水平軸翻 -> 列鏡射 + 轉 180
                rect = fitz.Rect(r.x0, PH - r.y1, r.x1, PH - r.y0)
                rot = 180
            # keep_proportion:等比縮放並置中,絕不變形
            b.insert_image(rect, filename=args.back_img,
                           keep_proportion=True, rotate=rot)

        if i == 0:
            r0 = cells[0]
            fit = min((r0.x1 - r0.x0) / bi.width, (r0.y1 - r0.y0) / bi.height)
            w, h = bi.width * fit, bi.height * fit
            print('\n券格   : %.2f x %.2f mm  (從正面 PDF 讀出,%d 格/頁)'
                  % ((r0.x1 - r0.x0) / 72 * 25.4, (r0.y1 - r0.y0) / 72 * 25.4, len(cells)))
            print('背面縮 : %.2f x %.2f mm -> 左右各留白 %.2f mm, 上下各留白 %.2f mm'
                  % (w / 72 * 25.4, h / 72 * 25.4,
                     ((r0.x1 - r0.x0) - w) / 2 / 72 * 25.4,
                     ((r0.y1 - r0.y0) - h) / 2 / 72 * 25.4))
            print('背面有效解析度: %.0f DPI' % (bi.width / (w / 72)))

    out.save(args.out, garbage=4, deflate=True)
    print('\n頁序   : F1,B1,F2,B2,... 共 %d 頁 (正 %d + 背 %d)'
          % (out.page_count, front.page_count, front.page_count))
    print('券總數 : %d' % total_cells)
    print('翻頁   : --flip %s -> 印表機請選「%s邊翻頁」'
          % (args.flip, '長' if args.flip == 'long' else '短'))
    print('檔案   : %s  (%.2f MB)' % (args.out, os.path.getsize(args.out) / 1e6))


if __name__ == '__main__':
    main()
