# iMakInventory daily_report

## 2026-04-30 — Phase 4 Live smoke Step 1 (最小スコープ)

### 決定

- Phase 4 Live smoke は段階的に進める方針確定 (Takaaki さん指示)
- Step 1 = test listing 1 件で **CSV 生成 + eBay login** のみ。**アップロード未実行**
- 推奨候補は TEST_HIGH 行 82 (item 358454087573 UNIQLO ヒロアカ 1年A組 UT XLサイズ)
  - 選定理由: 出品 $22.58 (最安)、Mercari DELETED (仕入不可確定)
  - Takaaki さん「どれでもいい」で承認

### 変更

- **CSV 生成**: c:/dev/iMak/iMakInventory/csv_output/revise_smoke_step1_20260430_071008.csv
  ```
  *Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8),ItemID,*Quantity
  Revise,358454087573,0
  ```
- **eBay login profile 作成**: C:\Users\imax2\local_data\iMakInventory\chrome_profile_ebay\
  - Takaaki さん手動 login 実行
  - Cookies file: 68KB 保存
  - profile total: 125.47 MB

### 検証

- ✅ CSV 形式 トラバホ delete*.csv と一致 (header / Action=Revise / Quantity=0 / 列順序)
- ✅ encoding UTF-8 BOM なし (グローバル CLAUDE.md 仕様遵守)
  - 注: トラバホは BOM 付きで実績あり、eBay は両対応の見込み
- ✅ eBay login cookie 保存成功 (Default/Network/Cookies = 68KB)
- ✅ **headless driver で login 状態認識成功**
  - is_logged_in() = True
  - current_url = https://www.ebay.com/mye/myebay/summary (login 必須ページ到達)
- ✅ Amazon と異なり eBay は headless detection 緩い
- ❌ アップロード未実行 (Step 2 待ち、Takaaki さん次の指示まで実行禁止)

### 次のアクション (Takaaki さん指示待ち)

Step 2 アップロード実行 GO / NOT-YET の判断:

```bash
# Step 2 で実行する想定コマンド (現在は実行しない)
python -m ebay_actions.sell_feed_uploader upload \
  csv_output/revise_smoke_step1_20260430_071008.csv \
  --dry-run    # まずは dry-run でフォーム到達確認
```

その後 `--dry-run` 外して実 upload で qty=0 反映確認。

---

## 2026-04-30 (続き) — Phase 4 Live smoke Step 2 (2段階アプローチ)

### 決定

- Step 2a (現 URL での dry-run) と Step 2b (トラバホ同等補強実装) を別工程で進める
- Step 2c (本番 upload) は別指示で待つ (Step 2 内では実行しない)

### Step 2a 結果 (k2b-bulk URL)

旧 URL `k2b-bulk.ebay.com/...` を `driver.get()` した結果、eBay 側が自動 redirect:
- 到達 page: `https://www.ebay.com/sh/reports/uploads` (= トラバホ解析の新 URL)
- ログイン OK (cookie で persist)
- file input 要素発見、ファイル選択完了
- success: true (dry-run、Submit せず)

→ **k2b-bulk → sh/reports/uploads は eBay 側で自動 redirect される** ことが判明。
   明示的な URL 切替も依然として推奨 (再 redirect 削減)。

### Step 2b 補強実装

トラバホ `__UploadCSVwithSolded` / `__UploadCSVwithSoldedWithRetry` を踏襲した補強:

| # | 項目 | 実装 |
|---|---|---|
| 1 | URL 切替 | `EBAY_FILEEXCHANGE_UPLOAD_URL = "https://www.ebay.com/sh/reports/uploads"` |
| 2 | 3回リトライ層 (upload 全体) | `for attempt in range(1, UPLOAD_RETRY_MAX+1=3)` + 3s sleep |
| 3 | login 3回リトライ層 | `for li in range(1, LOGIN_RETRY_MAX+1=3)` + driver.refresh |
| 4 | file input 可視化 | `driver.execute_script("...style.display='block'...")` |
| 5 | ポップアップ監視 (2分) | `#shui-upload-file__pop-up` を 2 秒おきポーリング、"Download results"/"ダウンロード" で成功判定 |
| 6 | 履歴ページ refresh (3回) | popup 不確定時 results URL に遷移、5s sleep、ファイル名 + "-" 含むか確認、session 切れ検知で再 refresh |
| 7 | NoSuchElement/StaleElement | popup 監視 / 履歴ループ内で `continue` で吸収 |

### 変更

- `ebay_actions/sell_feed_uploader.py`:
  - URL 定数を `https://www.ebay.com/sh/reports/uploads` に変更
  - 新規定数: `UPLOAD_RETRY_MAX=3`, `LOGIN_RETRY_MAX=3`, `POPUP_MONITOR_TIMEOUT_SEC=120`, `POPUP_POLL_INTERVAL=2`, `HISTORY_REFRESH_MAX=3`, `HISTORY_REFRESH_SLEEP_SEC=5`
  - `upload_csv_via_form`: 旧 alert ベース監視を `#shui-upload-file__pop-up` ポーリング + 履歴 refresh に置換、file input 強制可視化 JS 追加
  - `upload_one_csv`: 3 回リトライ層 + login 3 回リトライ層追加

