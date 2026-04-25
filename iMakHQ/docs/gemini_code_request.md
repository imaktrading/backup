# Gemini向けコード作成依頼

以下の指示に従って、Python コードを書いてください。
出力形式: ファイルパス + 完全なコード（コピペで動く形）。

---

## 背景

iMak Trading Japan の eBay listing system の再現性を 100% にするための実装依頼。
仕様書は別添（listing_system_spec.md v3）に従う。

レビュー結果に基づき、以下の Phase 1 を実装してほしい:

1. **listing_common.py に `CONDITION_MASTER` 辞書 + 補助関数追加** (項目⑥)
2. **`audit_csv_row()` の強化** (項目③)
3. **既存 listing_common.py の他関数群と整合させる**

---

## 既存 listing_common.py の現状

ファイルパス: `iMakeBayAPI/listing_common.py` (一部抜粋)

```python
SKU_PREFIX_BY_CATEGORY = {
    "porter": "PORT", "reel": "REEL", "tomica": "TOMI",
    "ichibankuji": "KUJI", "tshirt": "TSHT", "montbell": "MONT",
    "gshock": "GSHK", "tcg": "TCG",
}

def extract_sku_from_url(url: str, category: str = None) -> str:
    """URL末尾12文字 SKU化"""
    ...

def is_new_condition(condition_jp: str) -> bool:
    """スプシE列の状態値から新品判定"""
    ...

def determine_condition_id(condition_id_sheet: str, condition_jp: str, cfg_default: int) -> tuple[int, bool]:
    """L列(ConditionID)優先 → E列(状態)fallback → cfg値"""
    ...

def fetch_amazon_title(url: str) -> str:
    """Amazon URLから variation 正式タイトル取得"""
    ...

def enforce_title_coherence(title: str, is_new: bool, max_chars: int = 80) -> str:
    """ConditionID と Title 末尾の整合保証"""
    ...

def pad_title_to_target(title: str, item_specifics: dict, category: str = None,
                        target_min: int = 70, max_chars: int = 80) -> str:
    """Title 70字以下なら自動パディング"""
    ...

def normalize_title(title: str, is_new: bool, item_specifics: dict, category: str = None,
                    target_min: int = 70, max_chars: int = 80) -> str:
    """coherence + padding 統合"""
    ...

def audit_csv_row(row_data: dict, category: str = None) -> list:
    """CSV出力前の最終lint。違反リスト返却。
    Returns: [(field, issue, severity), ...] severity: 'error' or 'warning'
    """
    violations = []
    title = row_data.get("*Title", "")
    cid = str(row_data.get("ConditionID", ""))
    cd = row_data.get("ConditionDescription", "")

    # 既存ロジック: タイトル長、ConditionID整合、必須項目チェック等

    return violations
```

---

## 依頼内容

### A. `CONDITION_MASTER` 辞書 (新規追加)

`listing_common.py` の冒頭付近 (SKU_PREFIX_BY_CATEGORY の近く) に追加。

eBay の ConditionID と、それに対応する以下情報を1箇所に集約:

| ConditionID | name | title_marker (Title末尾候補) | description_default (Description定型文) | mercari_states (E列状態でマップ) |
|---|---|---|---|---|
| 1000 | Brand New | "Brand New Japan" / "Brand New" / "New" | "Brand new, unused condition. Comes with original packaging when applicable." | ["新品", "新品、未使用", "未使用"] |
| 1500 | New (Other) | "New" | (空欄、Claudeまたは手動) | (なし、明示指定のみ) |
| 1750 | New with Defects | "New" | (Claude生成) | (なし) |
| 2000 | Manufacturer Refurbished | "Refurbished" | (Claude生成) | (なし) |
| 2500 | Seller Refurbished | "Seller Refurbished" | (Claude生成) | (なし) |
| 3000 | Pre-owned | "Pre-owned Japan" / "Pre-owned" | (動的、メルカリ状態の英訳マッピング) | ["未使用に近い", "目立った傷や汚れなし", "やや傷や汚れあり", "傷や汚れあり", "全体的に状態が悪い"] |
| 7000 | For parts or not working | "For Parts" | (Claude生成) | (なし) |

