# iMakInventory 設計書 (Phase 0 → Phase 1 着手版)

最終更新: 2026-04-29 (Takaaki さん確定要件 + トラバホ Log.txt 解析反映)
作成: HQ Claude
状態: Phase 0 完了 → Phase 1 着手中

---

## 0. エグゼクティブサマリ

### 確定運用フロー (2026-04-29 Takaaki さん確定)

```
1. メルカリ/Amazon URL を 4時間おきに監視 (cron 0/4/8/12/16/20 時)
   ↓
2. 仕入元で売り切れ検知 → 在庫管理スプシ (101KL6...) に ○ (FLG 更新)
   ↓
3. Revise CSV 自動生成 (FileExchange 形式 / Quantity=0)
   ↓
4. eBay FileExchange Web UI に Selenium で自動アップロード (人手介在ゼロ)
```

### 確定要件

| 要件 | 値 | 備考 |
|---|---|---|
| 監視頻度 | **4時間おき** | cron 0/4/8/12/16/20 時、TCG/服 全商材一律 |
| 自動アップロード | **必須** | 人手介在ゼロ、寝てる時間も監視→取り下げまで完遂 |
| 自動アップロード方式 | **Selenium (FileExchange Web UI)** | トラバホ Log.txt 解析で判明、Sell Feed API 不採用 |
| 安全装置 | **cap / decision_log / dry-run** | Precision 100% 維持、誤取り下げ厳禁 |
| 優先順位 | **TCG PSA10 (メルカリ仕入)** | 1点もの仕入競合 → Defect Rate 直撃リスク最大 |

### Phase 計画 (確定版、合計 3-4日)

| Phase | 内容 | 工数 | 状態 |
|---|---|---|---|
| **0** | 設計フェーズ | (済) | ✅ 完了 |
| **1** | Mercari/Amazon scraper + graduation | 1-2日 | 🚧 着手 |
| **2** | スプシ FLG 更新 | 数時間 | pending |
| **3** | Revise CSV 生成 (FileExchange 形式) | 数時間 | pending |
| **4** | eBay Selenium FileExchange Web UI 操作 + 安全装置 | 1-2日 | pending |
| **5** | cron + 通知 + 統合 | 半日 | pending |

**Phase 4 が Sell Feed API → Selenium で大幅短縮された根拠**:
- トラバホ Log.txt (`C:\トラバホセット\…\BoostListing\Log.txt`) を解析
- 同 ツールは ChromeDriver 経由で eBay にログイン → FileExchange Web UI から CSV をアップロード
- ログパターン: `ebayにログイン中` → `ebay用のcsvを生成` → `ebayにUploadします` → `ファイルアップロードが完了しました - ポップアップ内のダウンロードリンクを確認` → `Upload成功しました!`
- → user-OAuth (Authorization Code grant) 不要、RuName 申請不要、Sell Feed API 学習不要
- 制約: Akamai Bot 検知対策と session 維持が技術ポイント (元設計の Phase 3 リスクが Phase 4 に圧縮)

### 戻り地点

- master HEAD (`555729b`) 維持
- Phase 1 は新ブランチ (`feature/inventory-phase1`) で進行
- 各 Phase 完成毎に commit + ユーザー報告

---

## 0.5. Revise CSV 仕様 (確定 / トラバホ互換)

トラバホ実 CSV 解析結果 (`C:\トラバホセット\BoostListing\…\csv\delete*.csv`):

```csv
*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8),ItemID,*Quantity
Revise,356802747021,0
Revise,356802747026,0
```

- **Action 列名**: `*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8)` (eBay FileExchange 標準)
- **Action 値**: `Revise` (delete ではなく Revise + Quantity=0 が事実上の取り下げ)
- **エンコーディング**: UTF-8 BOM なし (グローバル CLAUDE.md 規約)
- **生成タイミング**: 在庫切れ検知 → スプシ FLG 更新の直後 (Phase 3)
- **入稿先**: eBay Sell Feed API `/sell/feed/v1/inventory_task` (Phase 4)

価格改定 (将来用): `update_price_*.csv` も同形式で `*StartPrice` 列を持つ → Phase 5 以降で対応可。

---

## 1. iMakInventory の関連ファイル状態 (graduation 計画)

### 1.1 graduation ソース

`iMakeBayAPI/inventory_monitor/` (既存稼働中):
- main.py (348 LOC) - UNIQLO/montbell オーケストレーション
- uniqlo_scraper.py (294 LOC) - L2S API 経由
- montbell_scraper.py (431 LOC) - HTML scrape
- ebay_sku_fetcher.py (175 LOC) - sheet 参照モード
- sheet_updater.py (282 LOC) - gspread + 12列スキーマ
- _populate_ebay_data.py (228 LOC) - Browse API メタ取得
- _clear_sku_sheet.py (38 LOC) - 開発用