### 検証

- ✅ pre-commit 既存 115 tests pass
- ✅ Step 2b 修正後 dry-run 再実行成功:
  ```
  upload attempt 1/3 (3回リトライ層動作確認)
  ✅ ログイン状態 OK
  page_url: https://www.ebay.com/sh/reports/uploads
  success: true (ファイル選択まで OK、Submit せず)
  ```
- ❌ 本番 upload 未実行 (Takaaki さん次の指示まで実行禁止)

### Step 2 完了基準

- ✅ Step 2a: 現 URL での dry-run 結果報告
- ✅ Step 2b: トラバホ補強 1-7 実装 + pre-commit pass

### 次のアクション (Takaaki さん指示待ち)

Step 2c 本番 upload 実行 GO / NOT-YET 判断:

```bash
# Step 2c で実行する想定 (現在は実行しない)
python -m ebay_actions.sell_feed_uploader upload \
  csv_output/revise_smoke_step1_20260430_071008.csv
# ↑ --dry-run なし = 実 Submit + popup 監視 + 履歴 refresh で結果確認
```

実 upload 後の確認項目:
- eBay 側 listing 358454087573 (UNIQLO ヒロアカ) の qty が 0 になる
- decision_log/upload_*.jsonl に成否記録
- 不具合あれば履歴ページから人手で復旧

---

## 2026-04-30 (続き) — Phase 4 Live smoke Step 2c (本番 upload 実行)

### 決定

Takaaki さん「Step 2c GO」を受けて本番 upload 実行 (item 358454087573 の qty=0 化)。

### 実行結果 (success: true)

```
job: by7cwpvmc
csv: csv_output/revise_smoke_step1_20260430_071008.csv (Revise,358454087573,0)

upload attempt 1/3: 失敗 — "popup + history both inconclusive"
                         (popup 出る前にタイムアウト、3s sleep)
upload attempt 2/3: ✅ 成功
  popup_text: "アップロード完了\nrevise_smoke_step1_20260430_071008.csv\n結果をダウンロード"
  result_text: "popup: Download results link found"
  page_url: https://www.ebay.com/sh/reports/uploads
  success: true
```

### 検証

- ✅ **3 回リトライ層が機能した実例**: attempt 1 失敗 → 3s sleep → attempt 2 成功
- ✅ popup 監視が "ダウンロード" (Japanese) で hit (英語 "download results" にも対応)
- ✅ decision_log: `decision_log/upload_20260430_073541.jsonl` に success: true 記録
- ⏳ eBay 側反映確認 (qty=0): Takaaki さん管理画面で目視確認お願い
  (公開 itemID URL は 403 Bot block のため scraper では確認不可)

### NG 確認

- ❌ Step 3 (qty=1 復活) 未実行 (Takaaki さん次の指示まで実行禁止)
- ❌ 自動的に Step 3 進まない

### 完了基準

- ✅ decision_log success: true
- ⏳ eBay 側 listing qty=0 反映 = Takaaki さん管理画面確認

### Takaaki さん次のアクション

1. eBay seller hub (`https://www.ebay.com/sh/lst/active`) で listing 358454087573 の qty 確認
2. qty=0 反映済 → Step 2c 完了確定
3. 復活希望なら Step 3 (qty=1 化) を別 CSV 生成 + 同じ仕組みで upload

---

## 2026-05-01 — Phase 9c 並走突合 (trabajo vs inventory)

### 決定

- **DELETED → ○ → auto revise の現行ロジックを維持** (Takaaki さん判断)
- 「在庫あり → 在庫なし誤判定 (過剰)」は許容。理由: 機会損失のみで Defect Rate 影響なし
- 「在庫なし → 在庫あり誤判定 (漏れ)」は致命 (キャンセル直結 = Defect Rate 直撃)、ゼロ維持優先

### 変更

- `tools/compare_sheets.py`: 売切判定文字を `{"○", "〇"}` 両対応化
  - `SOLD_MARKS = {"○", "〇"}` 定数追加
  - `_is_sold(v)` ヘルパー追加
  - `diff_sheets` 内の `== "○"` → `_is_sold()` に置換
  - **Why:** 突合初回 (`sheet_diff_20260501_115901.md`) で「全件 0/120」の偽情報が出た真因 = trabajo 側 `〇` (U+3007 IDEOGRAPHIC NUMBER ZERO) と inventory 側 `○` (U+25CB WHITE CIRCLE) の文字コード差。判定 `== "○"` が片方のみ拾っていた。`monitor_listings.py:164` は既に両対応済 (`in ("○", "〇")`)、突合ツールだけ取りこぼしていた

