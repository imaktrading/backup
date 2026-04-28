# iMakCatalog — 全カテゴリ商品マスターDB

iMak Trading Japan 全プロジェクトから参照される共通の商品データベース。
各カテゴリ (TCG / G-SHOCK / リール / ポーター 等) の公式DB をローカル SQLite に集約し、
listing スクリプトが `iMakCatalog.api.lookup(...)` で参照する。

---

## 立ち上げ背景 (2026-04-26)

### 直接トリガー
- 2026-04-25: cert #143570665 で PSA "PRB02-005" を bandai_jp 名前検索で **ST16-005** に誤マッチ → SR を Common として CSV 出力寸前 → 人力検出で水際阻止
- 2026-04-26: Pokemon カード13件全滅 (FA/プレフィックス未対応 + 辞書漏れ)
- どちらも「ハードコード辞書 + 正規表現」で公式DB lookup している限界

### 構造的な根本原因
- 各 listing スクリプトが個別に Bandai/Pokemon 公式サイトをスクレイプ
- 同名キャラの別カード誤マッチ / 新セット未対応 / 新ラリティ未対応 が日常的に発生
- 修正は対症療法 (辞書追加 / 正規表現拡張) の繰り返し → 構造的負債

### 解決アプローチ
全カテゴリの商品マスター (id / 公式値 / eBay フィルタ値) を**事前に SQLite に集約**し、
listing スクリプトは `api.lookup(category, product_id)` で**ID完全一致 lookup のみ**にする。
ID不一致 = 物理 reject、フォールバック禁止。

---

## ディレクトリ構成

```
iMakCatalog/
├── CLAUDE.md              # このファイル (プロジェクト規約)
├── db/
│   ├── schema.sql         # SQLite スキーマ DDL
│   └── products.sqlite    # 商品マスター本体 (全カテゴリ統合)
├── scrapers/              # 各カテゴリの公式DBスクレイパー
│   ├── one_piece_tcg.py   # Phase 1
│   ├── pokemon_tcg.py     # Phase 2
│   ├── gundam_tcg.py      # Phase 2
│   ├── dragonball_scg.py  # Phase 2
│   ├── gshock.py          # Phase 3
│   ├── reel.py            # Phase 3
│   ├── porter.py          # Phase 4
│   ├── montbell.py        # Phase 4
│   └── ichibankuji.py     # Phase 4
├── api.py                 # 共通I/F (lookup / search / insert / bulk_update)
├── update.py              # 全カテゴリ差分更新コマンド (新弾発売時)
├── ebay_filter_map/       # eBay 公式フィルタ値マッピング (yaml)
│   ├── one_piece_set.yaml
│   ├── pokemon_set.yaml
│   └── ...
└── tests/                 # 各スクレイパー + api のユニットテスト
```

---

## SQLite スキーマ (products.sqlite)

```sql
-- 商品マスター本体
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,             -- 'one_piece_tcg' | 'pokemon_tcg' | 'gshock' | ...
    product_id TEXT NOT NULL,           -- カテゴリ内一意の ID (例: 'OP01-078', 'GA-2100-1A1')
    name TEXT NOT NULL,                 -- 表示名 (例: 'Boa Hancock', 'Casio G-SHOCK GA-2100-1A1')
    name_jp TEXT,                       -- 日本語名
    set_name TEXT,                      -- セット/シリーズ名 (eBay フィルタ値準拠)
    set_name_official TEXT,             -- 公式DB原文 (例: 'BOOSTER PACK -AWAKENED PULSE- [FB01]')
    specs TEXT NOT NULL,                -- JSON: rarity / cost / power / color / type / 等
    images TEXT,                        -- JSON: 公式画像URL配列
    source TEXT NOT NULL,               -- 'bandai_jp' | 'bandai_tcg_plus' | 'pokemon_official' | 'casio' | ...
    source_url TEXT,                    -- 取得元URL
    created_at TEXT NOT NULL,           -- ISO 8601
    updated_at TEXT NOT NULL,           -- ISO 8601
    UNIQUE(category, product_id)
);

CREATE INDEX idx_category ON products(category);
CREATE INDEX idx_product_id ON products(product_id);
CREATE INDEX idx_name ON products(name);

-- eBay フィルタ値マッピング (各カテゴリ × 各フィールドの公式値 → eBay 表示値)
CREATE TABLE ebay_filter_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,             -- 'one_piece_tcg' 等
    field TEXT NOT NULL,                -- 'set' | 'rarity' | 'card_type' | ...
    source_value TEXT NOT NULL,         -- 公式DB値 (例: 'BOOSTER PACK -AWAKENED PULSE- [FB01]')
    ebay_value TEXT NOT NULL,           -- eBay フィルタ表示値 (例: 'Awakened Pulse')
    UNIQUE(category, field, source_value)
);
```