### 1.2 Phase 1 graduation 戦略

**コピーではなく import 再利用** (技術的負債を残さない):

```
iMakInventory/
├── scrapers/
│   ├── __init__.py
│   ├── mercari_scraper.py       # 新規 (Phase 1)
│   ├── amazon_scraper.py        # 新規 (Phase 1)
│   ├── uniqlo_scraper.py        # iMakeBayAPI から移動
│   └── montbell_scraper.py      # iMakeBayAPI から移動
├── ebay_actions/
│   ├── __init__.py
│   ├── revise_csv_generator.py  # 新規 (Phase 3)
│   └── sell_feed_api_client.py  # 新規 (Phase 4)
├── sheet_updater.py             # iMakeBayAPI から移動
├── ebay_sku_fetcher.py          # iMakeBayAPI から移動
├── monitor.py                   # 旧 main.py を改名 (cron 統合点)
├── docs/
│   └── design.md
└── tests/
```

`iMakeBayAPI/inventory_monitor/` は移植後に **deprecation note** を README に追記して残置 (cron が指している間は壊さない、cron 切替後に削除)。

---

## 1. プロジェクト位置づけ

### 1.1 何を作るか

トラバホ (市販 SaaS) 代替の**自社在庫監視 + eBay 自動取り下げ統合プラットフォーム**。

| 機能 | カバー範囲 |
|---|---|
| 仕入元在庫監視 | UNIQLO / montbell (Phase 1 既存) → Mercari / Amazon / Rakuma / Yahoo (本プロジェクト追加) |
| 在庫変化検知 → eBay 反映 | Phase 3 で eBay listing の qty=0 化 / 完全取り下げを自動化 |
| スプシ連携 | sheet 101KL6... の `SKU詳細` タブ更新 (既存) を継続 |
| 通知 | Slack / Discord / メール (Phase 5) |

### 1.2 何を作らないか (CLAUDE.md より引用)

- 出品 CSV 生成 (各 listing project が担当)
- 商品マスター管理 (iMakCatalog が担当)
- バイヤー対応 (iMakAdvisor が担当)

---

## 2. 現状把握: 既存資産の精査結果

### 2.1 衝撃的発見: `iMakeBayAPI/inventory_monitor/` が Phase 1 相当を既に保有

```
iMakeBayAPI/inventory_monitor/
├── README.md               # Phase 1 完了基準・運用手順記載済
├── main.py            (348 LOC) # オーケストレーション、--listing / --dry-run 引数対応
├── uniqlo_scraper.py  (294 LOC) # UNIQLO L2S JSON API → SKU × 在庫 × 価格
├── montbell_scraper.py (431 LOC) # montbell HTML scrape
├── ebay_sku_fetcher.py (175 LOC) # Mode A: SKU シート参照 (Sell API 待ち)
├── sheet_updater.py   (282 LOC) # gspread + 12列スキーマ完全実装
├── _populate_ebay_data.py (228 LOC) # eBay Browse API で listing メタ取得
├── _clear_sku_sheet.py (38 LOC) # 開発用ユーティリティ
└── logs/              # 日次 .log + _last_needs_action_count.json
```

**機能稼働状況** (README.md L141 完了基準より):
- ✅ UNIQLO 1 listing 動作確認済 (357401200653 / E483933、2026-04-27)
- ✅ SKU シート自動書込
- ✅ 対処要判定ロジック実装済
- ✅ Windows タスクスケジューラ手順書化 (毎日 7:00 AM 実行、3回 retry)
- ⚠️ Phase 1.5 アラート通知メール (未実装)
- ⚠️ UNIQLO 29 listing 全件安定稼働 (未検証)

### 2.2 graduation 推奨理由 (Phase 0.5)

| 観点 | 現状 (iMakeBayAPI 内) | iMakInventory 移植後 |
|---|---|---|
| 役割境界 | iMakeBayAPI は eBay API ユーティリティ + listing 共通基盤、在庫監視は本来別関心事 | iMakInventory は **在庫監視専属**、責務が明確 |
| 規模 | 1796 LOC が iMakeBayAPI に同居、git diff が混雑 | iMakInventory に独立、CI/test も独立可 |
| 拡張時の動線 | Mercari scraper を追加すると iMakeBayAPI が肥大、TCG/Mercari 系と関心事が混ざる | プラグイン的 (各 supplier 1 ファイル) に追加可 |
| 命名 | `iMakeBayAPI.inventory_monitor` パス長い、import 煩雑 | `iMakInventory.scrapers.uniqlo_scraper` 直感的 |

