# iMakMercari プロジェクト

メルカリ商品管理シートからeBay出品用CSVを自動生成するツール。Porter（吉田カバン）とmontbell（モンベル）が主な対象。

## iMak Trading Japan 共通ルール

### eBay FileExchange CSV 出力規約

1. CSV出力は `csv.writer` + `quoting=csv.QUOTE_NONNUMERIC` + `encoding="utf-8"`（BOMなし）で統一
2. Item Specifics の列名は `C:` で始める（`*C:` は使わない）
3. ストアカテゴリの列名は `StoreCategoryID` を使う（`StoreCategory` ではない）
4. Description 列は `*Description` の1列のみ。重複列を作らない
5. ConditionDescription 列は ConditionID=3000（Pre-owned）の場合のみ出力
6. Country of Origin: 画像から確認できない場合は「Does not apply」を入れる。空欄だとeBay AIが勝手にJapan等を補完する

### Description 生成パターン（全プロジェクト共通）

1. テンプレートHTMLファイルをそのまま読み込む（この場合 USED.txt）
2. `build_specs_html()` で Specifications ブロックを `<ul>` で生成
3. `build_description()` で `<p><span style="text-decoration: underline;"><strong>Shipping` マーカー直前に挿入
4. マーカーが見つからない場合はフォールバックHTML生成

### 共通固定値

- ScheduleTime: 2週間後（UTC）
- ReturnProfileName: customer1
- PaymentProfileName: SALE
- PayPalAccepted: 1
- BestOfferEnabled: 1
- StartPrice: 100
- Format: FixedPrice / Duration: GTC
- Action列: SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8

### DDP送料テーブル（全プロジェクト共通）

価格帯に応じた ShippingProfileName: <39, 40-60, 60-100, 100-200, 200-300, 300-400, 400-500, 500-600, 600-800, 800-1000

## 商品特定ルール

1. 出品者のタイトル・商品説明は参考程度にとどめる。最終判断の根拠にしない
2. 商品の特定は必ず画像から自力で行う
3. 型番・シリーズ・サイズ・素材は画像内のタグや刻印から読み取り、Web検索で裏付けを取る
4. 出品者の記述を鵜呑みにしない（誤記・虚偽の可能性がある）
5. 画像から判別できない情報は「不明」と報告する。推測で埋めない
6. 型番（MPN）は画像のタグから読み取れた場合のみ記入。公式サイトからの推定は不可（同一製品名で複数型番が存在するため）

## ConditionDescription ルール

1. 出品者が明示した欠陥・傷・汚れは必ず記載する
2. 画像分析で出品者より悪い状態を発見した場合も必ず追記する
3. 出品者が書いていない良い情報は絶対に追加しない（例：A4 size compatible、使いやすい等）
4. 画像から読み取った情報でも、出品者が明示していない「良い評価」は記載しない
5. 不明な点は記載しない。推測で埋めない
6. 末尾は必ず "Please review all photos carefully before purchasing. Sold as-is." で統一
7. generate_csv.py では商品管理シートの「状態」「商品説明」欄からClaude APIで英訳・要約して自動生成

## スクリプト構成

### generate_csv.py（FileExchange CSV出力）

- items リストに商品データをハードコード → build_row() でCSV行生成
- 商品管理シート.csv から状態情報を読み込み、MercariURLで紐付け
- Claude APIで ConditionDescription を自動生成
- USED.txt + Specificationsブロック → *Description 列に出力

### mercari_to_ebay_csv.py（Claude API解析）

- 商品管理シート.csv を入力、写真URLから画像取得 → Claude APIに送信
- 全カテゴリ対応のSYSTEM_PROMPT（Porter/Tomica/UNIQLO UT/montbell/Vintage Toy/Fishing/Other）
- 出力は中間CSV（IS:フィールド名 形式）→ generate_csv.py でFileExchange形式に変換

## eBayキーワード最適化ルール

