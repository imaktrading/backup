# Seller Hub 月次 snapshot 運用

## 目的

eBay は Ended listing データを **90日で消失** させる。月次で snapshot を取って
`C:\dev\iMak_data\seller_hub\` に永続保存することで、View/Watchers 等の時系列分析が可能になる。

## 運用方針: 通知 → 手動実行

自動実行ではなく **通知 → 人手で確実に実行** する設計:
- 通知だけ自動 (Windows タスクスケジューラ + Toast 通知)
- 公式 CSV DL + scrape 実行は **ユーザー手動**
- 理由: cookie 切れ・bot 検出等の失敗を即時認識できる、Profile lock 衝突回避

## 月次実行フロー (ユーザー側 5 分)

### 通知が来たら

毎月 1 日 04:00 (or 設定時刻) にデスクトップ通知が出る:
```
📊 iMak Seller Hub 月次 snapshot
1. Seller Hub > Reports > Unsold CSV を DL
2. monthly_seller_hub_snapshot.bat を実行
```

### Step 1: 公式 CSV ダウンロード (1-2 分)

1. ブラウザで https://www.ebay.com/sh/reports/downloads
2. 「Unsold listings」レポート > Download
3. DL された file (`eBay-unsold-listings-report-YYYY-MM-DD-*.csv`) を
   `C:\dev\iMak_data\seller_hub\official_unsold_YYYYMMDD.csv` にリネーム保存

### Step 2: scrape 実行 (約 10 分)

エクスプローラーで `C:\dev\iMak\iMakHQ\tools\monthly_seller_hub_snapshot.bat` を
ダブルクリック実行。

または出品くんの「📊 今、見る」ボタン → Status=Ended + Save チェック + 実行
(--all-pages フラグ追加の UI 実装は今後の課題、現状は batch 直叩きが楽)。

### 完了確認

- `C:\dev\iMak\iMakHQ\logs\monthly_snapshot_YYYYMMDD.log` を確認
- `C:\dev\iMak_data\seller_hub\snapshot_*_YYYYMMDD_*.csv` が増えてれば成功

## 通知タスクの登録 (初回 1 回のみ)

### 1. タスクスケジューラを開く

`Win + R` → `taskschd.msc` → Enter

### 2. タスクの作成 (基本タスクではなく)

- **名前**: `iMak Seller Hub Monthly Alert`
- **説明**: `月初に Seller Hub snapshot のリマインダー通知`
- **セキュリティオプション**:
  - 「ユーザーがログオンしているときのみ実行する」を選択
  - 「最上位の特権で実行する」は OFF

### 3. トリガータブ

- 開始: 「スケジュールに従う」
- 設定: 「毎月」
- 開始時刻: **04:00** (or 任意)
- 月: 全月
- 日: 「1」 (毎月 1 日)

### 4. 操作タブ

- 操作: 「プログラムの開始」
- プログラム/スクリプト: `python`
- 引数の追加: `C:\dev\iMak\iMakHQ\tools\monthly_snapshot_alert.py`
- 開始: `C:\dev\iMak\iMakHQ\tools`

### 5. 条件タブ

- 「タスクを実行するためにスリープを解除する」: ON 推奨

### 6. OK → ログオンパスワード入力

### 動作確認

タスク右クリック → 「実行する」 → デスクトップ右下に通知が出れば成功。

## 依存

通知 script (`monthly_snapshot_alert.py`) は以下のいずれかで通知を表示:
1. **win10toast** (推奨、Python製 Toast): `pip install win10toast`
2. **PowerShell NotifyIcon** (フォールバック、追加 install 不要)

## トラブルシューティング

### Chrome profile lock 衝突 (batch 実行時)

Inventory cron (4h 周期) と batch を同時実行すると profile lock 衝突。
batch 実行前に Inventory が走ってないか確認:
```cmd
tasklist | findstr chrome
```

### eBay 再ログイン要求

cookie 切れた場合:
```cmd
cd C:\dev\iMak_inventory\iMakInventory
python -m ebay_actions.sell_feed_uploader --login
```

### 取得件数が想定より少ない

- SPA hydration 待機不足 → batch の `--wait 25` を `--wait 35` に増やす
- bot 検出 → eBay 警告ページに redirect、再ログイン or IP 変更
