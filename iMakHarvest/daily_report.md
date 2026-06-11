# iMakHarvest daily_report

## 2026-06-12 — Amazon seller 判定 FBA 誤検出バグ修正 + 376件 merchantId 再精査 + KEY空欄是正

### 決定

- **そもそもの抽出方針は「Amazon.co.jp 直販のみ keep」が正** (= 国内 third-party / Amazon US は両方除外)。
  user 指摘で再確認。 旧 flag_amazon_us_in_sheet.py の 'AMAZON_US' ラベルは誤り
  (= merchantId≠直販 を一律 US 扱い、 実体は国内 third-party の国内正規品が多数)。
- **selenium `_extract_seller` の FBA 誤検出が混入の根本原因** と特定。
  発送元(Ships from / 発送元) marker + body 全文マッチで、 第三者販売+Amazon発送(FBA) の
  国内 third-party を直販と誤判定 → run_harvest の seller!="Amazon.co.jp" gate をすり抜け。
  → 販売元 = buybox merchantId="AN1VRQENFRJN5" を authoritative signal に統一 (= HTTP 経路と同一)。
- **buybox rotation を新たに確認** (= Amazon の販売者は時間で入れ替わる)。
  旧 39 flag のうち 25件は rotation による誤flag (= 今は直販)、 真の非直販は 15件のみ。
  → 単発 snapshot flag は不安定。 再精査は merchantId + 非直販候補は確認 fetch 1回 で安定化。
- **KEY 空欄 12件の根本原因 = 型番の日本語直結** ("GWG-B1000-1AJFメンズ")。
  `\b` 境界が カタカナ/漢字も word 文字扱いで消え抽出漏れ。 → KEY抽出を ASCII境界+digit必須 に修正。
- **Q列 FLG 値は '非直販'** に統一 (= 'AMAZON_US' 誤称を廃し、 国内third-party/US を区別せず除外マーク)。

### 変更

- `scrapers/amazon_item_detail.py:520-536` SELLER_AMAZON_JP_MARKERS から発送系(Ships from/発送元)削除。
  `SELLER_AMAZON_MERCHANT_MARKER = '"merchantId":"AN1VRQENFRJN5"'` 追加。
- `scrapers/amazon_item_detail.py:645` `_extract_seller` 全面改修
  - step1: page_source の merchantId で直販判定 (= authoritative、 発送元に左右されない)
  - 旧 step2 (body 全文マッチ) を削除 (= FBA 誤検出の元凶)
  - fallback は buybox block 内「販売」marker のみ (= 発送 marker 除外済)
- `scrapers/amazon_item_detail.py:867` `_extract_product_id_estimated_from_title` 改修
  - `_KEY_MODEL_HYPHEN_RE` / `_KEY_MODEL_NOHYPHEN_RE` 新規 (= ASCII境界、 \b 非依存、 digit必須で series語除外)
- `tests/test_amazon_seller.py` 新規 8件 (= FBA 誤検出回帰防止)
- `tests/test_amazon_key_extract.py` 新規 11件 (= 日本語直結型番 / series語除外)
- `tools/reaudit_amazon_seller.py` 新規 (= 376行 merchantId 再精査 + Q列是正、 rotation 確認fetch付)
- `tools/backfill_key_from_title.py` 新規 (= 空欄KEY を修正済抽出で backfill、 Amazon fetch なし)
- `tools/flag_amazon_us_in_sheet.py` は旧版 (= 'AMAZON_US' 誤ラベル)、 reaudit が上書き是正済。

### 検証

- ✅ 全 pytest **693件 pass** (= 旧674 + seller8 + key11、 regression なし)
- ✅ 376件 再精査実機完走 (06:00-06:16): direct=361 / nondirect=15 / fetch失敗0 / captcha0
  - Q列書込 40件 = 旧誤flagクリア 25 + 非直販マーク 15
  - 非直販 15件の merchantId: A1EJGP084HULR(=真Amazon US: row74,83,91,92) + 国内third-party各種