タイトル生成時、`C:\dev\iMak\iMakKeywords\` にある2026Q1キーワードPDFの上位キーワードを最優先で盛り込む。検索されないタイトルは意味がない。

### 該当PDF

- Porter → `Clothing_Shoes_Accessories_2026Q1.pdf`（Women's Bags & Handbags）
- Tomica → `Toys_Hobbies_2026Q1.pdf`
- UNIQLO UT / montbell → `Clothing_Shoes_Accessories_2026Q1.pdf`
- Fishing → `Sporting_goods_2026Q1.pdf`

### PDF上位キーワード（バッグ関連抜粋）

- #26 `coach shoulder bag` / #43 `coach crossbody bag` — バッグの種類+ブランドで検索される
- #36 `bag` / #68 `tote bag` / #58 `purse`
- #53 `brand street tokyo` — 日本からのブランド品出品の競合
- #52 `designer handbags` — ブランドバッグ全般
- #70 `women s bags handbags`

### Porter タイトルへの反映方針

- バッグの種類は具体的に（`shoulder bag`, `tote bag`, `crossbody bag`, `briefcase`）— バイヤーはスタイルで検索する
- `Yoshida Kaban` より `Porter` のほうが検索される（ブランド認知度）
- `Nylon` などの素材はバイヤーが検索する（素材で絞る人がいる）
- `Japan` / `Japanese` は入れてよい（日本ブランドの差別化）
- `Pre-owned` は必須（Conditionフィルタだけでなくタイトルでも明示）
- キーワードの羅列はNG — 何の商品かわかるタイトルにする

## タイトルルール（Porter）

- フォーマット: `Porter [Series] [Style] [Color] [Material] Pre-owned Japan`
- 最大80文字、末尾は必ず "Pre-owned Japan"
- シリーズ名（Tanker/Heat/Smoky/Lift/Current/Force等）を必ず含める

## CSV出力設定（Porter固有）

- カテゴリ: 52357 (Bags & Luggage)
- ConditionID: 3000 (Pre-owned)
- Location: Japan
- StoreCategoryID: 41828940010 (Backpacks & Bags)
- ShippingProfileName: 60-100（固定）

## Description生成（Porter固有）

- USED.txt をベースHTMLテンプレートとして使用
- Specs: Brand(Porter/Yoshida Kaban), Series, Style, Material, Lining, Color, Width/Height/Depth, Closure, Handle, Hardware, Origin

## Item Specifics（Porter固有）

- Brand: Porter（固定）
- Department: Unisex
- Country of Origin: Japan
- Vintage: No / Handmade: No
- Style, Material, Fabric Type, Color, Closure, Pattern, Handle Style, Lining Material, Hardware Material, Handle/Strap Material, Product Line, Occasion, Bag Width/Height/Depth: 商品ごとに設定

## タイトルルール（montbell）

- フォーマット: `montbell [Product Name] [Color] US [Size] (JP [Size]) Pre-owned Japan`
- ブランド名は小文字 `montbell`（ハイフンなし）
- 最大80文字、末尾は必ず "Pre-owned Japan"
- JPサイズ→USサイズ変換: JP XS→US XXS, JP S→US XS, JP M→US S, JP L→US M, JP XL→US L

## CSV出力設定（montbell固有）

- カテゴリ: 57988 (Men's Coats, Jackets & Vests)
- ConditionID: 3000 (Pre-owned)
- Location: Japan
- StoreCategoryID: 41828939010 (Outdoor Jackets)
- ShippingProfileName: 価格帯に応じたDDPテーブルから選択

## Item Specifics（montbell/衣類 - 検索ボリューム順）

### Required
- Brand, Type, Size, Size Type, Color, Department, Outer Shell Material, Style

### Additional（検索ボリューム順、全て入力推奨）
- Lining Material (~915K) — Nylon / Mesh 等
- Insulation Material (~561K) — Does not apply（シェルの場合）
- Theme (~481K) — Outdoor
- Features (~451K) — Hooded, Lightweight, Drawstring, Pockets 等
- Fabric Type (~449K) — Nylon 等
- Pattern (~324K) — Solid / Colorblock
- Accents (~320K) — Logo
- Model (~197K) — 画像のタグから確認できた場合のみ
- Product Line (~144K) — Wind Blast / Tanker 等（確認できた場合のみ）
- Closure (~123K) — Full Zip / Half Zip
- Performance/Activity (~115K) — Hiking, Outdoor
- Season (~67K) — Spring, Fall 等
- Occasion (~28K) — Casual, Outdoor
- Fit (~24K) — Regular
- Collar Style (~7K) — Hooded
- Country of Origin — 画像から確認できた場合のみ。不明なら Does not apply
- MPN — 画像のタグから確認できた場合のみ
- UPC — Does not apply

## 公式画像リファレンス

### Porter（吉田カバン）
- ベースURL: `https://img-yoshida.freetls.fastly.net/yoshidakaban/image_item/{productId3桁}/{productId}/{productId}{colorCode}_b.jpg`
- カラーコード: 01=Black, 91=Silver Gray, J5=Sage Green
- 詳細写真: `{productId}_db01.jpg` ~ `{productId}_dbNN.jpg`

### montbell
- ベースURL: `https://montbell.jp/common/images/product/prod_k/k_{productId}_{colorCode}.jpg`
- サムネイル: `prod_c/c_{productId}_{colorCode}.jpg`
- 詳細: `cut_k/ck_{productId}_{seq}_{colorCode}.jpg`
- カラーコード例: bk=Black, nv=Navy, dgn=Dark Green, prbl=Primary Blue, og=Orange

### 画像テンプレート
- テンプレート: `c:\Users\imax2\OneDrive\デスクトップ\ebay\ebay店舗ロゴ\copyright_bottom_left_800x800.png`（800x800、©iMak Trading Japan）
- 公式画像をテンプレートに合成 → GitHub (imaktrading/ebay-images) にホスティング
- PicURL: 公式画像（あれば先頭） + メルカリ写真（パイプ区切り）

## 商品管理シート.csv

- エンコーディング: UTF-8（cp932ではない）
- 主要カラム: URL, タイトル, 状態, 商品価格, 写真URL, 商品説明, Title, Description, ConditionID
- MercariURLでgenerate_csv.pyのitemsリストと紐付け

## 技術的注意事項

- mercari_to_ebay_csv.py の画像取得: メルカリShopsとメルカリ通常でURL処理が異なる
- Claude APIモデル: claude-sonnet-4-20250514
- print文にUnicode絵文字を使うとcp932ターミナルでUnicodeEncodeError → ASCII文字に置換すること
- GitHub画像ホスティング: gh CLI (`gh auth login`) → imaktrading/ebay-images リポジトリ
