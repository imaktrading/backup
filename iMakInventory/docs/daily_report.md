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