**移植コスト見積**: 半日〜1日 (主にパス書換 + import 修正、ロジック改変ゼロ)。

---

## 3. 既存資産の再利用マトリクス

### 3.1 直接 import 再利用可

| 機能 | 提供元 | 関数 | 用途 |
|---|---|---|---|
| Selenium driver 構築 | iMakMercari/mercari_scout.py:69 | `create_driver()` | undetected_chromedriver + Chrome プロファイル永続化 |
| 商品ページ画像取得 | iMakMercari/mercari_scout.py:548 | `download_image_via_selenium(driver, url)` | 403 回避済の画像 fetch |
| gspread 認証 | iMakeBayAPI/inventory_monitor/sheet_updater.py:61 | `open_sheet()` | 既存 service account JSON 共用 |
| メインシート読込 | iMakeBayAPI/inventory_monitor/sheet_updater.py:98 | `read_main_active_rows(supplier=...)` | filter by uniqlo/montbell/all |
| SKU シート batch 更新 | iMakeBayAPI/inventory_monitor/sheet_updater.py:162 | `update_sku_rows()` | A=対処要 / B=対処済 / C=対処日 など |
| 対処要判定 | iMakeBayAPI/inventory_monitor/sheet_updater.py:250 | `determine_needs_action(supplier, ebay_qty)` | (✕ × Qty>0) または (◎ × Qty=0) |
| eBay OAuth トークン (Browse) | iMakeBayAPI/check_csv_core.py:52 | `get_oauth_token(app_id, app_secret)` | Browse API のみ、Sell API 不可 |
| eBay credentials 読込 | iMakeBayAPI/check_csv_core.py:38 | `load_ebay_keys()` | `ebay keys.txt` パース |
| eBay listing メタ取得 | iMakeBayAPI/inventory_monitor/_populate_ebay_data.py:85 | Browse API GetItem 相当 | listing 情報の sheet 反映 |

### 3.2 新規実装が必要

| 機能 | 理由 | 工数感 |
|---|---|---|
| **Mercari sold-out 検知** | iMakMercari に sold 検知ロジック存在せず (既存は出品 scout のみ) | 中 (1〜2日) |
| **Amazon 在庫検知** | 既存資産ゼロ。PA-API or Selenium scrape の選択 | 中〜大 |
| **Rakuma sold-out 検知** | 既存資産ゼロ | 中 |
| **Yahoo Auctions 終了検知** | 既存資産ゼロ、入札終了/落札済の状態区別必要 | 中 |
| **eBay Sell API user-OAuth** | iMakeBayAPI は client_credentials のみ、Authorization Code grant 未実装 | 大 (3〜5日、要トークン refresh + 安全網) |
| **eBay 自動取り下げ** | 上記の上に積む、Inventory API or Trading API EndItem | 中 |
| **Slack/Discord/メール通知** | 通知パイプライン未実装 | 小 (各 0.5日) |

---

## 4. 各仕入元のスクレイピング難易度調査

### 4.1 メルカリ

| 観点 | 評価 | コメント |
|---|---|---|
| 公開 API | × | なし。HTML scraping 必須 |
| 認証 | △ | 一部商品ページで Cookie 必要 (iMakMercari の Chrome プロファイル永続化で吸収済) |
| anti-bot | △ | undetected_chromedriver で現状 OK、Akamai 系の重さは無し |
| sold 判定 | ○ | 「SOLD」バッジ DOM が明確、ボタン無効化でも判別可 |
| pacing 推奨 | sleep 5〜10秒 + 1日数百件まで | iMakMercari mercari_scout.py で実績あり |
| 既存資産 | ◎ | create_driver / 画像取得は丸ごと再利用 |

**推奨実装方式**: iMakMercari の Selenium 基盤に乗っかり、`scrapers/mercari_scraper.py` で `is_sold(driver, url) -> bool` を提供。

### 4.2 Amazon (.co.jp)

| 観点 | 評価 | コメント |
|---|---|---|
| 公開 API (PA-API) | △ | 売上アフィリエイト報酬 ≥ 規定額が継続条件、停止リスクあり |
| HTML scraping | × | 強力な anti-bot (CAPTCHA / IP block 高頻度)、Akamai 系 |
| sold 判定 | ○ | "Currently unavailable" / "在庫切れ" 表示の DOM が明確 |
| pacing 推奨 | sleep 10〜30秒 + IP rotation 必須レベル | 過去事例 (Akamai ブロック) 既知 |
| 既存資産 | △ | iMakMercari/amazon_jp.py が "公式仕様取得" 用途で存在、在庫判定ではないが Selenium pattern 参考可 |