- ✅ buybox rotation 実証: B0H2CLW4T2 / B0F9K112T9 が 05:15非直販 → 05:40以降 3回連続 direct
- ✅ KEY backfill 6件書込 (= row66 GWG-B1000-1AJF / 71 GWG-B1000-1A4JF / 87 GWA11001A3JF /
  189 MTG-B3000-1AJF / 228 GWG-B1000-3AJF / 356 DW-6900NNJ-1JR)。 KEY空欄 12→6 に。

### 物理削除 (= user 指示 2026-06-12「1,2 は削除」)

- **非直販 + バンド類 17行を物理削除** (= `tools/delete_nondirect_and_bands.py`)。
  - 非直販時計 13 + バンド類 4 (= 85,89,93,208)。 削除直前 rotation 再確認で直販復帰 0件 (= 全件安定)。
  - 削除後 実機検証: データ 376→**359行**、 残 非直販 0 / 残 バンド 0 / 残 KEY空欄 0。
  - → 中間スプシは「Amazon.co.jp 直販 G-shock 時計・全件KEYあり」のクリーン状態に。

### 下流是正 (= catalog dump、 user 指示 2026-06-12「そうした方がいい」)

- **catalog dump 4 file (375件)** に混入の非直販/バンド 17 ASIN 除外を Catalog Claude へ依頼。
  - 依頼書投入: `catalog/requests/2026-06-12_amazon_gshock_dump_nondirect_exclusion.md`
  - 17 ASIN を A(バンド4)/B(真Amazon US 4)/C(国内third-party 9) に分類し dump file map 付きで提示。
  - **Catalog 回答受領 (`_response.md`)・本件クローズ** (2026-06-12):
    - Amazon dump は未 merge (= catalog に 17 ASIN 0 hit、 amazon_available 列も無し) → 遡及是正不要。
    - `_amazon_jp_dumps/exclude_asins.json` 恒久リスト化で対応 (= 完全除外8 / 直販フラグ抑止9)。
    - dump JSON は seller-bug 証跡として温存 (= 非破壊・可逆を採用、 user 同意でクローズ)。

### 残・別 task

- レディース skip (= user 判断保留、 6/11)
- 他カテゴリ展開時の `is_gshock_item` プラガブル化 refactor

---

## 2026-06-11 (= 後半) — Amazon G-shock メンズ全網羅完了 (= HTTP filter + variant 補完 + monthly_sales)

### 決定

- **Amazon メンズ G-shock 全抽出 完了** (= 中間スプシ 376 行、 catalog dump 4 file 375 件)
  - 根拠: 6/11 終日 5 session 通し、 selenium / 拡張機能 / URL filter / attach / HTTP filter を順次検証 → 最終 HTTP filter で 100% 精度確立
- **HTTP filter 戦略採用** (= Gemini 助言 + merchantId AN1VRQENFRJN5 検証で 100% 精度確認)
  - selenium 環境では URL filter / 拡張機能ともに無効化される (= Amazon bot 検出) ことを実証
  - `requests + bs4` + `merchantId="AN1VRQENFRJN5"` grep で代替実装、 selenium 介さず Amazon 直販判定
- **拡張機能 (Amazon 3rd Party Seller Filter) 対応 + attach 方式** = 検証の結果 selenium 自動 navigate で効かないと判明 → HTTP に転換
- **AI 列 (= col 35、 KEY 型番)** に生 verbatim (= HQ 規約 2026-06-11)
- **V 列 (= col 22、 Amazon 月販売数)** に生 verbatim 「過去 1 ヶ月で N 点以上購入」 (= user 指示 2026-06-11)
- **Amazon US 並行輸入 1 件 (= B000FPVUJA)** reject (= merchantId 検証で 国内仕入不可商品除外)
- **variant 全展開 採用** (= 既存 119 ASIN seed → HTTP で variant 子 ASIN 取得 → 既存 dedup 後 selenium で 14 field 抽出)
- **catalog 投入 schema 確定** (= 14 field + variant_asins、 catalog は identity/在庫hint/画像のみ使用、 動的データは sourcing 層 = 中間スプシ責務)