### 検証

- 突合対象: trabajo `19kj8N...` (統合Hight_商品管理シート20260420) vs inventory `1oDjQC8WN_3...` (TEST_統合Hight_商品管理シート)
- 共通 URL: 421 件
- 結果 (修正後 `sheet_diff_20260501_120229.md`):
  - 一致 ○○: **115**
  - 一致 --: 299
  - inventory 漏れ (致命): **0**
  - inventory 過剰: 6 → ユーザー目視確認後 **真の過剰 1 件のみ** (行 413 ポーター ブリーフケース)、残り 5 件は inventory 先回り正解 (trabajo 取りこぼし)
  - trabajo 誤検知 (inventory 正解): 1 (行 66 鬼滅 UT)
- inventory 正答率: **419/421 ≈ 99.5%**、漏れ 0、真の誤検知 1 (0.24%)
- 真の誤検知 1 件 (行 413) の原因: scraper が `raw_status=DELETED` を売切扱い → 出品者一時取下げ等で実際は他で在庫ありの可能性。Defect Rate には無影響のため許容
- pytest 146 passed / 1 failed (`test_live_known_sold_urls[row118-m14968932238]`、live Mercari アクセスの environmental issue で本修正と無関係)

### 次のアクション

- なし (現行ロジック維持)。次回 cycle 後に再突合して傾向継続確認


## 2026-06-03 — Trading API 統一 + amazon scraper 構造修正

5 commit 集約 (d23ad99 / 7b20adc / 2f5a268 / 7663102 / 4351d8e)。 朝の dry-run で
LOW amazon 152 件 偽 OOS が判明 → 順次潰し込み + HQ § 統一指示で監視くん全体を
Selenium FileExchange UI から Trading API direct に統一。

### 決定

- **(d23ad99) amazon scraper fail-closed 致命バグ 2 重 safety net**:
  scrape 失敗 / no_signal → False=取下げ に倒れる構造 (= LOW 152 件 偽 OOS の真因) を
  「raw に in_stock 無し / None → 強制 skip」 + 「Amazon driver 起動失敗 → cycle 即 abort」
  の 2 重 safety net で 構造的再発防止 (Takaaki さん § dont_declare_complete_after_one_cycle)
- **(7b20adc) HIGH/LOW 監視くん の取下げ path = Trading API 統一**:
  sell_feed_uploader (Selenium FileExchange UI) は chromedriver DevTools 2GB
  JSONDecodeError 等で 13:30 cycle 6 件 upload 失敗 = 構造的脆弱性。
  ReviseInventoryStatus direct call に切替、 sell_feed_uploader は緊急時 fallback 残置
- **(2f5a268) 公式監視くん (inventory_monitor) も同じく Trading API 化**:
  HQ § Trading API 統一を scope 拡張。 variation listing 対応のため
  `revise_inventory_status_variation` (= 当初 ReviseInventoryStatus 経路で実装) +
  CSV 自動判定 (3 col single / 6 col variation) を追加
- **(7663102) variation revise は ReviseFixedPriceItem の `<Variations>` 構造**:
  ReviseInventoryStatus は SKU 文字列ベースで VariationSpecifics 不可
  (= err 21916736 "Cannot revise a Multi-SKU item when ItemID alone is supplied")。
  ReviseFixedPriceItem の `<Item><Variations><Variation>` 経路 に修正
- **(4351d8e) 巡回レポート 集計 + DNS 自動 retry**:
  Trading API stdout が旧 sell_feed_uploader 文言と integrated せず
  「variation Revise: 0 件 なし/失敗」 誤表示 (= 実際は eBay 上 反映済)。
  result_text に Success / Transient 追加 + CSV 行数 + ok/ng 件数 明示出力 +
  run_daily 集計 logic 拡張 + DNS/Timeout 系は 同 cycle 内 1 回 自動 retry
- **(運用) cron 全 3 task Enable + LOW スプシ自動化 復活**:
  iMakInventory_Cycle / Cycle_BothDaily0930 / Monitor_Daily を Enable。
  memory `low_sheet_manual_only.md` は事実誤認のため削除
- **(運用) スプシ D=○ 一括同期 291 件 (片方向)**:
  D=空欄 + eBay qty=0/ended の不整合を D=○ 化 (= HIGH 79 + LOW 212)。
  逆方向 audit (D=○ + eBay active qty>0) は DNS fail で pending
- **(運用) ユーザー目視 force_revise 18 件**:
  G-SHOCK 第三者 FBA 11 件 + HIGH mercari/snkrdunk 7 件 = 計 18 件 qty=0 化 (HQ upload)
- **(運用) Profile 復旧 (Amazon + eBay)**:
  Amazon 7.7GB / eBay 2.34GB 巨大化で driver 起動不能。 rename 退避 + 新 profile +
  手動 re-login で復旧。 旧 profile は `*.broken_20260603` に保持 (rollback 用)