---

## API (api.py) インターフェース

```python
from iMakCatalog import api

# 完全一致 lookup
result = api.lookup(category="one_piece_tcg", product_id="PRB02-005")
# Returns: dict | None
# {
#   "category": "one_piece_tcg",
#   "product_id": "PRB02-005",
#   "name": "Monkey D. Luffy",
#   "name_jp": "モンキー・D・ルフィ",
#   "set_name": "Premium Booster Vol.2",        # eBay フィルタ値
#   "set_name_official": "Premium Booster ...",  # 公式原文
#   "specs": {"rarity": "Super Rare", "cost": 4, "power": 5000, ...},
#   "images": ["https://...", ...],
#   "source": "bandai_jp",
#   "updated_at": "2026-04-26T13:14:00",
# }

# 名前検索 (フォールバック用、誤マッチリスクあるので慎重に)
candidates = api.search(category="one_piece_tcg", name="Monkey D. Luffy")
# Returns: list[dict]

# 単件登録/更新 (スクレイパーから)
api.upsert(category="...", product_id="...", **data)

# eBay フィルタ値変換
ebay_set = api.to_ebay_value(category="one_piece_tcg", field="set",
                             source_value="BOOSTER PACK -AWAKENED PULSE- [FB01]")
# → "Awakened Pulse"
```

---

## listing スクリプト連携の原則

```python
# psa_to_csv.py 等の listing script
from iMakCatalog import api

# 1) ID完全一致 lookup を最優先
result = api.lookup(category="one_piece_tcg", product_id=psa_card_number)

if result is None:
    # 2) DB未登録 → CSV から物理排除 (フォールバック禁止)
    print(f"⚠️ iMakCatalog 未登録: {psa_card_number} → Skip")
    return None

# 3) DB値をそのまま採用 (推測なし)
specs = result["specs"]
set_name = result["set_name"]  # eBay フィルタ値で取れる
```

**禁止事項**:
- ID不一致時の名前検索フォールバック (← 昨日の Luffy ST16/PRB02 事故の原因)
- 公式DB値を推測で改変
- listing script 内でハードコード辞書を使う (Canonical Map 等は ebay_filter_map に集約)

---

## Phase 計画

| Phase | 期間 | 内容 |
|---|---|---|
| **Phase 0** | 2026-04-26 | 箱の準備 (本ファイル + スキーマ + api.py スタブ) |
| **Phase 1** | 1週間 | One Piece TCG スクレイパー + iMakTCG.psa_to_csv 連携 |
| **Phase 2** | 2-3週間 | Pokemon / Gundam / Dragon Ball SCG 追加 (TCG 全網羅) |
| **Phase 3** | 2週間 | G-SHOCK + リール |
| **Phase 4** | 1-2週間 | ポーター / モンベル / 一番くじ |

各 Phase 完了時に該当 listing script を **iMakCatalog 経由に切替** + 旧スクレイパー (bandai_jp.py 等) を deprecation。

---

## 運用ルール

### 新弾発売時
1. 該当カテゴリのスクレイパーを実行 (`scrapers/one_piece_tcg.py --update`)
2. 差分のみ DB に追加
3. ebay_filter_map/{category}_set.yaml に新セット名を追記 (eBay 表示値確認後)

### スクレイピング頻度
- TCG: 月1回 + 新弾発売直後
- G-SHOCK / リール: 四半期1回
- ポーター / モンベル: 半年1回 (商品入替少ない)

### バックアップ
- products.sqlite は Git 管理 (容量数十〜数百MB、Git LFS 検討)
- スキーマ変更時は migrations/ ディレクトリで版管理

---

## 横断的気づき・連携プロジェクト

- **iMakHQ**: プロジェクト一覧に iMakCatalog 追加済 (2026-04-26)
- **iMakeBayAPI**: 出力側 (eBay API)、こちらは入力側 (公式DB集約)、用途が独立
- **iMakAudit**: iMakCatalog の DB 整合性も監査対象に追加検討

## 関連メモリ

- `psa_bandai_brand_divergence.md` — プロモ二重国籍の許容パターン (Brand 文字列のみ判定の限界)
- `dual_gate_disagreement.md` — psa_to_csv ↔ check_csv の二重基準問題
- `gundam_bandai_tcg_plus_reliability.md` — fetch_card 誤ヒット問題
- `completion_must_be_proven.md` — "完了" 宣言は実走証跡で実証