形式は dict of dict で:
```python
CONDITION_MASTER = {
    1000: {
        "name": "Brand New",
        "title_markers": ["Brand New Japan", "Brand New", "New Japan", "New"],
        "description_default": "Brand new, unused condition. Comes with original packaging when applicable.",
        "mercari_states": ["新品", "新品、未使用", "未使用"],
    },
    ...
}
```

### B. 補助関数 (新規追加)

```python
def get_default_condition_description(condition_id: int, mercari_state: str = "") -> str:
    """ConditionID + メルカリ状態 から ConditionDescription を deterministic 生成。
    - 1000 (新品) → CONDITION_MASTER[1000]["description_default"] 固定
    - 3000 (中古) → メルカリ状態に対応する英訳テンプレ + "Please review all photos..."
    - その他 → 空文字 (Claude or 手動補完)
    """
    pass


def get_title_marker_for_condition(condition_id: int, available_chars: int) -> str:
    """空き文字数に応じた最適な title_marker を CONDITION_MASTER から選ぶ。
    例: 残り20字なら "Brand New Japan"、残り10字なら "Brand New"、5字なら "New"
    """
    pass


def detect_condition_id_from_state(mercari_state: str) -> int | None:
    """メルカリ状態文字列から ConditionID を逆引き（CONDITION_MASTER の mercari_states を走査）"""
    pass
```

### C. `enforce_title_coherence()` の改修

既存の関数を `CONDITION_MASTER` を参照する形に書き換え。
- 新品/中古の hard-coded marker を `CONDITION_MASTER[condition_id]["title_markers"]` から動的取得
- ConditionID = 1000 だけでなく、1500/2000/3000 等にも対応

### D. `audit_csv_row()` の強化

既存の audit_csv_row に以下のチェック追加:

1. **ConditionID と ConditionDescription の整合**:
   - ConditionID = 1000 で ConditionDescription が CONDITION_MASTER[1000]["description_default"] と異なる → warning
   - ConditionID = 3000 で ConditionDescription が空欄 → error (既存)

2. **Title marker の存在確認**:
   - ConditionID に対応する title_markers のいずれかが Title に含まれること
   - 含まれない → error

3. **Mercari状態と ConditionID の逆引き整合**:
   - 渡された condition_jp (mercari_state) が CONDITION_MASTER[condition_id]["mercari_states"] に含まれない → warning
   - "新品" なのに ConditionID=3000 等の不整合検知

シグネチャ拡張:
```python
def audit_csv_row(row_data: dict, category: str = None,
                  mercari_state: str = "") -> list:
    ...
```

### E. テストコード

`if __name__ == "__main__":` ブロックで以下smoke testを実装:

```python
# CONDITION_MASTER 検証
assert 1000 in CONDITION_MASTER
assert "新品" in CONDITION_MASTER[1000]["mercari_states"]

# detect_condition_id_from_state
assert detect_condition_id_from_state("新品") == 1000
assert detect_condition_id_from_state("やや傷や汚れあり") == 3000
assert detect_condition_id_from_state("不明") is None

# get_default_condition_description
assert "Brand new" in get_default_condition_description(1000)
desc_used = get_default_condition_description(3000, "傷や汚れあり")
assert "wear" in desc_used.lower() or "scratches" in desc_used.lower()

# audit_csv_row 強化版
row_new = {
    "*Title": "Daiwa Brand New Japan",
    "*Category": 261030, "*StartPrice": 100,
    "ConditionID": 1000, "ConditionDescription": CONDITION_MASTER[1000]["description_default"],
    "C:Brand": "Daiwa",
}
v = audit_csv_row(row_new, category="reel", mercari_state="新品")
assert all(s == "warning" for _, _, s in v) or len(v) == 0  # error なし

row_mismatch = {
    "*Title": "Daiwa Pre-owned Japan",  # title は中古
    "*Category": 261030, "*StartPrice": 100,
    "ConditionID": 1000,  # でも ID は新品 → error
    "C:Brand": "Daiwa",
}
v = audit_csv_row(row_mismatch, category="reel", mercari_state="新品")
assert any(s == "error" for _, _, s in v)

print("All smoke tests passed.")
```

---

## 出力フォーマット

以下を返してください:

1. 完全な listing_common.py の追加コード (CONDITION_MASTER + 4関数 + audit強化版)
2. 既存関数で書き換える必要があるもの (enforce_title_coherence等) の差分
3. smoke test の実行結果想定