### 変更

- `scrapers/amazon_scraper.py:62-89,100-138` (= 販売元 identity gate + fail-closed)
- `monitor_listings.py:141-160,378-410` (= None ハンドリング + driver 起動 retry/abort)
- `ebay_actions/trading_api_client.py` 新規 (= self-contained、 token + revise + variation + GetSellerList)
- `ebay_actions/trading_api_uploader.py` 新規 (= CSV 自動判定 + DNS retry + result_text 拡張)
- `run_cycle.py:51,303-321` (= _phase_upload を Trading API に切替、 sell_feed_uploader は fallback 残置)
- `../iMakeBayAPI/inventory_monitor/auto_qty_zero.py:187,304-309` (= upload_one_csv → trading_api_uploader、 件数 log 追加)
- `../iMakeBayAPI/inventory_monitor/audit_and_heal.py:158-162` (= upload_csv wrapper を Trading API 化)
- `../iMakeBayAPI/inventory_monitor/run_daily.py:73-118,160-185` (= _parse_qty_output + _detail() helper)
- `tests/test_amazon_stock_detection.py:117-148,149-210` (= 販売元 gate 5 検体 + fail-closed 3 件)
- `tests/test_trading_api_client.py` 新規 (= 11 件: Ack 解析 / IAF expired / CSV parse / DNS retry / result_text format)
- スプシ HIGH 79 + LOW 212 行 D=○ batch_update (= 永続)
- cron: iMakInventory_Cycle / Cycle_BothDaily0930 / Monitor_Daily Enable

### 検証

- amazon fail-closed bug fix:
  - HIGH/LOW dry-run pre-fix: LOW newly_sold 152 件 (= 主力 G-SHOCK 多数の偽 OOS)
  - post-fix LOW 再 scan: **newly_sold 152→7 (= -95%)** / 判定不能 (skip) 4/603 = 0.7% (= mass-skip 否)
  - 在庫あり 4 ASIN (B0BQHK77MZ/B0CQP1J8MD/B07VHSZ17W/B0CLR9NNJL) GetItem で in_stock=True ¥12K-32K 確認
- token refresh:
  - mtime 6/2 17:01:51 (HQ findings の 21h 停止) → 6/3 14:56:20 (= IAF expired 自動 retry で 更新)
- HIGH/LOW Trading API 化 E2E:
  - 13:30 cycle 失敗 6 件 CSV を ReviseInventoryStatus で再実行 → 5/6 ack=Warning redundant + 1/6 safe failure 231 = 全 OK
  - GetItem で status=Active available_qty=0 確認
- 公式監視くん variation E2E:
  - 16:42 cycle 全 31 件 失敗 (err 21916736) → 17:34 retry script で 28 件 即 OK + DNS fail 3 件 個別 retry で 全 OK = **31/31 ack=Success**
  - eBay 実機 GetItem 6 検体 (取下げ 4 + 補充 2): variation 単位 qty 全件 期待通り (`Sizes` 単軸 / `Sizes × Color` 多軸 両方)
  - 17:34 単独実行 5/5 ack=Success + result_text "Success 5 + Warning 0 + Transient 0" 出力確認
- 回帰テスト: pre-commit 全 115 件 / commit 別 検体 17→20 件 / Trading API client 6→11 件 全 pass
- スプシ D=○ 同期: ws.batch_update 2 call (HIGH 79 + LOW 212) で 「✓ done」 log 確認
- 18 件 force_revise: HQ upload で Warning 5 + safe Failure 1 + Warning 7 (= 朝 G-SHOCK 11 + HIGH 7) 確認

### 次のアクション

- **明朝 8:00 公式 cycle (= 自動)**: 集計表示 「variation Revise: N 件 (成功) (ok=N / ng=M)」
  へ format 整合確認 + DNS retry 自動発火確認 (= cycle 内 1 件でも fail があれば log で見える)
- **17:30 HIGH cycle (= 自動)**: Trading API path 経由 で qty=0 化が走るか確認、
  巡回レポート format 確認
- **逆方向 audit (= D=○ + eBay active qty>0)** pending: DNS resolver fail で延期、
  `c:/tmp/reverse_audit.py` script 残置、 次回 DNS 復旧後実行
- **HQ 依頼 2 フィギュア棚卸し** pending: amazon scraper bug fix 終結後着手、
  販売元抽出 logic 再利用 (= commit 24a6699 朝の販売元 identity gate + d23ad99 の `_detect_seller`)
- **process 反省**: 7663102 (= variation API 間違い) は memory `reuse_existing_proven_solution.md` 違反 = リバイス君の sell_feed_uploader 経由 variation_upload.py を 先に確認していれば API 仕様検討の trigger になっていた。 次回 worktree 跨ぎ logic 実装時は **既存 worktree で 同種実装の有無を 必ず先に grep** する

