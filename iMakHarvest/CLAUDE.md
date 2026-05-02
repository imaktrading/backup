# iMakHarvest — 商品ソース URL 集約プロジェクト

## 🛡️ Worktree 分離ルール (2026-05-01 制定・絶対厳守)

**この worktree (`C:/dev/iMak_harvest/`) は Harvest Claude 専用**。

- ✅ Harvest Claude: ここで作業
- ❌ Inventory Claude / Catalog Claude / その他: **絶対 touch 禁止**
- ❌ 他 worktree (`C:/dev/iMak/` `C:/dev/iMak_inventory/`) への touch も禁止

詳細は `.PROJECT_LOCKED.md` 参照。グローバル `~/.claude/CLAUDE.md` の Worktree 分離
ルールも厳守。違反は他プロジェクトの自動運用を破壊する致命行為。

---

iMak Trading Japan の出品候補商品の **入り口管理**。Mercari いいね /
Amazon お気に入り / 等から商品 URL を収集し、各カテゴリのスプシに転記する。

trabajo の `getMercariUrls / getAmazonUrls / etc` 機能の代替。

---

## 役割

| やる | やらない |
|---|---|
| Mercari いいねから URL 収集 | 出品作業 (各 listing project に任せる) |
| Mercari Shops products から URL 収集 | 在庫監視 (iMakInventory に任せる) |
| Amazon ウィッシュリストから URL 収集 | eBay 取り下げ (iMakInventory に任せる) |
| 各カテゴリのスプシに URL 書込 | リスティング作成 (iMakTCG / iMakG-shock / etc) |
| 重複防止 (item_id デドゥープ) | バイヤー対応 (iMakAdvisor) |
| GUI 操作パネル | コード修正 (iMakHQ) |
| 4h cron 自動巡回 (任意) | |

---

## スコープ (Phase 1)

- Mercari 通常 (`/item/m...`) いいね収集
- Mercari Shops (`/shops/product/...`) 収集
- Amazon ウィッシュリスト (ASIN 抽出)
- スプシ書込 (HIGH/LOW or 任意スプシ指定)

## Phase 2 (任意)

- ヤフオク・ラクマ・PayPay フリマ (現運用に対象無ければ不要)
- いいね削除機能 (収集後の整理)
- 既出品との突合 (eBay 出品中商品は除外)
- 4h cron + GUI

---

## 既存資産流用元

iMakInventory のコード資産を 70% 流用可能:

- Selenium + undetected_chromedriver + cookie 永続化 (`chrome_profile_*`)
- スプシ書込 (gspread + service account)
- 4h cron 統合 (Windows タスクスケジューラ)
- GUI フレームワーク (Tkinter)
- decision_log 記録方式
- トースト通知 (win10toast)
- pre-commit hook + pytest

---

## 関連プロジェクト

- **入力源**: Mercari / Amazon / (Yahoo Auctions / Rakuma / PayPay フリマ)
- **出力先**: 各カテゴリのスプシ (TCG / G-shock / Mercari listing 用 / 一番くじ / etc)
- **下流**: iMakTCG / iMakG-shock / iMakMercari / iMak_ichibankuji が出力スプシを読んで eBay 出品作成
- **並走**: iMakInventory (在庫監視・取り下げ)、iMakHarvest (URL 収集)、両者で trabajo 完全代替

---

## ディレクトリ構成 (想定)

```
iMakHarvest/
├── CLAUDE.md
├── scrapers/
│   ├── mercari_likes.py        ← メルカリ いいね収集
│   ├── mercari_shops_likes.py  ← Mercari Shops 収集
│   └── amazon_wishlist.py      ← Amazon ウィッシュリスト
├── sheet_writer.py             ← スプシ書込
├── run_harvest.py              ← エントリポイント
├── control_panel.py            ← GUI (Phase 2)
├── tests/
└── decision_log/
```

---

## NG (やってはいけないこと)

- 出品作業 (各カテゴリ listing project に任せる)
- 在庫監視・取り下げ (iMakInventory に任せる)
- 重複した URL のスプシ書込 (item_id 単位デドゥープ必須)
- 既出品 (eBay 出品中) 商品の再収集 (将来 Phase 2 で eBay と突合)

---

## セッション開始時の必須読み込み

iMakHarvest は他プロジェクトと連携するため、開始時に以下を読む:

- `C:\Users\imax2\.claude\CLAUDE.md` (グローバル / 全プロジェクト共通ルール)
- `C:\dev\iMak\iMakHQ\CLAUDE.md` (司令塔)
- `C:\dev\iMak\iMakInventory\CLAUDE.md` (姉妹プロジェクト、コード資産流用元)
- このファイル (`CLAUDE.md`)
- 該当時に各 listing project の CLAUDE.md
