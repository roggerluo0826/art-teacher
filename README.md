# 美術小老師 (art-teacher)

Claude Code / Claude Agent Skill — 把一張已定稿的券圖,變成一疊編號不重複的印刷用 PDF。

> 美術老師已經把券畫好了。你的工作是把它印很多份、每份編號不同。
> 原圖一個像素都不能動,只有編號那幾個字換掉。**你不是設計師,你是印刷廠。**

## 這個技能解決什麼

你有一張券/票/抽獎券/貼紙的圖(PNG),上面印了一組編號(例 `HMS001`)。
你要 150 張,編號從 `HMS001` 排到 `HMS150`,拼成 A4 每頁 12 張拿去印。

手工做要複製貼上 150 次、改 150 次編號,錯一張就要重印全部。
在 Canva 之類的 GUI 裡自動化更慘(版面常是表格,券在儲存格裡,只能靠像素點擊)。

這個技能把它變成四行指令,而且**每一步都有客觀驗證**。

## 成果

實際案例(哈瑪星商圈券 150 張,雙面,已實際印出驗證):

| 項目 | 結果 |
|---|---|
| 頁數 | 單面 13 頁 / 雙面 26 頁(F1,B1,F2,B2…) |
| 編號 | HMS001–HMS150,無重複、無缺漏、順序正確 |
| 檔案大小 | **0.22 MB** 單面 / 0.50 MB 雙面(底圖只嵌一次,編號為向量文字) |
| 有效解析度 | 534 DPI(正面)/ 583 DPI(背面) |
| 字體比對 | Arial Bold,IoU 0.79(原字體不在本機) |
| 正背對齊 | 13 張紙逐格吻合,含不滿版的最後一張(6/6) |

**實際印出來正確的設定**(見 `references/printing.md` 開頭的完整配方):
驅動 PDL 用 **KPDL(PostScript)**、送 **RGB 版**、**實際大小**、**雙面+長邊翻頁**。

## 用法

```powershell
$env:PYTHONUTF8=1

# 1. 讀圖:找出編號位置、量測、確認能不能無痕塗掉
py scripts/inspect_art.py 券.png --text HMS001 --color FF3131 --region top-right --out inspect.json

# 2. 配字體:像素疊合 IoU 客觀挑最接近的系統字型
py scripts/match_font.py inspect.json --out font.json --overlay overlay.png

# 3. 拼版:塗掉舊編號、印上流水號、拼成 N-up PDF
py scripts/impose.py inspect.json font.json --prefix HMS --digits 3 --start 1 --count 150 \
   --cols 2 --rows 6 --out out.pdf

# 4. 驗證:從 PDF 把編號抽回來比對(必須 exit 0),並輸出預覽圖親眼看
py scripts/verify_pdf.py out.pdf --prefix HMS --digits 3 --start 1 --count 150 \
   --cols 2 --rows 6 --proof proof

# 5.(要印背面才需要)交錯成 F1,B1,F2,B2... 給印表機雙面列印
py scripts/duplex.py out.pdf 背面.png --out duplex.pdf --flip long
```

> **用 `py` 不要用 `python`。** PATH 上的 `python` 多半是 Microsoft Store 的 stub,
> 沒有輸出、回 exit 9009/49,會讓你以為程式壞了。

## 印出來顏色不對?先看 `references/printing.md`

**不要先動檔案。** 真實案例:為了「印出來比較淡」,依序換 ICC profile、補 OutputIntent、
升 PDF 版本、換影像編碼、換解析度,甚至直接拿參考檔的 CMYK 像素當底圖——
**CMYK 色值比對到 0 差,實際列印毫無改變**。

真因是印表機驅動走 **PCL XL**,而 PCL XL 是 **RGB only、沒有 ICC 色彩管理**——
所有 CMYK 資料在送到印表機前就被丟掉了。把 PDL 改成 **KPDL(PostScript)** 後立刻正常。

**先做這兩件事(五分鐘):**
1. 同一份檔案拿到**另一台電腦**印。不一樣 → 檔案沒問題,是電腦。
2. 查驅動的 **PDL**:列印對話框 → 進階 → 有沒有「PostScript 選項」區塊。

## 設計上的堅持

- **絕不變形**:券高一律由原圖長寬比算出,寧可留白。
- **無痕塗白**:動手前先驗「遮罩框外框是否單一色」,不是就停下來問人,不硬塗。
- **不猜字體**:用 IoU 疊合客觀排序,並產出疊合圖讓人親眼確認。原字體不在本機時,誠實說「這是最接近的替代」。
- **反向驗證**:從產出的 PDF 把編號抽回來比對,不是「跑完沒報錯就算過」。
- **檔案要小**:底圖只嵌一次 + 向量編號 → 0.22MB。

## 需求

- Python 3.10+
- `pillow` `numpy` `reportlab` `pymupdf`

```
pip install pillow numpy reportlab pymupdf
```

## 檔案

```
SKILL.md                    技能本體(給 Claude 讀)
references/printing.md      印出來顏色不對時的排查流程(PDL / 驅動 / 縮放)
references/pitfalls.md      踩過的坑與對策(每一條都出過包)
references/imposition.md    拼版數學、出血裁切、CMYK、印刷規格
scripts/inspect_art.py      第1步 讀圖
scripts/match_font.py       第2步 配字體
scripts/impose.py           第3步 拼版
scripts/verify_pdf.py       第4步 驗證
scripts/duplex.py           雙面:把背面圖交錯進正面 PDF(F1,B1,F2,B2…)
scripts/extract_icc.py      從既有 PDF 挖出它用的 ICC profile
scripts/color_probe.py      色彩管線診斷頁(一次印一張定位問題)
```

## 安裝成 Claude Code skill

把整個資料夾放進 `~/.claude/skills/art-teacher/`,或在專案裡 `.claude/skills/art-teacher/`。