## 2026-06-04..05 — 公式監視くん 修復 + Active Listing 取得を Trading API 化

### 決定

- **6/4 朝 cycle 補完を即実行**: 8:00 cycle が 3 step NG (restore / audit_heal / scrape_audit) で
  終わったため、 取下げ未反映 7 件 (= 仕入元切れ × eBay qty>0、 Defect Rate 直撃) を放置
  しないため uuid_sync / K 列同期 / audit_and_heal / scrape_audit を手動再実行で補完。
  Trading API 経由で 12 件 (取下げ 7 + 復活 5) を heal、 GetItem 8 variation で qty 直接確認
- **`_schedule_new_report` UI 失敗時の既存 link fallback 実装** (= 5/29 以降 7 日連続失敗の
  延命): 真因 = eBay reports/schedule の DOM 構造変更で XPath 当たらず。 fallback で
  6/3 dated 既存 link を再利用、 「永遠に DL ゼロ」 を回避
- **SKU シート全行 cycle 内 1 回 cache 化** (= Sheets API 429 防止): 6/4 08:00 cycle 末尾
  8 listing が `Read requests per minute per user` quota 超で取りこぼし発覚。 process_listing
  毎の `read_sku_rows` 連発を main loop 前 1 回読込に集約 (= API read 74 → 1)
- **ErrorCode 21916750 (FixedPrice item ended) を safe_failure 化**: 6/4 09:30 メルカリ
  cycle で ng=1 → 3 cycle 連続 (= 6/2 ConnectionError, 6/3 JSONDecodeError, 6/4 21916750) で
  generic_failure_threshold アラート発火。 sold/expired listing への qty=0 化は dropshipping
  前提では「目的達成済」、 safe codes に追加
- **Active Listing CSV 取得を Trading API GetSellerList Fine に置換** (= 根本対策):
  上記 fallback は短期延命、 根本問題 = Selenium UI scrape の脆弱性 + 「fallback で同 CSV を
  使い続け → 新規 listing が監視対象外になる」 構造。 GetSellerList Fine + IncludeVariations
  で全 active listing を取得 + 既存 CSV column 互換で出力 → 既存 sync_from_csv / audit_and_heal
  無修正で動く。 Selenium 経路は safety net 残置 (= memory `reuse_existing_proven_solution`)
- **17:30 メルカリ cycle DNS failure を手動 Revise で即解消**: 1 件 (358571988843) が
  DNS resolver 一時失敗で transient retry 1 回でも復活せず ng=1。 4h 待たず手動 revise で
  qty=0 化 (= memory `ebay_first_always` Defect Rate 防衛)
- **「正式完了」 宣言を引込め、 145 件大量復活を verify**: 6/5 08:00 cycle で 145 件
  qty=1 復活が走った時、 サンプル 1 件 verify のみで「健全」 と断言したのは
  memory `full_check_before_report` 違反。 10 listing × 28 variation を仕入元 API で再 verify
  → 100% in_stock=True で復活妥当性確定

### 変更

- `iMakeBayAPI/inventory_monitor/ebay_active_listing_dl.py:248-267`
  (= `_schedule_new_report` 失敗時の既存 link fallback、 commit f07788c)
- `iMakeBayAPI/inventory_monitor/main.py:215-235,706-714` (= SKU シート全行 cycle 内
  cache + process_listing の all_sku_rows 引数追加、 commit a891745)
- `iMakInventory/ebay_actions/trading_api_uploader.py:178` (= safe codes に "21916750"
  追加、 commit 292b297)
- `iMakInventory/tests/test_trading_api_client.py:87-95` 新規 (= 21916750 source 検査
  test、 commit 292b297)
- `iMakeBayAPI/inventory_monitor/ebay_active_listing_via_trading_api.py` **新規**
  (= GetSellerList Fine paging + Active Listing CSV 互換 8 column 出力 + DNS retry 5 回
  + IAF auto refresh、 commit 8711aa3)
- `iMakeBayAPI/inventory_monitor/main.py:608-643` (= --ebay-report auto 分岐を Trading
  API 優先 + Selenium fallback に、 commit 8711aa3)

### 検証

- **6/4 補完 cycle**: uuid_sync 70 cells 書換、 K 列同期 159 件補正 (= 5/29 以降ずっと
  古かった K)、 audit_heal Trading API で取下げ 7 + 復活 5 = 12 件全件 ack=Success
- **8/8 variation direct verify (GetItem)**: 取下げ済 7 件 (358381852914 L/XL,
  358359355028 S, 358359565422 XL, 358275199203 BL/S, 358560250231 XXS, 358278977272
  Brown/L) + 復活 5 件 (358275199203 DGN-XL, NV/OG/TQ/YL-S) = 100% qty 期待値一致
