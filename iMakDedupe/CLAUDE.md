# iMakDedupe — 重複くん (dedupe-checker)

## 🛡️ Worktree 分離ルール (2026-05-26 制定・絶対厳守)

**この worktree (`C:/dev/iMak_dedupe/`) は重複くん Claude 専用**。

- ✅ 重複くん Claude: ここで作業
- ❌ HQ / Catalog / Inventory / Harvest / Revise / Advisor: **絶対 touch 禁止**
- ❌ 他 worktree (`C:/dev/iMak/` `C:/dev/iMak_catalog/` `C:/dev/iMak_inventory/`
  `C:/dev/iMak_harvest/` `C:/dev/iMak_revise/`) への touch も禁止 (= 読込のみ可)

詳細は `.PROJECT_LOCKED.md` 参照。グローバル `~/.claude/CLAUDE.md` の Worktree 分離
ルールも厳守。違反は他プロジェクトの自動運用を破壊する致命行為。

### branch 切替前の uncommitted 確認 (絶対厳守)

1. `git status` で uncommitted ゼロ確認
2. uncommitted があれば必ず先に commit or stash
3. 確認後にのみ `git checkout <branch>` 実行

このルールは 過去 3 回の同型事故 (workspace JSON 消失 / 並列セッション編集消失) の
根本対策。

---

## 役割

iMak Trading Japan の **出品候補 ↔ 既存出品 重複突合** 専属 worker。

| やる | やらない |
|---|---|
| 中間スプシ (= 抽出くん書込) と既存 HIGH/LOW/公式 スプシの突合 | URL 収集 (抽出くん責務) |
| カテゴリ別 regex で card_id / 型番抽出 | 在庫監視 (監視くん責務) |
| 中間スプシに「既存出品 chk」 列追加 + flag マーク | 出品 CSV 生成 (listing project 責務) |
| fail-closed 突合 (= ambiguous なら「不明」) | eBay 取り下げ (監視くん責務) |
| カテゴリ別 regex pattern 管理 | リバイス (リバイスくん責務) |

### スコープ外 (= 既存 worker touch NG)

抽出くん / 監視くん / 出品くん / Catalog / リバイスくん の code 編集は禁止。
読込のみ可 (= 既存スプシ ID は global config 経由で参照)。

---

## ディレクトリ構成

```
iMakDedupe/
├── CLAUDE.md                       # このファイル
├── .PROJECT_LOCKED.md              # 他 worktree からの touch 禁止 明示
├── dedupe/
│   ├── __init__.py
│   ├── checker.py                  # main logic
│   ├── sheet_io.py                 # 中間スプシ + 既存スプシ読書 helper
│   └── extractors/
│       ├── __init__.py
│       ├── tcg.py                  # TCG (One Piece / Pokemon / Yu-Gi-Oh!) regex
│       ├── gshock.py               # G-shock 型番 regex
│       └── url.py                  # mercari URL regex
├── tests/
│   ├── test_extractors_tcg.py
│   ├── test_extractors_gshock.py
│   ├── test_extractors_url.py
│   └── test_checker.py
├── pytest.ini
├── requirements.txt
└── .gitignore
```

---

## Phase 計画

| Phase | 内容 |
|---|---|
| **0** | worker skeleton 構築 (= 本依頼書、 完了報告先 = `C:/dev/iMak_data/dedupe/requests/`) |
| **1** | extractor + checker 本実装、 中間スプシ + HIGH/LOW/公式 突合 (CLI のみ) |
| **2** | GUI 統合 (= 出品くん panel に「重複 check」 button、 出品くん別依頼) |
| **3** | 抽出くん との 連携自動化 (= scrape 後に自動 trigger) |
| **4** | 既存出品スプシの product_id 列を 監視くんが自動書込 (= 監視くん別依頼) |

---

## 「出品の正確性」 原則 (= 重複くん 必須遵守)

グローバル CLAUDE.md の大前提を 重複くんでも厳守:

- **fail-closed**: regex hit せず card_id 取れない row は「不明」、 user 目視判断
- **ambiguous なら「不明」**: 推測で「重複」 マーク NG
- **物理除外しない**: 中間スプシ row を削除しない (= flag マークのみ)、 user 目視判断余地残す
- 「網羅性が低い」「重複検出漏れ」は受け入れる、 誤判定より遥かに低リスク

---

## 依頼書受領窓口

- 共有 dir: `C:/dev/iMak_data/dedupe/requests/`
- 新規 `.md` (= 未処理依頼) があれば内容を読んで対応判断
- 完了したら `_processed.md` リネーム or 同 dir に短いレポート (`*_response.md`) 追加
- `*_processed.md` / `*_response.md` は削除しない (= 対応済証跡)

---

## セッション開始時の必須読み込み

重複くんは他プロジェクトと連携するため、開始時に以下を読む:

- `C:/Users/imax2/.claude/CLAUDE.md` (グローバル / 全プロジェクト共通ルール)
- `C:/dev/iMak/iMakHQ/CLAUDE.md` (司令塔)
- `C:/dev/iMak_harvest/iMakHarvest/CLAUDE.md` (中間スプシ書込元 = 抽出くん)
- `C:/dev/iMak_inventory/iMakInventory/CLAUDE.md` (既存出品スプシ書込元 = 監視くん)
- `C:/dev/iMak_catalog/iMakCatalog/CLAUDE.md` (catalog 仕様)
- このファイル (`CLAUDE.md`)
- `C:/dev/iMak_dedupe/iMakDedupe/.PROJECT_LOCKED.md`

---

## 入力 / 出力 (Phase 1)

### 入力

- **中間スプシ ID**: `1hTdFVGkni4Ih4kZGsBgiCKxpTlOeoO_wJdk8Ek5n41Q` (= 抽出くん書込済)
- **既存 HIGH/LOW/公式 スプシ**: ID は HQ memory or sheet IDs config 参照

### 処理

1. 中間スプシの `seller_<id>` タブから row 取得 (= title / URL / 抽出済 card_id 等)
2. 各 row に対して以下 突合:
   - URL 一致 (= mercari URL 完全一致) → "重複 URL"
   - card_id 一致 (= TCG card_id 完全一致) → "重複 card_id"
   - 型番一致 (= G-shock 型番完全一致) → "重複 型番"
3. 既存 HIGH/LOW/公式 スプシ title 列から regex で card_id / 型番抽出 → 中間スプシ
   抽出済値 と diff

### 出力

中間スプシ各 row に **「既存出品 chk」 列追加** + flag:

- `重複 URL` / `重複 card_id` / `重複 型番` / `(空)` (= 新規) / `不明` (= regex hit せず)
- 物理除外しない (= 出品の正確性 原則準拠)

---

## カテゴリ別 regex (= Phase 1 initial 実装)

| カテゴリ | regex pattern | 例 |
|---|---|---|
| TCG (One Piece) | `#((?:OP\|ST\|EB\|PRB)\d+-\d+\|P-\d+)` | `#OP01-016`, `#P-115` |
| TCG (Pokemon) | `(?:#\|SV\|SM)\d+[-\s]*\d+` | `SV1a-001` |
| TCG (Yu-Gi-Oh!) | `\b(?:[A-Z]{2,5})-(?:JP\|EN)?\d+\b` | `LB-01-J001` |
| G-shock | `\b(?:GA\|GW\|DW\|GST\|GMW\|GBA\|MTG\|GMA)-[A-Z0-9-]+\b` | `DW-5600-1JF` |
| URL | `(/item/m\d+\|/shops/product/[\w-]+)` | mercari URL |

extractor は **categorize 可能なものだけ抽出**。fail-closed = hit なし → 「不明」。