**推奨実装方式 2 案**:

- **Plan A (PA-API)**: アフィリエイト売上の維持が前提。安定性高、運用コスト低
- **Plan B (Selenium scrape)**: NordVPN 切替 + sleep 30秒以上 + retry。安定性低、運用負荷大

→ **Plan A を第一推奨**。アフィリエイト要件未達なら Plan B にフォールバック。

### 4.3 ラクマ

| 観点 | 評価 | コメント |
|---|---|---|
| 公開 API | × | なし |
| HTML scraping | ○ | メルカリより緩い anti-bot (個人運営時代の名残) |
| sold 判定 | ○ | "SOLD" バッジ DOM 明確 |
| pacing 推奨 | sleep 3〜5秒 | |
| 既存資産 | × | ゼロ、新規実装 |

**推奨実装方式**: Selenium よりも `requests + lxml` で軽量実装可能。低コスト。

### 4.4 ヤフオク

| 観点 | 評価 | コメント |
|---|---|---|
| 公開 API | △ | YJAPI (旧 Yahoo オークション API) は終了、現在は限定的 |
| HTML scraping | ○ | scraping 親和性高 |
| sold 判定 | ○ | "落札" 表示 / 終了日時で判別 |
| 落札 vs 終了 (未落札) の区別 | △ | iMakInventory 視点では「終了 = 取り下げ対象」一律処理で OK |
| pacing 推奨 | sleep 3〜5秒 | |
| 既存資産 | × | ゼロ |

### 4.5 ヤフショ (Yahoo!ショッピング)

| 観点 | 評価 | コメント |
|---|---|---|
| 公開 API | ○ | Yahoo!ショッピング商品検索 API 利用可 |
| HTML scraping | △ | 公開 API があるので scrape は不要 |
| sold 判定 | ○ | API レスポンスの `inStock` フィールド |
| pacing 推奨 | API 提供のレート制限内 | |
| 既存資産 | × | ゼロ、ただし API 経由なら工数小 |

### 4.6 IP ブロック対策の共通方針

| 対策 | 適用先 | コスト |
|---|---|---|
| sleep ベース pacing | 全サイト | 既存実装あり (iMakMercari) |
| NordVPN IP rotation | Amazon scrape のみ (Plan B 採用時) | 既契約あり (memory `reference_nordvpn.md`) |
| undetected_chromedriver | Mercari / ラクマ | iMakMercari 既存利用 |
| Cookie 永続化 (Chrome プロファイル) | Mercari (一部商品ページ) | iMakMercari 既存実装 |
| API 経由優先 | Amazon (PA-API) / ヤフショ | scraping 0 で済む |

---

## 5. eBay 自動取り下げ方式 (Phase 4: Selenium FileExchange Web UI)

### 5.1 方式選定 (確定)

トラバホ Log.txt 解析で判明した運用パターンを採用:

| 観点 | Selenium FileExchange Web UI | (旧案) Sell Feed API |
|---|---|---|
| 認証 | eBay 通常ログイン (cookie 永続化) | OAuth 2.0 Authorization Code grant + RuName |
| 入稿フォーマット | FileExchange CSV (`Revise,<itemID>,0`) | JSON or XML payload |
| Developer Console 申請 | 不要 | 必須 (RuName 承認に数日) |
| 既存知見 | トラバホ Log.txt の動作シーケンス | ゼロ |
| 構築工数 | **1〜2日** | 4.5〜5.5日 |
| Akamai Bot 対策 | 必要 (undetected_chromedriver + cookie 持越) | 不要 |
| セッション維持 | 自前 (login 切れ検知 + 再 login) | refresh token で自動 |

→ **Selenium FileExchange Web UI 方式を採用**。トラバホ実績で安定動作確認済 (Log.txt の数百件アップロード履歴)。

### 5.2 トラバホ Log.txt から判明した動作シーケンス

```
1. ChromeDriver 起動 (chromep.exe, profile 永続化)
2. eBay にログイン (URL polling で完了確認)
3. 在庫 CSV (delete*.csv = Quantity=0 Revise) を生成
4. FileExchange Web UI にアップロード
5. ポップアップ内のダウンロードリンク (= 結果ファイル) を確認
6. (続けて) 価格更新 CSV (update_price_*.csv) も同様にアップロード
```