- **6/5 08:00 公式 cycle 全 step OK**: monitor (= Sheets 429 エラー 0 件、 a891745 効果)
  / uuid_sync / zero (11 件) / restore (141+4=145 件) / audit_heal (zero 9 + restore 11)
  / scrape_audit (100%、 昨日 90% アラート解消)
- **6/5 13:30 メルカリ cycle 正常**: 取下げ 2 件 ack=Success、 streak 0 維持
  (= 292b297 効果、 21916750 → safe 扱いで ng 化されない)
- **大量復活 sample verify**: random 10 listing (= 50 中 20%) × 28 variation を
  uniqlo / gu API で実 fetch → 100% in_stock=True qty=11 (= scraper 判定 健全)
- **昨日朝 heal_zero 7 件 巻き戻し非発生 verify**: 6/5 08:00 cycle 後に再度 GetItem、
  全 7 件 qty=0 維持確認 (= 復活 145 件に巻き込まれてない)
- **Trading API CSV 互換性 verify**: 19:53 全 24 page fetch (7500 rows)、 既存 6/3 dated CSV
  と diff = 共通 290 variation listings (互換 100%) / 削除 0 / **新規 3 listings
  (358639572937, 358639652237, 358640199261 = 計 21 variations) が 6/3 以降 監視対象外
  だった事実確定**
- **手動 Revise (17:30 救済)**: 358571988843 qty=0 化 ack=Warning (= 23015 Best Offer 警告
  だが qty=0 化 success)
- **pre-commit**: 4 commits 全て 115 tests pass

### 次のアクション

- **明日 8:00 公式 cycle (= 自動)**: Trading API path (= 8711aa3 効果) の log 確認、
  「[Active Listing DL] Trading API (GetSellerList Fine) 開始」 が出るはず + 監視対象に
  新規 3 listings (358639572937 等) が含まれることを確認
- **#7 監査 (= Claude implementation-auditor + Gemini 二次)**: 本セッション 4 commits
  + 実 eBay Revise ~201 件 + スプシ書込 (UUID 70 + K 列 159) の 独立検証。
  HQ 自己申告との乖離 chk
- **DNS retry 増強 (trading_api_uploader)**: 17:30 cycle failure の根本対策。 現状
  retry 1 回 → ebay_active_listing_via_trading_api._post_with_retry と同じ 5 回 + 10s sleep
  パターン展開 (= memory `reuse_existing_proven_solution`)
- **過去 restore NG 真因調査** (緊急度低): 6/2 6/3 6/4 で connectionError / JSONDecodeError /
  21916750 ng と毎回違う原因、 今は self-correct 済
- **K 列同期 「dry-run」 ログ表示** (cosmetic): execute=True で乖離 0 件のとき
  「乖離 0 件、 dry-run」 と紛らわしい文言、 後で確認
- **process 教訓**: Selenium UI scrape は eBay UI 構造変更で永続的に壊れる。 Trading API
  で代替可能なところは API 化 を優先する (= 今回 GetSellerList Fine で完全代替できた)

---

## 2026-06-06 — pending drain 後置化 (transient failure sliver loss bug 修正)

### 決定

- `drain_pending_queue` の呼出位置を **CSV 生成時 → upload 完了後** に移動
- 成功 item (= ack=Success/Warning or safe_failure) のみ drain、 失敗 item は pending 残置
- 失敗 item は次 cycle で sheet D=○ verify を経て自動 re-enqueue (= 構造的に retry)
- 17:30 cycle の 1 件 sliver loss は **手動 revise (358624006440 qty=0、 ack=Warning err=23015) で復旧済**

### 変更

- `ebay_actions/revise_csv_generator.py:538`: drain call 削除 + 説明 comment
- `ebay_actions/revise_csv_generator.py:567` return dict に `mode` / `allowed_item_ids` 追加
- `run_cycle.py:50` import に `drain_pending_queue` 追加
- `run_cycle.py:586` 付近 upload 完了後に `successful_ids = [r["item_id"] for r in u["results"] if r["success"]]`
  → `drain_pending_queue(successful_ids)` 呼出 + 失敗件数 log 出力
- `tests/test_run_cycle.py` に `test_drain_pending_only_on_success` 追加 (Regression guard)

### 検証

- ✅ 全 282 tests pass (新規 1 件含む)
- ✅ Grep 確認: `drain_pending_queue` 呼出は 2 箇所 (`revise_csv_generator.py:260` def + `run_cycle.py` の post-upload call) のみ
- ✅ revise_csv_generator return に新 field 追加、 既存 caller (`run_cycle.py`) は `mode == "pending"` で gating
- ✅ 旧 bug の再現条件 (transient failure → pending から即消滅) は新実装で発生不能
  - new test で `[iid_ok, iid_safe]` の 2 件のみ drain、 `iid_fail` は pending に残る ことを物理担保
