# 拼版與印刷規格

## 基本算式

```
單張寬 cw = (頁寬 - 2 × 左右邊界) / 欄數
單張高 ch = cw × (原圖高 / 原圖寬)      ← 一律由原圖比例決定,絕不獨立指定
拼版區高 = ch × 列數
上下邊界 my = (頁高 - 拼版區高) / 2      ← 垂直置中,多出來的留白是正常的
```

**券高一定要從原圖比例算出來,不能自己指定。** 一旦獨立指定高度就會拉伸變形——這是印刷品最不可原諒的錯誤,而且客戶一眼就看得出來。

### 頁數

```
每頁張數 per = 欄數 × 列數
頁數 = ceil(總數 / per)
末頁張數 = 總數 % per  (為 0 則是滿版)
```

實際案例:150 張、每頁 12 張 → 13 頁,末頁 6 張。**先算給使用者看。**

## 有效 DPI

```
有效 DPI = 原圖寬(px) / (單張寬(mm) / 25.4)
```

- **300 DPI** 是印刷底線
- **< 300** → 原圖解析度不足,要告訴使用者去要更高解析度的圖
- **> 400** 沒有壞處,只是檔案大一點;由於底圖只嵌一次,實務上不必為此降採樣

實際案例:2170px 寬的圖印成 97mm 寬 → 568 DPI,綽綽有餘。

## A4 常見配置

A4 = 210 × 297 mm。以左右各留 8mm 計算:

| 欄 × 列 | 每頁 | 單張寬 | 適用長寬比 | 單張高 |
|---|---|---|---|---|
| 2 × 6 | 12 | 97mm | 2.13 | 45.5mm |
| 2 × 6 | 12 | 97mm | 2.29 | 42.3mm |
| 2 × 5 | 10 | 97mm | 1.8 | 53.9mm |
| 3 × 8 | 24 | 64.7mm | 2.0 | 32.3mm |
| 1 × 4 | 4 | 194mm | 2.5 | 77.6mm |

列數放不下時 `impose.py` 會直接報錯並告訴你需要多少 mm。

## 裁切標記

`impose.py` 預設在拼版區**外側**畫短標記(不跨過畫面),每個欄/列交界都有:

- 標記長 4mm,離拼版區 1mm
- 線寬 0.25pt
- 券之間**沒有間隙**——一刀切開兩張,最省紙也最好裁

`--no-cropmarks` 可關掉。

### 要出血怎麼辦

目前的做法是**無出血**:券之間共用裁切線,一刀兩斷。這適合:

- 自己用美工刀/裁紙機裁
- 券的四周不是滿版色塊(裁歪一點看不出來)

若印刷廠要求出血(通常 3mm),而且券是滿版設計,那**原圖本身就必須含出血**——這個技能不會替你生出血,因為它不知道邊緣該延伸什麼顏色。請使用者從原始設計檔重新匯出含出血的版本。

## 頁尾標示

每頁左下角會印一行灰色小字:

```
HMS  p.1/13   HMS001 - HMS012   (12)
```

方便印刷廠和你自己核對。它用 Helvetica,和編號的字型不同,所以驗證腳本能把它排除掉。

不想要的話直接改 `impose.py` 裡那段 `drawString`。

## CMYK

### reportlab 怎麼嵌 CMYK

實測結果(重要,因為 reportlab 文件沒講清楚):

| 餵給 `ImageReader` | PDF 內的色彩空間 | 編碼 |
|---|---|---|
| RGB PNG | `DeviceRGB` | Flate(無損) |
| **CMYK TIFF** | **`DeviceCMYK`** | **Flate(無損)** ← 用這個 |
| CMYK JPEG | `DeviceCMYK` | DCTDecode(**有損**) |

**用 CMYK TIFF。** JPEG 雖然也能得到 DeviceCMYK,但券這種大色塊平面設計,JPEG 會在色塊交界處產生 ringing 雜訊。TIFF 讓 reportlab 以 Flate 無損重新編碼,檔案也沒大多少(0.22 → 0.23 MB)。

驗證方式:PyMuPDF `doc.extract_image(xref)['colorspace']`,`4` 就是 CMYK、`3` 是 RGB。

### 轉換要走 ICC,不要用 PIL 的 `convert('CMYK')`

`img.convert('CMYK')` 是**naive 公式轉換**(`C = 255 - R` 之類),完全沒有色彩管理,印出來會差很多。

正確做法是 `ImageCms` 走 ICC:

```python
tr = ImageCms.buildTransformFromOpenProfiles(
    ImageCms.getOpenProfile(SRGB_ICC),
    ImageCms.getOpenProfile(CMYK_ICC),
    'RGB', 'CMYK', renderingIntent=ImageCms.Intent.PERCEPTUAL)
cmyk = ImageCms.applyTransform(rgb_img, tr)
```