### 変更

- `scrapers/amazon_search_http.py` 新規作成 (= HTTP-based URL 収集 + seller/brand/variant filter)
  - `create_session` / `fetch_search_page` / `parse_search_asins` / `collect_search_asins`
  - `fetch_detail_page` / `detect_seller_amazon_jp` (= merchantId AN1VRQENFRJN5 100% 精度)
  - `extract_brand_text` / `extract_title` / `extract_monthly_sales_text`
  - `extract_variant_asins_http` (= regex `</ul>` end pattern で section 切り出し、 入れ子 div 問題回避)
  - `is_gshock_brand_text` / `evaluate_detail_for_keep` (= 1 ASIN total 評価)
  - `SELLER_AMAZON_PRIMARY_MARKER = '"merchantId":"AN1VRQENFRJN5"'` (= Amazon.co.jp 公式 ID)
- `scrapers/amazon_search.py:_collect_asin_urls_from_search_page` 拡張
  - `brand_prefilter=True` (= G-SHOCK title 含む card のみ採用)
  - `card.is_displayed()` チェック追加 (= 拡張機能で hide された card 除外用、 ただし selenium で効かず判明)
- `scrapers/amazon_item_detail.py` 拡張
  - `_extract_seller` 強化 (= merchant block 内 厳格判定 + fallback)
  - `_extract_rating` 修正 (= "5つ星のうち X.X" pattern 優先で 5.0 誤抽出 fix)
  - `_extract_monthly_sales` 追加 (= V 列用、 「過去 1 ヶ月で N 点以上購入」 grep)
  - `extract_variant_asins` / `extract_variant_count` (= inline-twister 新 UI 対応)
  - `fetch_detail_full` に variant + monthly_sales 統合
- `sheet_writer_amazon.py`
  - `COL_MONTHLY_SALES = 22` (= V 列、 月販売数) 追加
  - `_build_row` で V 列書込 logic 追加
  - `append_amazon_search_items` を `ws.update(range_name)` pattern で fail-safe (= 既存)
- `run_harvest_amazon_search.py` 大幅拡張
  - `is_gshock_item` (= brand + title AND filter、 Baby-G / Edifice 除外)
  - `_collect_urls_for_paths` / `_fetch_details` (= queue ベース + variant 展開 + pre_visited)
  - `_load_existing_asins_from_tab` / `_http_prefilter_keep_asins`
  - `_http_variant_supplement` (= seed ASIN → variant 子 ASIN 補完 + Amazon US 除外)
  - `setup_extension_mode` / `launch_attach_chrome_mode` / `attach_to_existing_chrome`
  - 新 options: `--use-http-prefilter` / `--supplement-variants-from-tab` /
    `--skip-existing-tab` / `--launch-attach-chrome` / `--attach-port` / `--setup-extension`
- 全 pytest **674 件 pass** (= regression なし)

### 検証

- ✅ session 1 (= 11:34-13:08): selenium 直、 200 scanned → 49→75 件 keep (= bug fix 後再 append)、 captcha 0
- ✅ session 2' (= 14:50): brand pre-filter + 拡張機能、 200 scanned → 17 件 keep (= Amazon US 1 件混入後 16 件)、 captcha 0
- ✅ session 4 (= 18:37-19:11): HTTP pre-filter + variant、 28 scanned → 27 件 keep (= 歩留り 96%)、 captcha 0
- ✅ session 5 (= 19:54-22:07): variant supplement、 287 scanned → 257 件 keep、 captcha 0
- ✅ Gemini 助言検証: merchantId AN1VRQENFRJN5 = 既存 keep 3 + reject 5 で **100% 精度** 実証
- ✅ HTTP variant regex 修正: B0D9Y4QZQT で 6 件取得確認 (= 親 + 5 色 variant)
- ✅ 中間スプシ実機: 376 行、 AI 列 96.8%、 V 列 9 件 (= Amazon 売れ筋表示の仕様通り)
- ✅ catalog merge pre-flight: 119 件 → 既収録 97% (= 新規 catalog 追加 3 件)
- ✅ Amazon US 並行輸入 B000FPVUJA: merchantId 検証で `A1EJGP084HULR` (= Amazon US) と判明 → reject
- ✅ 完成報告投入: `harvest/requests/2026-06-01_amazon_gshock_full_scrape_processed.md`