ログから読取れる注意点:
- セッション切れで `WebDriverException ConnectFailure` 多発 → 再ログインリトライ実装必須
- Chrome window 最小化禁止 (Selenium が "Chromeのウインドウを最小化は控えてください" エラーを投げる)
- `chromep.exe` (= chromium portable) 起動失敗もそこそこ頻発 → リトライ + driver 再起動必要
- 在庫 CSV (Quantity=0) は **「Upload失敗しました」** 表示でも実は内部的に処理されているケースが多い (Log.txt の delete CSV 失敗パターン頻発が、業務継続できている事実が裏付け) → ポップアップの実テキスト判定はベストエフォート、最終確認はスプシで取れる ItemID×Qty で行う

### 5.3 eBay FileExchange Web UI 仕様 (公開情報)

- アップロード URL (推定): `https://k2b-bulk.ebay.com/ws/eBayISAPI.dll?FileExchangeUploadForm`
- 必要権限: 通常 eBay seller 権限のみ (FileExchange は Standard 機能、Subscribe Free)
- 認可: cookie ベースのログインセッション
- 入稿後: ポップアップで "Job ID" + 結果ダウンロードリンク (CSV) を返す

### 5.4 Phase 4 タスク分解

| サブフェーズ | 内容 | 工数 |
|---|---|---|
| 4-A | `ebay_actions/sell_feed_uploader.py`: ChromeDriver 起動 (undetected_chromedriver) + cookie 永続化 + login 検証 | 0.5日 |
| 4-B | FileExchange Upload Form 操作 (file_input.send_keys + Submit + ポップアップ待ち) | 0.5日 |
| 4-C | セッション切れ自動検知 + 再ログイン (Log.txt パターン参考) | 0.25日 |
| 4-D | dry-run mode (Selenium まで起動して実 Submit はしない) + decision_log 完全保存 | 0.25日 |
| 4-E | smoke test (テスト用 listing で qty=0 ↔ 復活) | 0.5日 |

合計: **1〜2日**

### 5.5 安全網 (Precision 100% 大前提)

- スクレイピング失敗 (HTTP 5xx / Selenium timeout) → 自動取り下げ**発動しない**
- sold 判定の信頼度スコア < 閾値 → 通知のみ、自動取り下げ保留
- 1 run あたりの最大取り下げ件数を **5件 cap** (連鎖事故防止)
- すべての取り下げ操作を `decision_log/inventory_actions_*.jsonl` に追記
- Selenium 操作前後で eBay listing の現状 Qty を Browse API で record (取り下げ前後の差分がトレース可能)
- アップロード前 CSV 内容を decision_log に raw 保存
- ポップアップ結果 (成功/失敗テキスト + Job ID) を decision_log に保存
- **法的リスク回避**: トラバホの .exe / .dll は逆コンパイル禁止、参考はあくまで Log.txt + 公開 CSV + 公開 FileExchange 仕様のみ

---

## 6. 監視運用設計

### 6.1 cron 間隔設計 (確定)

**全商材一律 4時間おき** (Takaaki さん確定要件):

| 起動時刻 | 内容 |
|---|---|
| 00:00 | 全 supplier 監視 → 必要時 Revise CSV → Selenium upload |
| 04:00 | 同上 |
| 08:00 | 同上 |
| 12:00 | 同上 |
| 16:00 | 同上 |
| 20:00 | 同上 |

理由: TCG 1点ものの仕入競合速度に合わせ、寝てる時間帯 (00/04 時) も自動取り下げまで完遂する必要あり。

実装: Windows タスクスケジューラ 1 タスクで 4h 繰返し (既存 inventory_monitor で 7:00 daily 実績、cron 間隔のみ変更)。

### 6.2 並列度

| 並列軸 | 推奨値 | 制約 |
|---|---|---|
| 同一 supplier 内の listing 並列 | 1 (= sequential) | IP ブロック回避 |
| supplier 別 (Mercari + Amazon) 並列 | 2 | 別ドメインなのでサーバー側に影響なし |
| eBay FileExchange アップロード | 1 (= sequential) | Selenium driver は単一インスタンス、Akamai セッション維持 |

### 6.3 通知設計

| 種類 | チャネル | トリガー |
|---|---|---|
| 即時 | Discord (推奨、無料 + bot 簡単) | 自動取り下げ発動時 |
| 日次サマリ | メール | 検知 0件でも `要対処 N件` を朝 8:00 に送信 (現状の Windows Task ログを置換) |
| 異常 | Discord + メール | scraper 失敗 / API 認証エラー |

