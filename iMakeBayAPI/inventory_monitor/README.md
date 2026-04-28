# inventory_monitor — 仕入元在庫の自動監視 (Phase 1)

無在庫運用で「仕入元 (UNIQLO 等) で在庫切れだが eBay で出品中」のミスマッチを自動検知し、対処要 SKU を Google Sheets に反映する。

## 構成

```
iMakeBayAPI/inventory_monitor/
├── uniqlo_scraper.py      ← UNIQLO 商品 URL → JSON API 経由で在庫・価格取得
├── ebay_sku_fetcher.py    ← eBay listing → SKU 情報取得 (Phase 1 = sheet 参照)
├── sheet_updater.py       ← Google Sheets 認証 + メイン/SKU シート読書
├── main.py                ← オーケストレーション (日次バッチ)
├── logs/                  ← YYYY-MM-DD.log + _last_needs_action_count.json
└── README.md              ← このファイル
```

各モジュールは独立。既存の psa_to_csv.py / control_panel.py / iMakeBayAPI 内 listing 系ロジックを **一切修正していない**。

## Phase 1 の機能 (Level 1: 検知のみ)

- UNIQLO 商品 29 listing 全件の各サイズ × カラー × 在庫状況を自動取得
- SKU シート (`SKU詳細` タブ) に以下を更新:
  - 仕入元在庫 (◎ / ✕)
  - 仕入元価格 (¥)
  - 自動 CHK 日 (実行時刻)
  - 対処要フラグ (A 列)
- 要対処件数が前回より増加した時のみコンソール強調 (Phase 1.5 でメール通知化予定)
- eBay 自動操作 (qty=0 化等) は **行わない** — 手動運用前提

## Phase 1 の制約 (Sell API gap)

⚠️ eBay listing 単位の SKU/Qty 直接取得は **未実装** (Phase 4 着手予定)。

理由:
- 既存 `iMakeBayAPI/check_csv_core.py` が使う eBay API credentials は app-level (client_credentials)
- これで取れるのは Browse API (公開検索) のみ
- listing の SKU/Qty を直接取得 or 変更するには Sell API or Trading API → user-OAuth (Authorization Code grant) 必須

現状の暫定:
- `ebay_sku_fetcher.py` は Mode A (`stub_from_sheet`) で動作
- SKU シートに既登録の SKU ID + 旧 Qty (人手登録) を信頼して使用
- 「eBay 現Qty」列の更新には Phase 4 で Sell API 連携を導入

## 認証

| 用途 | ファイル | 既存使用 |
|---|---|---|
| Google Sheets | `c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json` | iMakHQ control_panel / migrate_to_gsheet で使用中 |
| eBay (将来) | `iMakeBayAPI/ebay keys.txt` (AppID + CertID) | Browse API で稼働中 |

## 実行方法

### 単発 (手動)
```bash
cd c:\dev\iMak\iMakeBayAPI\inventory_monitor
python main.py                        # 全 UNIQLO listing
python main.py --listing 357401200653 # 特定 listing のみ
python main.py --dry-run              # スプシ書込なし、結果のみ console
```

### 単体テスト (各モジュール CLI)
```bash
# UNIQLO scraper 単体 (1 商品 URL)
python uniqlo_scraper.py "https://www.uniqlo.com/jp/ja/products/E483933-000/00?colorDisplayCode=09&sizeDisplayCode=004"

# Google Sheets 接続 + メインシート行読込
python sheet_updater.py

# eBay Browse API topline (SKU/Qty は取れない、active 確認のみ)
python ebay_sku_fetcher.py 357401200653
```

### 日次自動実行 (Windows タスクスケジューラ)

**設定手順** (1回だけ):

1. Win + R → `taskschd.msc` → タスクスケジューラ起動
2. 「タスクの作成」(右ペイン)
3. **全般タブ**:
   - 名前: `iMak inventory_monitor (UNIQLO daily)`
   - 「ユーザーがログオンしているかどうかにかかわらず実行する」
4. **トリガータブ** → 新規:
   - 毎日、開始: 7:00:00、繰り返し間隔: 1日