### 次のアクション

- レディース 着手 (= user 判断「skip」 で保留)
- Catalog Claude による catalog merge (= dump 4 file 受領済、 Catalog スケジュール)
- 他カテゴリ展開 (= フィギュア / ねんどろ / 一番くじ) 時の `is_gshock_item` プラガブル化 refactor (= 30 分)
- selenium 環境での Amazon URL filter / 拡張機能 有効化 (= Playwright / CDP 直接利用 / 別 task)

---

## 2026-06-11 (= 終夜) — Amazon US (= 並行輸入) cleanup tooling + 39 件 flag

### 決定

- **中間スプシ既存 376 件 を全件 merchantId 検証 → Amazon US 商品 39 件 (= 10.4%) を Q 列 FLG=AMAZON_US で識別** (= user 後で削除 / 別タブ移動可能化)
  - 根拠: session 1 / 2' (= selenium 直 + brand pre-filter) で selenium が seller="Amazon.co.jp" と誤判定し Amazon US 並行輸入が keep されていた
  - HTTP merchantId 検証 (= AN1VRQENFRJN5 一致) を真実値として retroactive cleanup

### 変更

- `tools/flag_amazon_us_in_sheet.py` 新規作成 (= 中間スプシ全行を HTTP detail で merchantId 検証 + Q 列に FLG 書込)
  - rate limit 2-3s (= Amazon ブロック対策)
  - 既存 Q 列値あり 行は skip (= 上書き禁止、 安全)
  - 完走 376 件、 captcha 0

### 検証

- ✅ 全 376 件 fetch 完走 (= captcha 0)
- ✅ Amazon.co.jp 確定: **337 件** (= 89.6%)
- ✅ Amazon US 検出 + Q 列書込: **39 件** (= 10.4%)
- ✅ fetch_failed: 0 件
- ✅ session 4 / 5 (= HTTP filter で keep した分) には Amazon US 混入 **0 件** (= merchantId 100% 精度実証通り)
- ✅ 結果 dump: `debug/flag_amazon_us_result.json` (= 39 ASIN list + 行番号)

### 次のアクション

- user 手動で Q 列 = "AMAZON_US" 39 行の削除 / 別タブ移動 / 出品候補から除外
- 国内 Amazon 直販 実質 **337 件** が catalog 投入 / listing 候補化対象

---

## 2026-06-11 (= 前半) — Amazon G-shock 全件 scrape 新規実装 (= 4 番目 catalog source)

### 決定

- **Amazon G-shock 全件 scrape を 4 番目 catalog source として実装** (= 元 6/1 依頼書 GO 発火)
  - 根拠: ユーザー Takaaki さんの「Amazon retry GO」 (= 6/1 Amazon bot mark expire 後)
  - 規模: メンズ 推定 200-300 弱 (= 6/11 実機 sniff、 captcha なし)
- **「一石二鳥」 案採用** (= JSON dump + 中間スプシ append、 catalog 投入 + listing 候補化 両方)
  - 根拠: Catalog 回答 (= `_amazon_gshock_two_birds_confirmation_response.md`) で C 案 賛成
- **brand filter 追加** (= CITIZEN 完全除外、 5/11 5 件 sample で混入課題判明 → fix)
- **variant 全展開 fetch 採用** (= 各色違いの子 ASIN を別 detail fetch、 ユーザー指摘「全部取らないとね」)
- **AI 列 (= 型番) 生 verbatim で中間スプシ 列追加** (= HQ 規約 `_amazon_gshock_raw_model_in_sheet.md`)
  - canonical 化・正規化は Harvest でやらない (= catalog 側 lookup_gshock で resolve)
