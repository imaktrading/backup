# iMakG-shock プロジェクト

CASIO公式ページ（casio.com/jp）からG-SHOCKの仕様をスクレイピングし、eBay FileExchange CSVを自動生成するツール。

## iMak Trading Japan 共通ルール

### eBay FileExchange CSV 出力規約

1. CSV出力は `csv.writer` + `quoting=csv.QUOTE_NONNUMERIC` + `encoding="utf-8"`（BOMなし）で統一
2. Item Specifics の列名は `C:` で始める（`*C:` は使わない）
3. ストアカテゴリの列名は `StoreCategoryID` を使う（`StoreCategory` ではない）
4. Description 列は `*Description` の1列のみ。重複列を作らない

### Description 生成パターン（全プロジェクト共通）

1. テンプレートHTMLファイルをそのまま読み込む（この場合 GSHOCK.txt）
2. `build_specs_html()` で Specifications ブロックを `<ul>` で生成
3. `build_description()` で `<p><span style="text-decoration: underline;"><strong>Shipping` マーカー直前に挿入
4. マーカーが見つからない場合はフォールバックHTML生成

### 共通固定値

- ScheduleTime: 2週間後（UTC）
- ReturnProfileName: customer1
- PaymentProfileName: SALE
- Format: FixedPrice / Duration: GTC
- Action列: SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8

### DDP送料テーブル（全プロジェクト共通）

価格帯に応じた ShippingProfileName: <39, 40-60, 60-100, 100-200, 200-300, 300-400, 400-500, 500-600, 600-800, 800-1000

## eBayキーワード最適化ルール

タイトル生成時、`C:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\iMakKeywords\Jewelry_Watches_2026Q1.pdf` の上位キーワードを最優先で盛り込む。検索されないタイトルは意味がない。

### PDF上位キーワード（G-SHOCK関連抜粋）

- #8 `mens watches` / #12 `watch men` / #22 `casio watch men`
- #28 `casio` / #33 `g shock` / #35 `g shock watches men` / #63 `casio g shock`

### 文字数を稼ぐための削除対象

- **型番ハイフンなし重複は削除**（例: GM5600YRA8JF → 14文字浪費。CustomLabel/Item Specificsに入っている）
- **発売年は削除**（バイヤーは年で検索しない）
- **"Japan" は削除候補**（Locationフィルタで表示される）

### 空いた文字数に入れるべきキーワード

- `Mens` — #8, #12, #22, #35 に部分マッチ
- `Digital` or `Analog` — 商品説明 + 検索ワード
- 実際のカラー名（Black/Silver/Green等）— 色で検索する人は多い

### 検証済み実績

GM-5600YRA-8JF で旧タイトル→新タイトルにした結果、PDF上位キーワードマッチ数が **4個→8個に倍増**。

## タイトルルール

1. フォーマット: `CASIO G-Shock {型番} [特徴] Mens [Display] Watch [Color] New`
2. 最大80文字厳守
3. 型番はハイフンあり1つのみ（ハイフンなし重複は不要）
4. `Mens` を必ず入れる（検索ボリューム上位）
5. Display（Digital/Analog）を入れる
6. Metal Covered系（GM系）は "Metal Covered" を追加
7. 機能キーワードは文字数に余裕があれば優先度順に追加: GPS > Bluetooth > Tough Solar > Multiband 6
8. キーワードの羅列はNG — 何の商品かわかるタイトルにする
9. 80文字超過時は末尾の単語から削除

## CSV出力設定（G-SHOCK固有）

- カテゴリ: 31387 (Jewelry & Watches > Watches > Wristwatches)
- ConditionID: 1000 (New)
- Location: Japan
- デフォルト価格: $100.00
- PicURL: GitHub上のウォーターマーク画像（出品後に手動差し替え）

## データ取得の優先順位

1. **CASIO公式ページ**（casio.com/jp）: Seleniumでスクレイピング。仕様テーブルのdt/dd構造 + li要素 + bodyテキストから抽出
2. **MODEL_OVERRIDES辞書**: CASIOページで取得できない year/weight/band_material を型番ベースで補完
3. **SERIES_WEIGHT辞書**: シリーズプレフィックスからデフォルト重量を取得
4. **g-central.com**: year, weight, case_size, thickness, band_material, dial_color を補完
5. **casiofanmag.com**: year, weight の最終フォールバック

## 自動判定ロジック

### モデル番号から自動判定されるフィールド

- **Band Color**: 型番末尾のカラーコード（1=Black, 2=Blue, 3=Green, 4=Red, 5=White, 7=White, 8=Orange, 9=Yellow）
- **Band/Strap**: GMW/MRGG/MTG系 → Bracelet、その他 → Two-Piece Strap
- **Band Material**: GMW/MRGG/MTG系 → Stainless Steel、その他はCASIOページから取得
- **Tough Solar**: GW/GBX/GBD/GBA/GST/GMW/GWG/GPR/GWN系は自動追加
- **Movement**: タフソーラー → Solar Quartz、電波 → Radio Controlled Quartz
- **Display**: DW/GW/GX/GBD/GBX/GMW系 → Digital、GA/GST系 → Analog or Analog & Digital
- **Case Shape**: 5600系 → Square、その他 → Round
- **Metal Covered**: GM/GMW系 → true

### 日本語→英語マッピング

- 防水: 20気圧 → 200 m (20 ATM)
- バンド素材: 樹脂→Resin, ステンレス→Stainless Steel, カーボン→Carbon Fiber, Resin
- ガラス: サファイアガラス→Sapphire Crystal, 無機ガラス→Mineral Glass
- 機能: タフソーラー→Tough Solar, マルチバンド6→Multiband 6, 耐衝撃→Shock Resist

### Features 優先度（trim_features で65文字以内にカット）

GPS > Bluetooth > Tough Solar > Multiband 6 > Shock Resist > Tide Graph > Moon Data > World Time > Activity Tracker > ...

## ストアカテゴリマッピング

モデル番号プレフィックスで自動分類:
- DW-6900/DW-9600/GM-6900系: 41925816010
- DW-5600/GW-5000/GM-5600系: 41925784010
- GMW系 (FULL METAL): 41925819010
- GA-2100系: 41925817010
- G-SQUAD (GBD/GBA/GBX): 41925821010
- G-STEEL (GST): 41925820010
- Master of G (GWG/GPR/GWN): 41925819010
- フォールバック（アナログGA/GS/GM/GB/GR系）: 41927356010
- デフォルト: 41925822010

## casio_finder サブツール

eBay出品中リスト（Seller Hub CSV）とCASIO公式シリーズページを照合して未出品モデルを発見するツール。

- 入力: active_listings.csv（Seller Hubからダウンロード）
- 対象シリーズ: DW-6900, DW-5600, GA-2100, GA-110, GA-100, GX-56
- 出力: unlisted_models.csv（未出品モデル + NEW/限定フラグ + CASIO価格 + eBay競合検索URL）
- NEWフラグ・限定フラグも自動検出

## 技術的注意事項

- CASIOページはJS描画のためSelenium（undetected-chromedriver）が必須
- 仕様テーブルが遅延ロードされるため、スクロール + 最大10秒の待機ループが必要
- 仕様がbody.textに出ない場合はdt/dd要素から直接取得、さらにHTMLソース内のJSONからも抽出を試みる
- 正式型番（JF/JR付き）はページ本文から正規表現で取得
- Claude APIは使用していない（全てルールベース処理）
- eBay出力後の手動確認項目: Case Color / Band Color / Department / Style
