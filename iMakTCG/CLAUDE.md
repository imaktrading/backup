# iMakTCG プロジェクト

PSA鑑定番号からpsacard.comの鑑定ページをスクレイピングし、Claude APIでカード情報を解析して、eBay FileExchange CSVを自動生成するツール。

※ iMak Trading Japan 全プロジェクト共通ルール（CSV出力規約、Description生成パターン、共通固定値、DDP送料テーブル）はグローバル `~/.claude/CLAUDE.md` を参照。

## TCG固有のDescriptionポリシー

- TCGはDescription共通テンプレート（PSA10.txt）をそのまま使用、カード個別のSpecificationsブロック挿入はなし
- ReturnProfileName: **No return**（他プロジェクトの customer1 と異なる）

## eBayキーワード最適化ルール

タイトル生成時、`C:\dev\iMak\iMakKeywords\Toys_Hobbies_2026Q1.pdf`（CCG Individual Cards）の上位キーワードを最優先で盛り込む。検索されないタイトルは意味がない。

### PDF上位キーワード（TCG関連抜粋）

- #7 `psa 10` / #9 `psa`
- #6 `one piece card` / #13 `one piece` / #20 `one piece psa 10` / #25 `one piece tcg`
- #63 `monkey d luffy`（One Piece キャラ名が直接検索されている）
- #30 `dragon ball` (※ "dragon ball psa 10" は未ランクインだが "psa 10" との複合で拾える)
- Gundam CCG は上位キーワードになし → "psa 10" + キャラ名 + ゲーム名で拾う

### タイトルへの反映方針

- `PSA 10` は先頭固定（#7 で高ボリューム確認済み）
- ゲーム名は短縮名を使いつつもPDFのキーワードに合わせる（例: `One Piece TCG` は #25 にそのまま入っている）
- キャラ名は必ず入れる（#63 `monkey d luffy` のように直接検索される）
- カード番号はバイヤーが検索するので残す
- キーワードの羅列はNG — 何のカードかわかるタイトルにする

## タイトルルール

1. フォーマット: `PSA 10 [Game Short] [Set] #[Number] [Card Name] [Rarity/Feature]`
2. 最大80文字厳守、70-80文字が理想
3. "PSA 10" を必ず先頭に置く
4. ゲーム短縮名: Dragon Ball SCG / One Piece TCG / Gundam CCG / Pokemon
5. "Japanese", "GEM MT", "Japan" は入れない
6. 80文字超過時はSet名を削る（Item Specificsに入っているため省略可）
7. Claude APIで生成 → 失敗時はルールベースのbuild_title()でフォールバック

## CSV出力設定（TCG固有）

- カテゴリ: 183454 (Collectible Card Games)
- ConditionID: 2750 (Graded - Gem Mint)
- CD:Professional Grader: 275010
- CD:Grade: 275020
- CDA:Certification Number: PSA鑑定番号
- Location: Osaka
- デフォルト価格: $100.00
- ReturnProfileName: **No return**（他プロジェクトの customer1 と異なる）
- PicURL: GitHub上のウォーターマーク画像

## ゲーム判定ロジック（detect_game_info）

PSAラベルのBrandフィールドから自動判定:
- "DUAL IMPACT" / "NEWTYPE RISING" / "STEEL REQUIEM" 等 → Gundam CCG + セット名マッピング
- "ONE PIECE" → One Piece Card Game
- "DRAGON BALL" → Dragon Ball Super Card Game（長いプレフィックスを除去してセット名を短縮）
- "POKEMON" → Pokemon

### Dragon Ballセット名短縮

`DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE BLAZING AURA` → `Blazing Aura` のように長いプレフィックスを除去

## Claude API 解析

- カード画像（PSAページから取得）+ PSAラベル情報を送信
- 返却JSON: title, card_name, rarity, features, card_type, attribute, cost, power, finish
- JSONパース失敗時は簡略プロンプトでリトライ（1回）
- タイトル80文字超過時は title=null でフォールバックに切り替え
- model: claude-sonnet-4-20250514
- system prompt: "You are a JSON-only response bot"（余計なテキストを防止）

## PSAラベル解析（parse_psa_page）

- パターン: `Brand #CardNumber Subject`
- Brandから年号（先頭4桁）を除去
- Subjectからレアリティ（末尾の LEGEND RARE/RARE+/COMMON等）を除去
- 発行年は「発行年」ラベルの次行から取得

## ストアカテゴリマッピング

フランチャイズ名で自動分類:
- Gundam: 42145683010
- One Piece: 42142742010
- Dragon Ball: 42154739010
- Pokemon: 42054519010
- NIKKE: 42144249010
- Hololive: 42144254010
- デフォルト: 42054516010

## Item Specifics（TCG固有）

- Manufacturer: Bandai（固定）
- Language: Japanese（固定）
- Country of Origin: Japan（固定）
- Age Level: 6+（固定）
- Material: Card Stock（固定）
- Card Size: Standard（One Piece）/ Japanese（その他）
- Card Condition: Near Mint or Better（固定）
- Grade: 10 / Professional Grader: PSA / Graded: Yes
- Game, Set, Card Type, Card Name, Character, Rarity, Features, Finish, Attribute, Cost, Power: Claude APIが生成

## CustomLabel命名規則

`{CardNumber}-PSA10`（例: FS03-15-PSA10）。CardNumberが空の場合は `PSA10-{CertNumber}`

## 技術的注意事項

- psacard.com はJS描画のためSelenium（undetected-chromedriver）が必須
- PSAページはja-JP版（/ja-JP/cert/）を使用
- ページ読み込み後5秒待機が必要
- カード画像はPSAページのimg要素からURL抽出（cert/card/psa/gradingを含むsrc）
- Claude APIのレート制限対策として各カード間に待機あり
- レアリティパターンは正規表現で末尾から除去（LEGEND RARE+, RARE+, COMMON+, PROMO等）