- **拡張機能 (Amazon 3rd Party Seller Filter) 組込** (= 検索 page で第三者除外、 user 提案)
  - chrome_profile_amazon に install、 setup-extension mode で setup 一度のみ
- **append bug fix** (= 5/26 mercari_seller 同型事故、 ws.append_rows で AC 列から書込発生 → ws.update(range_name) pattern に修正)
- **skip-existing-tab option** 追加 (= session 跨ぎで既存 ASIN 重複 fetch 防止)
- **brand pre-filter** 追加 (= 検索 page card で G-shock title 含むもののみ URL 収集)

### 変更

- `scrapers/amazon_search.py` 新規作成 (= 検索 page URL 収集 + pagination + brand pre-filter)
  - `parse_search_url` / `build_search_url_with_page` / `parse_asin_from_url`
  - `_collect_asin_urls_from_search_page(brand_prefilter=True)` (= card 単位 + G-SHOCK title filter + fallback)
  - `collect_search_listing_urls` (= 最大 25 page 走査、 hard cap 1000)
  - `SEARCH_RESULT_CARD_SELECTORS` / `GSHOCK_TITLE_PREFILTER_RE`
- `scrapers/amazon_item_detail.py:514-617` `fetch_detail_full` 新規追加 (= 14 field 拡張)
  - `_extract_seller` (= block + body marker、 6/11 fix で `merchantInfo` block 内 「販売 + Amazon」 strong signal 採用)
  - `_extract_brand` / `_extract_model_number` / `_extract_release_date_amazon` (= spec_pairs から key:value)
  - `_extract_review_count` / `_extract_rating` (= "5つ星のうち X.X" pattern 優先)
  - `_extract_product_id_estimated_from_title` (= G-shock model regex)
  - `extract_variant_asins` / `extract_variant_count` (= inline-twister + variation_color_name、 子 ASIN list 抽出)
- `sheet_writer_amazon.py` 拡張
  - `DEFAULT_COLUMN_COUNT`: 20 → **35** (= AI 列 KEY まで含む format)
  - `COL_KEY = 35` (= AI 列、 model_number / product_id_estimated 優先で生 verbatim)
  - `_build_row` に AI 列書込 logic 追加
  - `build_amazon_tab_name` / `_get_or_create_amazon_search_tab` / `append_amazon_search_items` (= 中間スプシ append)
  - **append bug fix**: `ws.append_rows()` → `ws.update(range_name=A{next}:T{end})` 明示範囲指定
- `run_harvest_amazon_search.py` 新規作成 (= entrypoint)
  - `PRESETS = {gshock-all, gshock-mens, gshock-ladies}`
  - `is_gshock_item` (= brand + title AND filter、 Baby-G / Edifice / Pro Trek 除外)
  - `_collect_urls_for_paths` / `_fetch_details(queue ベース + variant 展開 + pre_visited_asins)`
  - `harvest_amazon_search` / `_load_existing_asins_from_tab`
  - `setup_extension_mode` (= chrome 起動 + 拡張機能 install URL navigate + 30 分 sleep)
  - `--skip-existing-tab` / `--setup-extension` option
- `tests/test_amazon_search.py` 新規 24 件 (= URL parse / brand filter / dedup / regex / tab name / is_gshock_item)
- `tests/test_sheet_writer_amazon_dedupe.py` `len(r) == 20` → `35`
- `tests/test_mercari_size_extract.py` 同様 `len(row) == 20` → `35`
- `.gitignore` debug/dry_run / sniff / verify / probe / *.log 追加除外

### 検証

- ✅ `pytest` 全体 = **674 件 pass** (= regression なし)
- ✅ 6/11 sniff dry-run (= verify_extension_filter): 拡張機能 install 後 1 page URL 46 件 (= 前 60 件、 23% 削減)
- ✅ variant dry-run (= dry_run_amazon_variant): B0D9Y4QZQT 起点 6 色 variant 全取得確認
  - GD-010-4JF (オレンジ) / -1A1JF (オールブラック) / -3JF (カーキ) / -1JF (ブラック) / -010BEG-1JF / -010GB-1A9JF