- ✅ 手動 revise 実行: `358624006440` qty=0 ack=Warning success=True (err 23015 = informational Best Offer 警告)

### 次のアクション

- **明日 cycle 観察**: 17:30 cycle 後の `decision_log/trading_api_upload_*.jsonl` で
  ng>0 のとき pending に該当 item が残ってるか実機確認
- **DNS retry 増強 (元 TODO)**: trading_api_uploader._is_transient_failure 用 1-時 retry を
  ebay_active_listing_via_trading_api._post_with_retry と同等 (5 回 + 10s) に展開
  → 今回の drain 後置 化で sliver loss 不能化したため緊急度は下がった、 別 turn で着手
- **reverse_audit (memory `reverse_audit_pending`)**: 別系統の補完監査として残置、 D=○ +
  eBay active qty>0 検出 logic は cycle 末尾 phase 化検討

---

## 2026-06-09 — pending queue auto-prune (肥大化防止)

### 決定

- `collect_from_pending_queue` の verify で `no_longer_sold_or_id_changed` 判定された
  entry を pending file から物理削除し、 `discarded_revise.jsonl` に archive する
  構造修正 (= 「2026-06-02 amazon scraper bug 由来の 158 件等が永続蓄積」 問題)
- 削除は **sheet verify 成功** 時のみ。 sheet 読込失敗 (skip_reason 無し) / 別 sheet の
  filter_* skip は誤削除しない安全側設計

### 変更

- `ebay_actions/revise_csv_generator.py:79` `DISCARDED_REVISE_FILE` 定数追加
- `ebay_actions/revise_csv_generator.py:260` `prune_discarded_entries(skipped)` 追加
  - skip_reason="no_longer_sold_or_id_changed" のみ対象、 archive に
    `discarded_at` / `discard_reason` field 付与
- `ebay_actions/revise_csv_generator.py:485` `run()` 内、 `collect_from_pending_queue` 直後で
  prune 呼出 + 件数 log 出力
- `tests/test_run_cycle.py::test_prune_discarded_entries_only_no_longer_sold` 追加
- 既存 167 件 (LOW 166 + SHEET 1) を実機 sheet verify 経由で全件 archive 実行 →
  pending file 0 件 / discarded file 167 件

### 検証

- ✅ 全 283 tests pass (新規 1 件含む)
- ✅ 4 種の skip 状況 (no_longer_sold / filter_low / sheet_read_fail / valid) で
  no_longer_sold のみ削除されることを test で物理担保
- ✅ live sheet verify 実走で 167 件全てが `no_longer_sold_or_id_changed` と判定 →
  全件 archive 安全と確認 (sheet 上で ○ 残存ゼロ)
- ✅ 実機 prune 実行: pending 167 → 0、 discarded 0 → 167
- ✅ 主因 (158 件) は 2026-06-02 amazon scraper fail-closed bug 由来 (= memory
  `amazon_scraper_fail_closed_bug` で 解決済の偽 OOS 残骸)

### 次のアクション

- **明日 09:30 `--sheet both` cycle 観察**: 新 prune 経路の log
  「pending prune (sheet で ○ 解除済): N 件 → discarded_revise.jsonl」 が 0 件出力
  (= 新規蓄積なし) になっているか確認
- **discarded_revise.jsonl size 監視**: 蓄積 file なので backup_inventory.ps1 の
  rotation 対象に含めるか検討 (= 緊急度低、 当面 167 件で size 微小)

---

## 2026-06-10 — sliver loss 根絶 Phase 1 (HQ FINAL 確定指示 A/B/C 実装)

### 決定

- 過去 5 週間に 156 件規模の silent sliver loss が発生していた事実発覚
  (= ユーザーが 358596670518 を指摘 → reverse_audit で 11 件発見 + 全件 qty=0 化救済)
- 真因 = (i) 旧 Selenium FileExchange UI 経路の脆性 (6/3 commit 8711aa3 で Trading API 化済)
  + (ii) drain-before-upload bug (6/6 commit 5716879 で drain 後置化済)
  + (iii) **私の 6/9 commit b4c238d の prune_discarded_entries が sheet D=空 だけで** archive
  → 6/10 09:30 で sheet 書込 DNS fail 由来の偽 D=空 で 2 件 silent drop 発生
- HQ FINAL 設計指示 (= `_FINAL_design_directive`) 確定:
  - 「取り下げるべきもの」 はそのサイクル内で eBay qty=0 を確認するまで閉じる
  - 「除外」 を silent でなく「未取下げ=要対応」 として明示
  - 「正常」 は全件 qty=0 確認できた時のみ

### 変更

- `ebay_actions/revise_csv_generator.py:263` `prune_discarded_entries` を fail-CLOSED 改修
  - sheet D=空 だけでは discard しない、 **eBay GetItem qty=0 確認後にのみ** discard
  - eBay qty>0 残存 entry は pending 残置 + **再 include 候補に格上げ** (= sheet 状態誤と判定、 silent loss を逆に救済)
  - GetItem 失敗時は保守的に pending 残置
  - return 値: `int` → `{"discarded": N, "kept_qty_gt0": M, "reincluded": [..]}`
