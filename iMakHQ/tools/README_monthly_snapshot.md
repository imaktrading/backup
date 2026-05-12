# Seller Hub 月次 snapshot — タスクスケジューラ登録手順

## 目的

eBay は Ended listing データを **90日で消失** させる。月次で自動 scrape して
`C:\dev\iMak_data\seller_hub\` に永続保存することで、View/Watchers 等の時系列分析が可能になる。

## 自動取得対象

- **Ended 全件 (--all-pages)**: 21 page 全件、約 9 分
- **Active 全件 (--all-pages)**: 数 page、約 1-2 分
- 取得項目 15列: snapshot_date / status / item_id / sku / title / price_usd
  / views / watchers / quantity_available / listed_date / ended_date
  / promoted_rate / format / best_offer_enabled / search_keyword

## 手動取得が必要なもの (補完)

公式 CSV (Sold/Relist status を含むがVies は含まない) は eBay 認証で自動化困難:
1. https://www.ebay.com/sh/reports/downloads にアクセス
2. 「Unsold listings」レポート > Download
3. DL 後、`C:\dev\iMak_data\seller_hub\official_unsold_YYYYMMDD.csv` にリネーム保存

## Windows タスクスケジューラ登録手順

### 1. タスクスケジューラを開く

`Win + R` → `taskschd.msc` → Enter

### 2. 新規タスク作成

右ペイン「タスクの作成…」(基本タスクではなく) クリック

### 3. 全般タブ

- **名前**: `iMak Seller Hub Monthly Snapshot`
- **説明**: `eBay 90日消失防止のため月次で Ended/Active 全件 scrape`
- **セキュリティオプション**:
  - 「ユーザーがログオンしているときのみ実行する」を選択 (Chrome profile 共有のため)
  - 「最上位の特権で実行する」は OFF

### 4. トリガータブ

「新規…」 → 以下設定:
- 開始: 「スケジュールに従う」
- 設定: 「毎月」
- 開始時刻: **04:00** (Inventory cron と衝突回避、深夜帯)
- 月: 全月
- 日: 「1」 (毎月 1 日)
- 有効: ON

### 5. 操作タブ

「新規…」 → 以下設定:
- 操作: 「プログラムの開始」
- プログラム/スクリプト: `C:\dev\iMak\iMakHQ\tools\monthly_seller_hub_snapshot.bat`
- 開始: `C:\dev\iMak\iMakHQ\tools` (省略可)

### 6. 条件タブ

- 「コンピューターをAC電源で使用している場合のみタスクを開始する」: 任意
- 「タスクを実行するためにスリープを解除する」: **ON 推奨** (PC sleep 中でも起動)
- 「次のネットワーク接続が利用可能な場合のみタスクを開始する」: 「任意の接続」

### 7. 設定タブ

- 「タスクを要求時に実行する」: ON
- 「タスクが失敗した場合の再起動の間隔」: 30分、再試行回数 3 回
- 「タスクが次の時間より長く実行されている場合は停止する」: 30分

### 8. OK → ログオンパスワード入力

## 動作確認

1. タスクを右クリック → 「実行する」 で手動起動
2. `C:\dev\iMak\iMakHQ\logs\monthly_snapshot_YYYYMMDD.log` を確認
3. `C:\dev\iMak_data\seller_hub\snapshot_*_YYYYMMDD_*.csv` が増えてれば成功

## トラブルシューティング

### Chrome profile lock 衝突

Inventory cron (4h 周期) と Active なタイミングが重なる可能性:
- Inventory cron は通常 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
- = 04:00 は Inventory 走行時刻と被る
- 衝突回避: タスク時刻を 03:30 (Inventory 直前) or 04:15 (直後) に調整

### eBay 再ログイン要求

cookie 切れた場合は手動でログイン:
```cmd
cd C:\dev\iMak_inventory\iMakInventory
python -m ebay_actions.sell_feed_uploader --login
```

### 取得件数が想定より少ない

- SPA hydration 待機不足 → batch の `--wait 25` を `--wait 35` に増やす
- bot 検出 → eBay 警告ページに redirect、再ログイン or IP 変更
