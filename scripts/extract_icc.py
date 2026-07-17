# -*- coding: utf-8 -*-
"""從既有 PDF 的 OutputIntent 挖出它用的 ICC profile。

用途:客戶/設計工具給了你一份 CMYK PDF,你想用「同一個 profile」處理其他素材,
讓兩邊的分色完全一致。Canva 的「PDF 列印 + CMYK」匯出就把 profile 嵌在裡面。

用法:
  py scripts/extract_icc.py <某份.pdf> [--out profiles/xxx.icc]
"""
import sys, io, os, argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import fitz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    doc = fitz.open(args.pdf)
    cat = doc.xref_object(doc.pdf_catalog(), compressed=False)
    if '/OutputIntents' not in cat:
        raise SystemExit('這份 PDF 沒有 OutputIntent(沒有嵌入 ICC)。'
                         '\n它的 DeviceCMYK 數值等於沒有單位,印表機只能自己猜。')

    found = []
    for x in range(1, doc.xref_length()):
        try:
            o = doc.xref_object(x, compressed=False)
        except Exception:
            continue
        if '/Type /OutputIntent' not in o:
            continue
        info = cond = None
        dest = None
        for line in o.split('\n'):
            s = line.strip()
            if s.startswith('/Info'):
                info = s[len('/Info'):].strip().strip('()')
            elif s.startswith('/OutputCondition ') or s.startswith('/OutputConditionIdentifier'):
                cond = cond or s.split('(', 1)[-1].rstrip(')')
            elif '/DestOutputProfile' in s:
                dest = int(s.split()[-3])
        found.append((x, info, cond, dest))
        print('OutputIntent (xref %d)' % x)
        print('  Info                : %s' % info)
        print('  OutputCondition     : %s' % cond)
        print('  DestOutputProfile   : xref %s' % dest)

    if not found or found[0][3] is None:
        raise SystemExit('找到 OutputIntent 但沒有 DestOutputProfile,無法取出 ICC。')

    x, info, cond, dest = found[0]
    icc = doc.xref_stream(dest)
    out = args.out or os.path.join('profiles', (info or 'extracted').replace(' ', '_')
                                   .replace('(', '').replace(')', '') + '.icc')
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    open(out, 'wb').write(icc)
    print('\nICC 已取出: %s  (%.2f MB)' % (out, len(icc) / 1e6))

    try:
        from PIL import ImageCms
        p = ImageCms.getOpenProfile(out)
        print('驗證:')
        print('  描述       : %s' % ImageCms.getProfileDescription(p).strip())
        print('  色彩空間   : %s' % p.profile.xcolor_space)
        print('  連接空間   : %s' % p.profile.connection_space)
        print('  ICC 版本   : %s' % p.profile.version)
    except Exception as e:
        print('!! 驗證失敗(可能不是合法 ICC): %s' % e)

    print('\n接著可以:\n  py scripts/impose.py ... --cmyk %s' % out)


if __name__ == '__main__':
    main()