→ **Discord webhook 第一推奨** (Slack より個人運用向き、Telegram も可)。

### 6.4 在庫変化検知 → スプシ FLG 更新

既存の `update_sku_rows()` を流用するだけ。新 supplier 追加時は `read_main_active_rows(supplier="mercari")` フィルタを sheet_updater に追加。

---

## 7. スプシ連携 (101KL6...) 仕様

### 7.1 既存 schema (12 列、変更不要)

| 列 | 名称 | 用途 | 書込方針 |
|---|---|---|---|
| A | 対処要 | 自動判定 (TRUE/FALSE) | iMakInventory 上書き |
| B | 対処済 | 人手 | **絶対不変** |
| C | 対処日 | 人手 | **絶対不変** |
| D | listing ID | eBay item ID | iMakInventory 上書き |
| E | title | listing title | iMakInventory 上書き |
| F | eBay SKU ID | SKU 識別 | 既存値あれば保持、無ければ supplier 由来コード仮置 |
| G | サイズ | 服系で使用 | iMakInventory 上書き |
| H | 色 | 服系で使用 | 既存値あれば保持 |
| I | 仕入元在庫 | ◎ / ✕ | iMakInventory 上書き |
| J | 仕入元価格 | ¥ | iMakInventory 上書き |
| K | eBay 現Qty | live qty | Phase 3 (Sell API) 着手後のみ更新 |
| L | 自動CHK日 | timestamp | iMakInventory 上書き |

### 7.2 バリエ/バンドル対応

UNIQLO の listing は GTC + Multi-Variation 出品なので 1 listing = 多 SKU。Mercari は基本 1 商品 = 1 SKU。混在時の論理:

- 1 listing N SKU の場合、`SKU詳細` タブには **SKU ごとに行を持つ** (既存仕様)
- listing 全体の対処要 = **SKU いずれかが対処要** (= OR 集約) — main sheet 側の集約表示用、別ヘルパで実装可 (既存無し、Phase 5 候補)

---

## 8. Phase 計画 (確定版・実装順序)

### 8.1 順序 (依存関係順、合計 3-4日)

```
Phase 0 (設計、本ドキュメント)        ←✅ 完了
  ↓
Phase 1: Mercari/Amazon scraper + graduation       ←1-2日 🚧 着手
  iMakeBayAPI/inventory_monitor/ を iMakInventory/ に移植
  + scrapers/mercari_scraper.py (TCG 優先)
  + scrapers/amazon_scraper.py
  ↓
Phase 2: スプシ FLG 更新 (在庫切れ → ○)              ←数時間
  既存 sheet_updater 拡張、新 supplier 用フィルタ
  ↓
Phase 3: Revise CSV 生成 (FileExchange 形式)         ←数時間
  ebay_actions/revise_csv_generator.py
  ↓
Phase 4: Selenium FileExchange Web UI 操作          ←1-2日
  ebay_actions/sell_feed_uploader.py + 安全装置
  ↓
Phase 5: cron + 通知 + 統合                          ←半日
```

合計: **3〜4日** (Selenium 採用で旧設計 15-23日から大幅短縮)

### 8.2 各 Phase 詳細

#### Phase 1: Mercari/Amazon scraper + graduation (🚧 着手中)

| タスク | 工数 |
|---|---|
| 1-A: `iMakeBayAPI/inventory_monitor/` 全 7 ファイルを `iMakInventory/` に移植 + import 書換 | 0.5h |
| 1-B: `scrapers/mercari_scraper.py` 新規 (`is_sold(url) -> bool`, TCG PSA10 想定) | 0.5日 |
| 1-C: iMakMercari の `create_driver` を import 再利用 | 0.25日 |
| 1-D: `scrapers/amazon_scraper.py` 新規 (Plan A: PA-API or Plan B: Selenium、要決定) | 0.5日 |
| 1-E: `monitor.py` (旧 main.py) に supplier 分岐追加 (mercari/amazon) | 0.25日 |
| 1-F: `sheet_updater.py` の `read_main_active_rows` に supplier フィルタ追加 | 0.25h |
| 1-G: dry-run + 1listing smoke test (TCG メルカリ 1件) | 0.5日 |

**TCG PSA10 優先理由**: 1点もの仕入競合 → 同じ商品を別バイヤーが先取り → メルカリ売切 → eBay は live のまま → 売れた→仕入れ不可→キャンセル → Defect Rate 直撃。これが iMak 全体で最大級リスク。

#### Phase 2: スプシ FLG 更新 (✅ 完了 2026-04-29)