5. **操作タブ** → 新規:
   - プログラム/スクリプト: `python`
   - 引数の追加: `c:\dev\iMak\iMakeBayAPI\inventory_monitor\main.py`
   - 開始 (オプション): `c:\dev\iMak\iMakeBayAPI\inventory_monitor`
6. **条件タブ**:
   - 「コンピューターを AC 電源で使用している場合のみタスクを開始する」(必要に応じて)
7. **設定タブ**:
   - 「タスクが失敗した場合の再起動の間隔: 10分、最大 3回」
8. 保存 → 認証情報入力

実行ログ: `logs/YYYY-MM-DD.log` に日付別蓄積。

## メインシート (連携元) の前提

URL: https://docs.google.com/spreadsheets/d/101KL6KxMugKqZeSp2W5L2ykTvT0Zwd3RzlfsHgiJsg0/edit

| 列 | 内容 | 本ツールの読み方 |
|---|---|---|
| A | FLG | "1" 以外を active 扱い |
| D | listing ID | eBay item ID (例: 357401200653) |
| E | title | 商品名 (sheet 表示用、フィルタには未使用) |
| F | URL | 仕入元 URL (uniqlo.com ドメインのみ Phase 1 対象) |

## SKU シート (`SKU詳細` タブ) のレコード仕様

12 列構成 (Advisor が `_create_sku_sheet.py` で作成済):

| 列 | 名称 | 本ツールの書込 | 備考 |
|---|---|---|---|
| A | 対処要 | ✅ True/False を書込 | 仕入元✕ × eBay Qty>0 or 仕入元◎ × eBay Qty=0 |
| B | 対処済 | ✅ 既存値を保持 | 人手チェック用、ツールは触らない |
| C | 対処日 | ✅ 既存値を保持 | 人手記入用 |
| D | listing ID | ✅ 書込 | |
| E | title | ✅ 書込 | |
| F | eBay SKU ID | ✅ 既存値あれば保持、無ければ UNIQLO communication code を仮置 | Phase 4 で Sell API 連携 |
| G | サイズ | ✅ 書込 (XS/S/M/L 等) | |
| H | 色 | ✅ 既存値あれば保持、無ければ UNIQLO 名 | |
| I | 仕入元在庫 | ✅ 書込 (◎ / ✕) | |
| J | 仕入元価格 | ✅ 書込 (¥) | |
| K | eBay 現Qty | ⚠️ 既存値そのまま | Phase 4 で live 更新 |
| L | 自動CHK日 | ✅ 書込 (実行時刻) | |

条件付き書式:
- A=TRUE & B=FALSE → 赤背景 (要対処、未対応)
- B=TRUE → 緑背景 (対処済)

## Phase 2-4 計画

| Phase | 内容 | 工数 |
|---|---|---|
| **Phase 2** | montbell スクレイパー追加 (8 listing) | 中 (UNIQLO API のような公開 API の有無で差) |
| **Phase 3** | Amazon スクレイパー追加 (2 listing) | 大 (Amazon 公式 API or HTML scrape) |
| **Phase 4** | eBay Sell API user-OAuth 整備 → SKU/Qty 直接取得・自動 qty=0 (Level 3) | 大 (OAuth flow + token refresh + 安全網) |
| **Phase 5** | アラート通知のメール化 / Slack 化 | 小 |

## 完了基準 (Phase 1)

- [ ] uniqlo_scraper.py が 1 listing で動作 (例: マンガキュレーション UT 357401200653 / E483933) — **完了 2026-04-27**
- [ ] SKU シートに正しいデータが自動書き込みされる
- [ ] 対処要判定が正しく動く (仕入元✕ + eBay Qty>0 で A=TRUE)
- [ ] (Phase 1.5) アラート通知が飛ぶ
- [ ] UNIQLO 29 listing 全件で安定稼働
- [ ] 7日間連続実行で誤検知ゼロ

## 注意事項

- **無在庫モデル前提**。在庫塩漬けの議論は不要 (memory: `dropshipping_model_premise.md`)
- 既存の SSOT 抽象化方針に従う (Step 7-8、yaml SSOT、decision_log)
- Combined Payment / UPI 等の eBay 設定は触らない (Advisor 議論済、変更不要結論)