Rendering intent 用 `PERCEPTUAL`(整體壓縮、保持色彩關係),適合這種插畫。
`RELATIVE_COLORIMETRIC` 會把色域外的色硬夾到邊界,飽和色會糊成一團。

### 編號色要走同一條路

編號是向量文字,顏色要用 `setFillColorCMYK`。**那個 CMYK 值必須用跟底圖同一個 ICC transform 算出來**,否則編號的紅和底圖的紅會是兩種紅。

`impose.py` 的 `rgb_to_cmyk_color()` 就是造一個 1×1 的 RGB 圖走同一條 transform,取出 CMYK 值。

### OutputIntent 不能省(實際踩過)

**沒有 OutputIntent 的 DeviceCMYK PDF,等於一堆沒有單位的數字。** `C44 M6 Y78 K16` 在不同 CMYK 空間裡是不同的顏色;沒有 OutputIntent,印表機/RIP 只能自己猜(通常套用內建預設),顏色就飄了,印刷廠也可能退件。

`impose.py --cmyk` 會自動把 ICC 嵌成 OutputIntent(`--no-output-intent` 可關)。代價是檔案變大——ICC 本身就有 3.4MB,所以 0.24MB 會變成 2.89MB。**這個大小是值得的。**

驗證:PDF Catalog 裡要有 `/OutputIntents`,且該物件要有 `/DestOutputProfile`。

### Canva 的「PDF 列印 + CMYK」到底做了什麼(逆向分析結果)

實測拆解 Canva Pro 匯出的 CMYK PDF:

| 項目 | Canva 的做法 |
|---|---|
| ICC profile | **GRACoL 2013 CRPC6 (ISO DIS 15339-2)** |
| Rendering intent | **Perceptual** |
| OutputIntent | 有,`/S /GTS_PDFX`,ICC 完整嵌入(3.46MB) |
| 影像 | **整頁壓平成一張 CMYK JPEG**(有損) |
| 解析度 | 390 DPI |
| 字型 | **0 個**——全部點陣化,沒有向量文字 |
| 頁面 | MediaBox 222.1×309.1mm / **TrimBox 210.1×297.1 / BleedBox 216.1×303.1**(3mm 出血) |
| 檔案 | 3.88MB(其中 3.46MB 是 ICC) |

**用 `scripts/extract_icc.py` 可以把那個 GRACoL profile 從 Canva 的 PDF 裡挖出來**,拿來餵 `impose.py --cmyk`,分色結果就會跟 Canva **完全一致**。實測(Perceptual):

| 顏色 | 我用挖出的 CRPC6 | Canva 實際圖中 | 差 |
|---|---|---|---|
| 天空藍 | C36 M2 Y2 K0 | C36 M2 Y2 K0 | **0** |
| 山丘綠 | C44 M6 Y78 K16 | C44 M6 Y78 K16 | **0** |
| 海水藍 | C80 M30 Y5 K9 | C80 M30 Y5 K9 | **0** |
| 沙灘米 | C2 M2 Y9 K0 | C2 M2 Y8 K0 | 1 |

**profile 選錯的影響遠大於方法。** 同樣的程式,改用 Japan Color 2001 Coated,山丘綠變成 `C55 M24 Y82 K0`——跟 Canva 差 Σ49,因為 Japan Color 幾乎不用黑版,GRACoL 用 GCR 把彩色墨換成 K16。

實務意義:**GCR 重的分色(多用 K、少用 CMY)在辦公室印表機上通常比較乾淨**,三色疊印在普通紙上容易糊、吃墨、發濁。

### CMYK 檔裡不要混 RGB

裁切線、頁尾標示也要用 `setStrokeColorCMYK` / `setFillColorCMYK`。混用 RGB 色的 PDF 送印刷廠會被退件或被對方自行轉換(結果不可控)。

裁切線用 `(0,0,0,1)` 純黑版(K100),不要用四色黑。

## 為什麼底圖只嵌一次很重要

`impose.py` 建立**一個** `ImageReader` 物件,150 次 `drawImage` 都傳同一個,reportlab 因此只嵌入一個 XObject。

| 做法 | 檔案大小 |
|---|---|
| 每張券各貼一次圖 | 數百 MB |
| 共用 ImageReader + 向量文字編號 | **0.22 MB** |

而且編號是向量,列印機用多少解析度都銳利,不會因為圖被降採樣而糊掉。

`verify_pdf.py` 會數不重複影像物件數,應為 **1**。