**監視対象スプシ (Takaaki さん確定)**:
- HIGH: `19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk` (商品 421 件)
- LOW : `1jF9vggbfUCddjneROMO2GGN-jTAPRbq6Qe2cbgr37B0` (商品 650 件)
- 共通 gid: `851100680` (タブ「商品管理シート」)
- 在庫管理スプシ (101KL6...) は別運用 (UNIQLO/montbell バリエ管理)、Phase 2 範囲外

**スプシ列マッピング (両 spreadsheet 共通 schema)**:
| 列 | 内容 | Phase 2 動作 |
|---|---|---|
| A | URL (Mercari/Amazon) | 読込 |
| B | itemID (eBay) | 読込 (Phase 3 Revise CSV で使用) |
| C | タイトル | 読込 (ログ表示用) |
| D | 売り切れ | **書込: 売切=「○」、在庫あり=「""」** |
| O | 売り切れチェック時間 | **書込: timestamp** |

**実装**:
- [sheet_updater.py](../sheet_updater.py): `open_sheet_by_id` / `get_listings_worksheet` / `read_listings_rows` / `update_listings_sold_marks` 追加
- [monitor_listings.py](../monitor_listings.py): HIGH/LOW 専用 entry point。`--sheet {high,low,both} --start N --end N --limit N --dry-run --sleep S` をサポート
- [scrapers/mercari_scraper.py](../scrapers/mercari_scraper.py): **Selenium ベースに全面改修**

**Mercari 検知方式の重要変更 (2026-04-29 発見)**:
- メルカリは 2026 年に Next.js App Router 移行済 → 静的 HTML に `__NEXT_DATA__` が無くなった
- 公開 API (`api.mercari.jp/items/get`) は **DPoP token 必須** で叩けない
- → **Selenium で実描画後の DOM testid を見るのが唯一の方式**
  - `[data-testid="checkout-button"]` 存在 → 通常 item 在庫あり
  - `[data-testid="variant-purchase-button"]` 存在 → Mercari Shops 在庫あり
  - 該当 testid なし (timeout) → 売切判定
- iMakMercari の Chrome プロファイル流用 (ログイン状態継承)
- driver は monitor_listings 内で 1 つ生成・全行で再利用 (起動コスト削減)

**smoke test 結果 (HIGH の最初 50 行 dry-run)**:
- 処理: 50/50、Mercari 47件 + ラクマ 3件 (skip)
- 検知: ON_SALE 46 / SOLD_OUT 1 (row 30) / 新規復活 1 (row 6)
- 1 URL あたり ~6.2 秒 (起動 8 秒 + 49 URL × 6.2 秒)
- 全 1071 URL 推定: ~110 分 (4h cron 内に収まる)
- decision_log を `decision_log/listings_<sheet>_<ts>.jsonl` に完全保存

**ラクマ (fril) 対応**:
- HIGH/LOW 内に `item.fril.jp` URL が混在 → 現状は "other" supplier として skip (連続失敗カウント外)
- 必要なら Phase 4 以降で `scrapers/rakuma_scraper.py` 追加可

**運用フロー (Phase 3 への入口)**:
1. cron 4h おきに `python monitor_listings.py --sheet both` を実行
2. 売切検知 → D="○", O=timestamp が書込まれる
3. Phase 3 で D="○" の行から B (itemID) を集めて Revise CSV 生成

**実装済み safety**:
- fail-closed: scraper が None 返す場合は書込しない (D 列の現状維持)
- decision_log: 各 run の全結果を .jsonl で保存 (Phase 4 取り下げ前に追跡可能)
- 連続 8 失敗 (anti-bot 疑い) で abort
- dry-run mode: スプシ書込なし、判定のみ + decision_log は保存

#### Phase 3: Revise CSV 生成 (数時間)

`ebay_actions/revise_csv_generator.py` 新規:
- 入力: スプシで対処要かつ自動取り下げ条件を満たす行 (cap 5件以内)
- 出力: `csv_output/revise_<timestamp>.csv` (FileExchange 形式、UTF-8 BOMなし)
- 列: `*Action(SiteID=US|Country=JP|Currency=USD|Version=745|CC=UTF-8),ItemID,*Quantity`
- 値: `Revise,<itemID>,0`
- decision_log/inventory_actions_<timestamp>.jsonl に raw 記録

#### Phase 4: Selenium FileExchange Web UI 操作 (1-2日)

§5.2-5.5 参照。

#### Phase 5: 統合運用 (半日)