- ✅ session 1 本実行 (= 13:34-14:50、 約 1 時間 16 分):
  - メンズ URL 398 件、 scanned 200 件、 **keep 49 件 (= bug fix 前) → 75 件 (= bug fix 後再 append)**
  - captcha 0 件
  - 中間スプシ amazon_gshock タブ append 75 件、 **AI 列 (= 型番) 値あり率 97.3% (73/75)**
- ✅ append bug 修正検証: row 2 col 1 = URL / col 3 = title / col 5 = "New" / col 6 = "10780" 正常書込確認
- ✅ brand filter 検証: 75 件中 「Baby-G / Edifice / Pro Trek / CITIZEN 等」 hit **0 件**、 title G-SHOCK 表記 75/75
- ✅ Catalog 依頼書 2 件 + 回答受領済 (= 6/11 13:00-13:39):
  - `_amazon_gshock_two_birds_confirmation.md` + `_response.md`
  - `_amazon_gshock_intermediate_sheet_format_check.md` + `_response.md`
- ✅ HQ 依頼書受領 (= 6/11):
  - `_amazon_gshock_raw_model_in_sheet.md` (= 型番は生 verbatim、 AI 列に格納)
  - `_gshock_ingestion_suffix_normalize.md` (= 別 task、 casio_official.py 投入時 alias 整合)
- ⏸ session 2' 進行中 (= 拡張機能 + brand pre-filter 込み、 max_per_session 200、 既存 75 ASIN skip)

### 次のアクション

- session 2' 完走 → 拡張機能 + brand pre-filter 効果実測 (= 歩留り 75-90% 期待)
- 完了報告 投入 (`harvest/requests/2026-06-01_amazon_gshock_full_scrape_processed.md`)
- 別 task: `_gshock_ingestion_suffix_normalize.md` (= casio_official.py 投入時 alias 整合、 緊急度低)
- フィギュア等他カテゴリ展開時の brand filter プラガブル化 (= refactor 30 分相当)

---

## 2026-06-03 — メルカリセラー 接続切断対策 + 差分 fetch mode 追加 / Casio 391 件 中断

### 決定

- メルカリセラー rate limit を **2-4s → 5-10s に緩和** (= IP 評判低下下での接続切断対策)
  - 根拠: 6/3 朝、 seller 803732659 で 15-25 件目に Read timed out / ConnectionResetError 連続発生
  - 直前 Casio 大量 fetch (= 累計 1200 request) で IP 評判低下、 mercari 側 bot 検出 threshold 同期厳格化と推定
- **「✓ click 完了!」 button mode 追加** (= manual click 早期完了 fix)
  - 根拠: stable_sec=15s 自動判定が user click 前に発火 → 10 件で完了とみなされる症状確認
  - user 明示 signal で stable_sec より優先 即完了
- **chrome profile fresh reset + フリマアシスト 再 install** (= profile 累積 odd state 疑い)
  - 旧 profile rename 退避 (= legacy_20260603)、 setup_anonymous mode で再 install
- **「差分のみ詳細取得」 mode 追加** (= 再実行高速化、 default ON)
  - 根拠: 同 seller 再実行時、 既存タブ row の詳細取得が 50 分 無駄 → 差分のみで 数分化
  - 既存挙動 (= checkbox OFF) は維持 = backwards compatible
- Casio 公式 391 件 fetch は **204/391 取得時点で Akamai 認定** → 数時間待ち + 全技 reset で後日 retry 方針
  - profile + IP + instance fingerprint 全て track 確認、 attach 方式 (= port 9222) も 1-2 件で再 block

### 変更

- `scrapers/mercari_seller.py:92-94`
  ```python
  DEFAULT_DETAIL_RATE_LIMIT_MIN_SEC = 5.0  # 旧 2.0
  DEFAULT_DETAIL_RATE_LIMIT_MAX_SEC = 10.0  # 旧 4.0
  ```
  commit `d74f5a1`
