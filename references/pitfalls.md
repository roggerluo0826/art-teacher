# 踩過的坑

每一條都是實際出過包的,不是理論。

---

## 環境

### `python` 沒有輸出、回 exit 9009 或 49

**症狀**:`python -c "import docx; print(1)"` 完全沒輸出,exit code 49 或 9009。會讓你以為套件沒裝、程式壞了,開始瞎修。

**原因**:Windows 的 PATH 上有兩個 `python.exe`,Microsoft Store 的 **App Execution Alias stub 排在前面**:

```
C:\Users\<你>\AppData\Local\Microsoft\WindowsApps\python.exe   <- stub,先被找到
C:\Users\<你>\AppData\Local\Programs\Python\Python312\python.exe <- 真的
```

stub 的用途是「引導你去 Store 安裝 Python」,你已經裝了 Python 但沒從 Store 裝,它就默默失敗。

**對策**:一律用 **`py`**(Python Launcher),或給完整路徑。
用 `Get-Command python -All` 可以看到 PATH 上所有的 python。

### cp950 編碼炸掉

繁中 Windows 預設 cp950,印中文或寫檔會 `UnicodeEncodeError`。

```powershell
$env:PYTHONUTF8=1
```

腳本裡也已經加了 `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')`。

### 檔案「找不到」

先 `Get-ChildItem <資料夾>` 列出實際內容再說。**使用者很可能已經把檔案改名或重新匯出了**——曾經 `0.png` 變成 `1.png`,而且新檔的尺寸從 2170×946 變成 2017×946。不要假設檔名和尺寸沒變,每次都重新 inspect。

---

## 讀圖

### 顏色偵測抓到整張圖

**症狀**:找紅色編號,結果 bbox 是 `x191..1969 y102..812`——幾乎整張圖。

**原因**:圖上別的東西也是紅色。實際案例:券左下角的貨櫃船,貨櫃是紅的。

**對策**:`--region` 限縮搜尋範圍。腳本會在 bbox 寬度接近搜尋範圍時警告。

### bbox 高度 ≠ 字高

**症狀**:拿整串 bbox 的高度當 cap height 去反推字級,字就是差一點點。

**原因**:圓形字元(`O` `0` `S` `C` `G`)有 **overshoot**——為了視覺上等高,它們會稍微超出 cap line 上下各 1px。所以 `HMS001` 的整串 bbox 高 36,但 `H` 只有 35。

**對策**:把字元逐一切開,用**平頂平底的字元**(`H` `M` `E` `T` `1` `4` `7`)量 cap height 和基線。`inspect_art.py` 已經這樣做。

### 遮罩的驗證條件寫錯

**症狀**:寫了個斷言「遮罩框內非編號色的像素應該 >99% 是純白」,結果實際只有 95.87%,斷言擋下來,以為底不乾淨。

**原因**:那 4% 不是別的圖案,是**紅字本身的反鋸齒淡粉色邊緣**(如 `#FFAFAF`),顏色偵測器抓不到它(它不夠紅),但它也不是純白。而這些像素本來就會被塗掉,根本不需要檢查。

**對策**:要驗的是**遮罩框的外框一圈**是不是單一色。外框單色 → 塗掉內部必然無縫。框內是什麼不重要。

### 底不是純色怎麼辦

`mask_ring_uniform` 是 `false` 時,代表編號壓在漸層、照片或圖案上。選項:

1. **請使用者把編號那層在原始設計裡隱藏後重新匯出**(最乾淨,一次動作)。
2. **縮小 `--pad`**——也許編號其實壓在一小塊純色上,只是外擴太多碰到別的東西。
3. **改用 inpainting 補背景**——會失真,只適合雜訊背景,不建議用在印刷品。
4. **在編號位置疊一個白底色塊**——會改變設計外觀,必須先問使用者。

**不要自己決定,問使用者。**

---

## 字體

### 不要用肉眼挑字體

**症狀**:看起來 Noto Sans 很像,選了它,印出來怪怪的。

**原因**:實際案例中 Noto Sans TC Bold 的「**1**」有**底座橫畫**,原圖的「1」只有左上小旗標、沒有底座。這在小字級下肉眼很難察覺,IoU 疊合一看就露餡(那塊底座是一整片綠色)。

**對策**:用 `match_font.py` 的 IoU 排序,並用 Read 看 `overlay.png`。實際案例的排名:

| 字體 | IoU |
|---|---|
| Arial Bold | 0.786 |
| Segoe UI Bold | 0.736 |
| Trebuchet Bold | 0.563 |
| Noto Sans TC Bold | 0.554 |

### 數字是否等寬會影響對齊

Arial 的數字是**等寬(tabular)**,所以 `HMS001` 和 `HMS150` 排版寬度完全相同(實測 308.591),可以安心左對齊,150 張編號都會落在同一位置。

但不是所有字體都這樣。`match_font.py` 會檢查並回報。**不等寬**的話,不同編號會長短不一,得改成右對齊或改用等寬字體。

---

## 產 PDF

### `canvas.setCharSpace()` 不存在

reportlab 的 `setCharSpace` 在 **text object** 上,不在 canvas 上:

```python
# 錯
c.setFont('F', 10); c.setCharSpace(2); c.drawString(x, y, s)
# 對
to = c.beginText(x, y)
to.setFont('F', 10); to.setCharSpace(2); to.setFillColorRGB(r, g, b)
to.textOut(s); c.drawText(to)
```

### 檔案幾百 MB

150 張券每張都貼一次圖 → 圖被嵌入 150 次。

**對策**:建立**一個** `ImageReader` 物件重複傳給 `drawImage`,reportlab 會重用同一個 XObject。實測 150 張券的 PDF 從理論上的數百 MB 降到 **0.22MB**,而且編號是向量,放到多大都銳利。

驗證方式:`verify_pdf.py` 會數 PDF 裡不重複的影像物件數,應該是 **1**。

---

## 驗證

### 從 PDF 抽編號抽到 0 個

**症狀**:PDF 畫面上明明看得到 `HMS001`,`page.get_text('words')` 找 `HMS\d{3}` 卻抓到 **0** 個,以為編號根本沒畫上去。

**原因**:`setCharSpace` 的字距夠寬時,**PyMuPDF 會把每個字元切成獨立的 word / span**,文字實際變成 `"H M S 0 0 1"`,每個 span 只有一個字元。正則當然對不上。

**對策**:用**行層級**把 spans 的 text join 起來、去掉空白,再比對:

```python
t = ''.join(sp['text'] for sp in line['spans']).replace(' ', '')
```

`verify_pdf.py` 已經這樣做。

### 頁尾標示混進驗證結果

頁尾若印了 `HMS001 - HMS012` 之類的標示,會被當成編號抽出來,數量就多了。

**對策**:用字型過濾——編號用 `CodeFont`(Arial-BoldMT),頁尾用 Helvetica。`verify_pdf.py` 先找出最常出現的編號字型,再只認那個字型的行。

### 「腳本沒報錯」不等於「印出來對」

驗證腳本只能證明**編號的文字內容和座標**對。它證明不了:

- 編號有沒有壓到圖上的其他元素
- 塗白有沒有留下痕跡
- 券有沒有被裁到

**一定要用 Read 親眼看 proof 圖。**

---

## Canva

### 12 格是「表格」,券在儲存格裡

實際案例:使用者的 A4 版面看起來是 12 格拼版,點下去才發現整頁是一個 **2×6 的 Canva 表格**,券是放在儲存格內的圖。工具列出現表格圖示就是它。

**不要試圖用瀏覽器自動化在 Canva 上改 150 次編號。** Canva 是 canvas 應用,元素不在 DOM 裡,只能靠像素點擊,又慢又容易錯位,而且很容易誤改到使用者的設計。

### Canva Bulk Create 是「一列 = 一頁」

若使用者堅持要留在 Canva 用大量建立:**150 列資料會產生 150 頁、每頁一張券**,不是每頁 12 張。

要每頁 12 張,CSV 必須做成 **12 欄 × 13 列**(一列 = 一張 A4),欄位 `code1`..`code12` 分別連到版面上 12 個文字框。

### Canva CLI 不能編輯設計

`@canva/cli` 是給 **Apps SDK** 開發用的鷹架工具(建立跑在 Canva 裡的外掛 App),**不能**登入帳號去改既有設計的元素。Canva 也沒有可編輯既有設計內容的公開 API(Connect API 只能建立設計、上傳素材、匯出;Autofill API 需要 Enterprise 方案 + Brand Template)。

使用者說「連接 Canva CLI 幫我排版」時,要先講清楚這條路走不通,不要浪費時間去裝。