| タスク | 工数 |
|---|---|
| 5-A: cron (Windows タスクスケジューラ) 4h 間隔登録 | 0.25h |
| 5-B: 通知 (decision_log + メール暫定、Discord 後回し) | 0.25日 |
| 5-C: control_panel.py に「在庫監視 / 自動取り下げ」ボタン (HQ 統合、任意) | 0.25日 |
| 5-D: 1週間連続稼働観察 + 誤検知ゼロ確認 | 観察期間 (作業時間ゼロ) |

---

## 9. リスク評価

### 9.1 技術リスク

| リスク | 確率 | 影響 | 緩和策 |
|---|---|---|---|
| eBay FileExchange Akamai Bot 検知 | 中 | 大 (Phase 4 全停止) | undetected_chromedriver + cookie 永続化 + 通常ブラウザの操作タイミング模倣 |
| eBay session 切れ多発 | 中 | 中 (Phase 4 リトライ多発) | login 切れ自動検知 + 再 login (Log.txt パターン参考) |
| Amazon PA-API のアフィリ要件未達 | 中 | 中 (Plan B fallback で +1〜2日) | アフィリ売上監視を運用に組込 |
| Mercari の anti-bot 強化 | 中 | 中 | sleep 増 + Chrome プロファイル更新で対応、長期的には Selenium → Playwright 検討 |
| Akamai ブロック (Amazon scrape Plan B) | 高 | 中 | NordVPN rotation + sleep 30s + retry exponential backoff |
| eBay 誤取り下げ (sold 判定の偽陽性) | 低〜中 | **大** (出品アカウント信頼度低下) | dry-run / 信頼度閾値 / cap 5件 / decision_log 完全保存 |
| 並列セッション間で同 sheet 競合 | 低 | 中 | sheet_updater の batch_update + 楽観的同期で軽減、複数 cron 多重起動を回避 |
| Chrome バージョン更新で chromedriver 不整合 | 中 | 中 | webdriver-manager で chromedriver 自動更新、または undetected_chromedriver の version_main 指定 |

### 9.2 運用リスク

| リスク | 緩和策 |
|---|---|
| 各サイトの HTML 構造変更 | 月次 smoke test を Phase 5 で組込 |
| 監視 silent failure (cron 起動失敗・log 0行) | 「last_run > 25h で警告」を追加 |
| サブスク (NordVPN / PA-API キー) 失効 | 年次更新リマインダー |

### 9.3 戦略リスク

| リスク | コメント |
|---|---|
| トラバホ撤退タイミング | iMakInventory が安定稼働するまで並走 (= 二重支払あり)、Phase 3 完了 + 1ヶ月実績で乗換 |
| 新規 supplier 追加要件発生 | プラグイン構造で吸収 (`scrapers/` に 1 ファイル追加 + sheet_updater の supplier 名追加) |

---

## 10. オープン質問 (ユーザー判断保留中)

Takaaki さん確定 (2026-04-29) で多くは決着済。残り未決:

1. **Amazon は Plan A (PA-API) / Plan B (Selenium) どちら?**
   - 現在のアフィリ売上額 (PA-API 維持要件) によって決まる
   - 不明なら Phase 1 の Amazon scraper 着手直前に Amazon Associates ダッシュボードで要件確認
   - 暫定方針: Phase 1 では Selenium ベースで先行実装、PA-API 移行は後回し可

2. **TCG メルカリ URL の管理方針**
   - 既存スプシ (101KL6...) のどの行に TCG が入るか? FLG 列の使い方は?
   - 暫定方針: メインシートの supplier 列を `mercari` で識別、URL 列に商品ページ直リンク

3. **iMakHQ control_panel への統合タイミング**
   - Phase 5-C で組込予定、必須ではない (cron 経由運用がメイン)

---

## 11. 戻り地点 / 安全策

- 戻り地点: master HEAD (現在 `555729b`) は維持
- Phase 1 着手時は `feature/inventory-phase1` branch 経由 (CLAUDE.md `branch_usage_policy.md` に従う、複数 commit が見込まれる規模)
- 各 Phase 完成毎に commit + ユーザー報告 (CLAUDE.md「完了報告は事実+検証」原則)

---

## 12. 次のアクション (Phase 1 着手)

- [x] design.md 確定要件反映 (本コミット)
- [ ] feature/inventory-phase1 ブランチ作成
- [ ] iMakeBayAPI/inventory_monitor 移植 (1-A)
- [ ] mercari_scraper.py 実装 (1-B/C)
- [ ] amazon_scraper.py 実装 (1-D)
- [ ] monitor.py 拡張 (1-E)
- [ ] sheet_updater.py 拡張 (1-F)
- [ ] dry-run + smoke test (1-G)
- [ ] Phase 1 完了報告