- `ebay_actions/revise_csv_generator.py:619` 付近 `run()` で reincluded 候補を CSV 対象に追加
- `ebay_actions/trading_api_uploader.py:96` `INCYCLE_RETRY_INTERVALS_SEC = [5.0, 15.0, 45.0]`
  module-level 追加
- `ebay_actions/trading_api_uploader.py:170` `_verify_qty_zero(item)` 関数追加
  (= revise 後 GetItem で qty=0 確認、 err 17 は qty=0 同等扱い)
- `ebay_actions/trading_api_uploader.py:175` 付近 in-cycle short retry loop 実装
  (revise → verify → NG なら 5s/15s/45s で再 revise + 再 verify、 最大 4 試行 = 65s 上限)
- 失敗時 entry に `verified` / `verify_qty` / `verify_msg` / `verify_attempts` field 追加
- `monitor_listings.py:304` `ACTION_REQUIRED_FILE` + `append_action_required` 追加
  (HQ 原則 B、 silent 除外禁止)
- `monitor_listings.py:533` 付近 newly_sold + item_id 空欄 → silent 除外せず action_required 化
- `run_cycle.py:50` `drain_pending_queue` import 修正
- `run_cycle.py:610` 付近 upload 完了後 verify-failed item を action_required.jsonl に記録
- `run_cycle.py:689` 付近 cycle 末尾で action_required の cycle 内集計 →
  `cycle_log["phases"]["action_required_summary"]` 格納
- `email_notifier.py:204` 付近 メール冒頭 1 行に
  `取下げ: 売切検知 N → 完了 X / 未取下げ Y` + `結果: ⚠️ 要対応 (取下げ漏れ Y件)` or
  `結果: ✅ 全件取下げ完了` (= HQ 原則 C)
- 旧 cycle_log 形式との後方互換性確保 (= action_required_summary 未投入時は status_jp fallback)
- `tests/test_run_cycle.py` 既存 test 1 件改修 (`test_prune_discarded_entries_requires_ebay_qty_zero`)
  + 新規 2 件追加 (`test_email_header_shows_untaken_count_when_action_required` /
  `test_in_cycle_verify_blocks_silent_success`)
- HQ 依頼書 2 本 `_processed` リネーム + iMakRevise feasibility 依頼書投入
  (`c:/dev/iMak_data/revise/requests/2026-06-10_price_revise_sliver_loss_feasibility.md`)

### 検証

- ✅ 全 185 tests pass (新規 2 件 + 既存改修 1 件含む、 live scraper test 除く)
- ✅ Email format 模擬 cycle_log で動作確認:
  - 要対応 2 件 → `売切検知 4 → 完了 2 / 未取下げ 2` + `⚠️ 要対応 (取下げ漏れ 2 件)` ヘッダ
  - 全件完了 → `売切検知 3 → 完了 3 / 未取下げ 0` + `✅ 全件取下げ完了` ヘッダ
- ✅ Regression test `test_in_cycle_verify_blocks_silent_success`:
  revise が Ack=Success でも GetItem qty=5 なら success=False / verified=False / verify_attempts>=3
- ✅ Regression test `test_prune_discarded_entries_requires_ebay_qty_zero`:
  qty=0 → discard / qty>0 → 再 include / API 失敗 → 保守的に保持 / filter skip → 触らない
- ✅ Reverse audit 6/10 実行で発見した 11 件全件 qty=0 化済 (= 156 件型の事後収束)
- ✅ HQ 信頼回復 5 点 のうち 1 (失敗注入回帰テスト) 完了

### 残課題 (= Phase 2 候補)

- 案 B 自動 re-enqueue (= 定期 reverse_audit を cycle phase に組込) — Phase 1 効果観察後
- Bulk Change Circuit Breaker (newly_sold 率異常検知) — commit d23ad99 既存実装の調査先行
- グローバル CLAUDE.md 原則追記 (「1 回失敗 = 永久放置 禁止」) — HQ 側で別セッション
- DLQ resurrection CLI (`cli.py resurrect-dlq <iid>`) — action_required.jsonl からの戻し経路
- 公式監視くん audit_and_heal の reconciliation 網羅性 再監査 (HQ 横断指示)
- iMakRevise feasibility 回答待ち (= 価格 revise の sliver loss 有無)

### 次のアクション

- 次 cycle (= 13:30 SHEET 単一 cycle) で新 logic 実走、 ログ + メール冒頭 1 行を実機確認
- 明日 09:30 `--sheet both` cycle で 6/10 同型 (= sheet 書込 fail 発生時) の動作確認
- iMakRevise 回答 / Phase 2 着手判断は 1-2 週間運用後

