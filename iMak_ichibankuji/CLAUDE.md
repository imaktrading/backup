# iMak_ichibankuji プロジェクト

1kuji.com の商品ページから賞別データをスクレイピングし、eBay FileExchange CSV を自動生成するツール。

## iMak Trading Japan 共通ルール

### eBay FileExchange CSV 出力規約

1. CSV出力は `csv.writer` + `quoting=csv.QUOTE_NONNUMERIC` + `encoding="utf-8"`（BOMなし）で統一する（gshock_to_csv.py / psa_to_csv.py と同じ方式）
2. Item Specifics の列名は `C:` で始める（`*C:` は使わない）
3. ストアカテゴリの列名は `StoreCategoryID` を使う（`StoreCategory` ではない）
4. Description 列は `*Description` の1列のみ。重複列を作らない
5. ConditionDescription 列は ConditionID=3000（Pre-owned）の場合のみ出力

### Description 生成パターン（全プロジェクト共通）

1. テンプレートHTMLファイルをそのまま読み込む（この場合 ICHIBANKUJI.txt）
2. `build_specs_html()` で Specifications ブロックを `<ul>` で生成
3. `build_description()` で `<p><span style="text-decoration: underline;"><strong>Shipping` マーカー直前に挿入
4. マーカーが見つからない場合はテンプレート末尾に追加するフォールバック

### 共通固定値

- ScheduleTime: 2週間後（UTC）
- ReturnProfileName: customer1
- PaymentProfileName: SALE
- PayPalAccepted: 1
- BestOfferEnabled: 1
- Format: FixedPrice
- Duration: GTC
- Action列: SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8

### DDP送料テーブル（全プロジェクト共通）

価格帯に応じた ShippingProfileName: <39, 40-60, 60-100, 100-200, 200-300, 300-400, 400-500, 500-600, 600-800, 800-1000

## 出品対象ルール

1. **フィギュアのみ出品する** - タオル、マグカップ、アクリル、ぬいぐるみ、キーチェーン等の非フィギュア商品はスキップ
2. **10cm未満はスキップ** - ちょこのっこ等の小型フィギュアは利益が出ないため除外
3. 非フィギュア判定は日本語キーワード + Claude API の二重チェック

## eBayキーワード最適化ルール

タイトル生成時、`C:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\iMakKeywords\Collectibles_2026Q1.pdf`（Animation Art & Merchandise）の上位キーワードを最優先で盛り込む。検索されないタイトルは意味がない。

### PDF上位キーワード（一番くじフィギュア関連抜粋）

- #1 `anime figure` / #63 `anime figures` — **最重要。必ず入れる**
- #3 `one piece` / #26 `one piece figure`
- #8 `jujutsu kaisen`
- #30 `dragon ball` / #55 `dragon ball figure`
- #39 `my hero academia`
- #25 `sailor moon`
- #44 `demon slayer` / #74 `demon slayer figure`
- #32 `japan` — 一番くじは日本限定なので差別化になる

### タイトルへの反映方針

- `Figure` は必ず入れる（#1 `anime figure` に部分マッチ）
- フランチャイズ名はPDFのキーワードそのままの表記を使う（例: `My Hero Academia` not `Boku no Hero`）
- キャラ名は必ず入れる（バイヤーはキャラ名で検索する）
- `Bandai` は文字数に余裕があれば入れる（ブランド検索する人もいる）
- `Japan` は一番くじの場合は入れてよい（#32にランクイン + 日本限定の差別化）
- キーワードの羅列はNG — 何の商品かわかるタイトルにする

## タイトルルール

1. フォーマット: `Ichiban Kuji [IP/Series] [Prize] [Character] [Figure Type] Bandai New`
2. 最大79文字厳守、70-79文字を目標にできるだけ埋める
3. 必ず含める: 賞名(A Prize等)、キャラクター名
4. "Japan" は入れない（出品者の調査ワードであり購入者の検索ワードではない）
5. 文字数超過時は "Bandai" や "New" を削る

## CSV出力設定（一番くじ固有）

- カテゴリ: 261055 (Collectibles > Animation Merchandise > Figures & Statues)
- ConditionID: 1000 (New)
- Location: Osaka fu
- デフォルト価格: $50.00
- PicURL: 公式OGP画像 + ウォーターマーク画像のパイプ区切り

## Description生成（一番くじ固有）

- ICHIBANKUJI.txt をベースHTMLテンプレートとして使用
- Specs: Series, Prize, Character, Figure Type, Size(cm/in), Material(PVC), Brand(Bandai), Year

## ストアカテゴリ

- StoreCategoryID: 42133037010 (固定)
- StoreCategory2: フランチャイズ別マッピング
  - Dragon Ball: 41829920010
  - One Piece: 41830031010
  - My Hero Academia: 41830032010
  - Demon Slayer: 41833121010
  - Sailor Moon: 41834947010
  - Jujutsu Kaisen: 41834948010
  - Precure: 41834949010
  - Gundam: 41834950010
  - デフォルト: 41861579010 (Figures > Others)

## Item Specifics（一番くじ固有）

- Brand: Bandai（固定）
- Material: PVC（固定）
- Color: Multicolor（固定）
- Theme: Anime & Manga（固定）
- C:Series: "Ichiban Kuji"（固定）
- Country of Origin: Does Not Apply
- Original/Licensed Reproduction: Original
- Character, Franchise, Year: Claude APIが生成

## 技術的注意事項

- 1kuji.com はJS描画のためSelenium（undetected-chromedriver）が必須（requests不可）
- スクロールして遅延ロードを発火させる必要あり（scrollTo → 2秒待機 → scrollTo(0,0)）
- ラストワン賞はサイズ記載なしのパターンがあるので別途正規表現で拾う
- ダブルチャンスキャンペーンは「■当選数」の有無で検出して重複除外する
- Claude APIのレート制限対策として各賞間に2秒待機
- CustomLabel はASCII文字のみで生成: `KUJI-{franchise8文字}-{character6文字}`
- Item Heightのフォールバック: Claudeが返せない場合は size_cm / 2.54 で自動計算
