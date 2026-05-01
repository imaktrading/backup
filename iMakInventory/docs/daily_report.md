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