- `scrapers/mercari_seller.py:334-378` `_wait_for_manual_load`
  - `done_event` (= threading.Event) 引数追加、 set で即完了
  - 既存 stable_sec 判定は fallback として維持
- `scrapers/mercari_seller.py:394-406` `collect_seller_listing_urls`
  - `manual_done_event` 引数追加 → `_wait_for_manual_load` に pass-through
- `scrapers/mercari_seller.py:487-503` `collect_seller_with_details`
  - `manual_done_event` 引数追加 → `collect_seller_listing_urls` に pass-through
  - `known_item_ids: Optional[set] = None` 引数追加 → URL 収集後 詳細取得 phase 前に filter
  - 返却 dict に `skipped_known` 追加 (= 効果計測用)
  commit `babf5ba` / `a19754c`
- `control_panel.py:279-300`
  - 「差分のみ詳細取得」 checkbox 追加 (= default ON、 `self.mercari_seller_skip_known_var`)
  - 「✓ click 完了!」 緑 button 追加 (= `self.mercari_seller_manual_done_btn`)
  - `self.mercari_seller_manual_done_event = threading.Event()` 保持
- `control_panel.py:993-1057` `_run_mercari_seller_thread`
  - manual_mode 実行時 button enable + event reset
  - skip_known ON 時 既存タブから `read_existing_dedupe_keys_in_tab` で dedup key set 取得
  - mercari_seller 呼出に `known_item_ids` + `manual_done_event` を pass
  - 終了処理で button disable + text reset
- `control_panel.py:1180-1194` `_on_mercari_seller_manual_done`
  - button 押下 callback、 event.set() + button text 更新
- 退避済: `C:\Users\imax2\local_data\iMakHarvest\chrome_profile_mercari_seller_anon_legacy_20260603` (= rename)
- 退避済 (= Casio 別 task): `chrome_profile_casio_anon_blocked_20260601` / `chrome_profile_casio_attach_blocked_20260601`

### 検証

- ✅ `pytest tests/test_mercari_seller.py` = 51 件 pass (= 各 commit 前 pre-commit hook)
- ✅ `pytest` 全体 = 115 件 pass (= 各 commit)
- ✅ 6/3 17:19-18:11 実機完走: seller 803732659
  - URL 収集 222 件 (= 「click 完了」 button で 11s で signal 送信、 stable_sec 15s 待ち不要)
  - 詳細取得 222/222 (= rate 5-10s、 接続切断 0 件)
  - group 化 221 rows (= aux 1 件)
  - Vision calls=213 hits=5 disagree=0
  - スプシ書込 appended=211 + skipped_existing=10
  - 所要時間 約 50 分
  - bot 検出 / 429 / timeout / ConnectionResetError = **すべて 0**
- ✅ git push: feature/harvest-phase1 = origin と同期 (= commit d74f5a1 / babf5ba / a19754c 全 push 済)
- ✅ フリマアシスト install verify (= PowerShell): `chrome_profile_mercari_seller_anon\Default\Extensions\jcbljdgnpcckiamdgmnfhijgkkaogmgg\3.68.1_0`
- ✅ 報告書投入:
  - `requests/2026-06-03_mercari_seller_click_done_button_release.md` (= 完成報告)
  - `requests/2026-06-01_casio_official_391_detail_fetch_interim.md` (= Casio 中断報告)
- ✅ memory 更新: `mercari_seller_phase3_anonymous_furima.md` (= click 完了 button / rate 5-10s / 6/3 実機実績 追記)
- ⏸ 差分 fetch mode の実機検証は 次回 同 seller 再実行時 (= 効果値は実機で確定)

### 次のアクション

- 差分 fetch mode 実機検証 (= user が 同 seller 再実行で skipped_known 件数報告)
- Casio 391 件 retry (= 数時間〜半日 待機 + user 指示で発火、 fresh profile で再 try)
- 共有 dir `2026-06-01_amazon_gshock_full_scrape.md` (= 30 分前 投入の新依頼) 未着手 = 次セッションで対応
