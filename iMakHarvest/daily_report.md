# iMakHarvest daily_report

## 2026-06-11 — Amazon G-shock 全件 scrape 新規実装 (= 4 番目 catalog source)

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
