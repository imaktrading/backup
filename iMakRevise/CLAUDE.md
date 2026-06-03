# iMakRevise — eBay 出品メンテ専門 (リバイスくん)

iMak Trading Japan の **eBay 既存出品の更新系** 全般を担当する専用プロジェクト。

## 🛡️ Worktree 分離ルール (2026-05-03 制定・絶対厳守)

**この worktree (`C:/dev/iMak_revise/`) は リバイスくん Claude 専用**。

- ✅ リバイスくん Claude: ここで作業
- ❌ 監視くん / 抽出くん / Catalog Claude / その他: **絶対 touch 禁止**
- ❌ 他 worktree への touch も禁止

詳細は `.PROJECT_LOCKED.md` 参照。グローバル `~/.claude/CLAUDE.md` の Worktree 分離
ルール厳守。

---

## 役割

| やる | やらない |
|---|---|
| eBay 出品の **価格 revise** (仕入価格変動追従) | 在庫切れ取下げ (= 監視くん) |
| eBay 出品の **タイトル / IS リフレッシュ** | URL 収集 (= 抽出くん) |
| **ScheduleTime 延長** (30日期限切れ防止) | 新規出品 (= 出品くん) |
| **SOLD 速度ベース値下げ** | 商品マスター集約 (= Catalog) |
| その他 eBay 出品メンテ系 revise | 仕入元在庫検知 (= 監視くん) |

---

## Phase 計画

| Phase | 機能 | 判定軸 | 状態 |
|---|---|---|---|
| **Phase 1** | 価格 revise | F 列 (出品時) vs N 列 (現在) の差分 | 計画中 |
| Phase 2 | タイトル / IS リフレッシュ | T 列 (出品日) からの経過日数 | 計画中 |
| Phase 3 | ScheduleTime 延長 | 出品日 + 30日 期限切れ前 | 計画中 |
| Phase 4 | SOLD 速度ベース値下げ | 30日経過で売れず → 自動 -5% | 計画中 |
| Phase 5+ | IS 補完 / Best Offer / 競合チェック | 各機能ごと別途 | 検討中 |

---

## データソース (前提)

スプシ列構成 (trabajo SheetRow.cs より):
- A: URL (仕入元)
- B: ItemID (eBay item_id)
- F: 出品時の価格 (固定、履歴)
- **N: 現在の仕入価格 (監視くん が毎 cycle 更新)** ← Phase 1 の主参照
- O: チェック日時
- T: 出品日 (Phase 2-4 の判定軸)
- U: itemid 入力日

監視くん が N 列を更新 (2026-05-03 Phase 10 で実装) してくれる前提。

---

## 連携プロジェクト

- **監視くん (iMakInventory)**: N 列 (現在価格) を毎 cycle 更新 → リバイスくん が読む
- **出品くん (iMakHQ)**: 新規出品時の USD 計算式は listing_common 等で共通
- **iMakeBayAPI**: eBay FileExchange CSV upload 共通基盤
- **抽出くん (iMakHarvest)**: URL 収集、リバイスくんとは無関係
- **Catalog (iMakCatalog)**: 商品マスター、リバイスくん は触らない

---

## eBay 価格再計算ロジック (Phase 1)

```
仕入価格 (円) → eBay USD price = (仕入価格 + 送料 + eBay fee + Payoneer fee) × profit_ratio
```

既存 listing_common の出品時計算式を **そのまま import** して使う (修正連鎖回避)。

---

## ディレクトリ構成 (想定)

```
iMakRevise/
├── CLAUDE.md
├── revise/
│   ├── price_revise.py        # Phase 1: 価格 revise
│   ├── title_refresh.py       # Phase 2 (将来)
│   ├── schedule_extend.py     # Phase 3 (将来)
│   └── slow_price_down.py     # Phase 4 (将来)
├── ebay_actions/              # iMakInventory から流用 or 共通化
│   ├── revise_csv_generator.py
│   └── sell_feed_uploader.py
├── run_revise.py              # エントリポイント
├── control_panel.py           # GUI 操作パネル
├── tools/                     # PowerShell タスクスケジューラ等
├── tests/
└── decision_log/
```

---

## NG (やってはいけないこと)

- 在庫切れ判定 / qty=0 化 (= 監視くんに任せる)
- URL 収集 / スプシ追加 (= 抽出くんに任せる)
- 新規出品 (= 出品くんに任せる)
- 修正連鎖 (memory: no_modification_chain.md 厳守)
- 既存稼働中スクリプトの直接修正 (流用は import で、改造は本元に依頼)

---

## セッション開始時の必須読み込み

- `C:\Users\imax2\.claude\CLAUDE.md` (グローバル / Worktree 分離ルール)
- `C:\dev\iMak_inventory\iMakInventory\CLAUDE.md` (連携先、N 列更新仕様)
- `C:\dev\iMak\iMakHQ\CLAUDE.md` (連携先、出品くん計算式)
- このファイル (`CLAUDE.md`)
