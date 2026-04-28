"""spec_normalizer - Mercari listing の Item Specifics 後処理 (独立モジュール).

設計原則 (修正連鎖を生まないため):
  - 既存モジュール (mercari_to_ebay_csv / listing_common 等) を一切修正しない
  - mercari_to_ebay_csv は item_specifics dict を 1 関数通すだけ (try/except 付)
  - 失敗時は元 specs 返却 (フォールバック耐性)

設計思想:
  Claude Vision の判断は LLM 非決定論 (temperature=0 でも完全決定論にならない).
  ブランド事実 (Porter=Japan 製) のような **動かせない事実** を Vision に推測させると、
  毎回回答ブレ → CSV 品質バラつき (Origin が 'Japan'/'Does not apply'/空 で混在).

  → 「決定論的に書ける情報は Vision に任せず固定値で上書き」を本モジュールで実施.

  対象:
    1. Brand-default Country fields (Porter/Yoshida → Japan 等)
    2. 寸法表記の dual format (`39.5 cm` → `15.5 in (39.5 cm)`)

  範囲外 (= 触らない):
    - Vision の責務である「画像からの読取」値 (色・素材・サイズ表示等)
    - Brand 不明 / 上記マップ外のブランド (元値維持)

使用例:
    from spec_normalizer import normalize_specs
    item_specifics = normalize_specs(item_specifics)
"""
from __future__ import annotations

import re
from typing import Optional


# ============================================================================
# Brand 事実マップ (失敗ナレッジ蓄積、新ブランド都度追加)
# キーはブランド名小文字部分一致、値は確定 Country
# ============================================================================
_MADE_IN_JAPAN_BRANDS = [
    "porter",        # 吉田カバン PORTER
    "yoshida",       # 吉田カバン
    "head porter",   # ヘッドポーター
    "montbell",      # モンベル
    "snow peak",     # スノーピーク
    "uniqlo",        # ユニクロ
    "muji",          # 無印良品
    "g-shock",       # G-SHOCK (CASIO)
    "casio",         # CASIO
    "tomica",        # タカラトミー (一部、要確認)
    "takara tomy",
    # 必要に応じて追加 (新ケースで「○○ なのに Japan じゃない」と気付いたら追記)
]


# 寸法フィールド (CSV 列名 / item_specifics dict キー)
_DIMENSION_KEYS = [
    "Bag Width", "Bag Height", "Bag Depth",
    "Item Width", "Item Height", "Item Length", "Item Depth",
    "Width", "Height", "Depth", "Length",
]

# eBay Item Specifics フィールドの絶対文字数制限
# (失敗ナレッジ: 2026-04-28 Porter 11件 全 Features 100字超で eBay 入稿 Failure)
_EBAY_FIELD_MAX_LEN = {
    "Features": 65,        # eBay 厳格、超過すると入稿時 Failure
    "Item Length": 65,
    # 必要に応じて追加 (Subtitle 55, Title 80 等は別レイヤーで扱う)
}


# ============================================================================
# 公開 API: Title Brand prefix 統一
# (注: 関数名は 'enforce_brand_prefix'. listing_common.normalize_title との
#  衝突を避けるため別名にしている.)
# ============================================================================
def enforce_brand_prefix(title: str, brand_hint: str = "", target_max: int = 80) -> str:
    """eBay Title の Brand prefix を統一 (Vision の非決定論ブレ救済).

    対象:
      - Porter (吉田カバン): `PORTER` 単独冒頭 → `YOSHIDA PORTER` 強制 prepend
      - HEAD PORTER (別ブランド): 触らない
      - 既に `YOSHIDA PORTER` の場合: 触らない (冪等)

    根拠 (mercari_to_ebay_csv.py L302-311 のルール文より):
      "TOPセラー慣習: 'YOSHIDA' 冠（ブランド明確化）"
      ただしルール文は OR 許容なので Vision がランダム選択する → ブレ.
      ここで強制統一 (本体プロンプト L302-306 を変更せず別ルーチンで吸収).

    長さ制約:
      `YOSHIDA ` (8字) prepend で 80字超なら、`Pre-owned Japan` → `Used Japan` (-5字) で再試行.
      それでも超える場合は諦めて元 title 返却 (中途半端な切詰め禁止).

    Args:
        title:       元 title (Vision 由来)
        brand_hint:  args.sheet 等 (porter なら強制発動)
        target_max:  80字制限 (eBay Title 上限)

    Returns:
        正規化済 title (失敗時は元値)
    """
    if not title:
        return title

    try:
        title_upper = title.upper()

        # HEAD PORTER は別ブランド、触らない
        if "HEAD PORTER" in title_upper or "HEADPORTER" in title_upper:
            return title

        # 既に YOSHIDA PORTER なら冪等
        if "YOSHIDA PORTER" in title_upper:
            return title

        # PORTER で冒頭一致しなければ対象外 (brand_hint=porter でも、まず title が PORTER 形式かチェック)
        if not re.match(r"^\s*PORTER\b", title, re.IGNORECASE):
            return title

        # YOSHIDA を prepend
        candidate = "YOSHIDA " + title.lstrip()
        if len(candidate) <= target_max:
            return candidate

        # 80字超 → 'Pre-owned Japan' を 'Used Japan' に短縮 (TOPセラー慣習許容)
        candidate2 = candidate.replace("Pre-owned Japan", "Used Japan", 1)
        if len(candidate2) <= target_max:
            return candidate2

        # それでも超 → 諦めて元 title 維持 (破損より良い)
        print(f"    ⚠️ enforce_brand_prefix: YOSHIDA 追加で 80字超、元 title 維持 (len={len(title)})")
        return title

    except Exception as e:
        print(f"    ⚠️ enforce_brand_prefix 例外、元値採用: {type(e).__name__}: {e}")
        return title


# ============================================================================
# 公開 API: Item Specifics 正規化
# ============================================================================
def normalize_specs(
    specs: dict,
    brand_hint: str = "",
) -> dict:
    """item_specifics dict を後処理.

    Args:
        specs:      Vision 由来の item_specifics (改変しない、コピー返却)
        brand_hint: Brand キー外部指定 (sheet_registry 等から). 通常は specs["Brand"] で OK.

    Returns:
        正規化済 dict (浅いコピー)
    """
    if not isinstance(specs, dict):
        return specs

    try:
        out = dict(specs)

        # 1. Brand-default Country 強制
        brand_text = _collect_brand_text(out, brand_hint)
        if _is_made_in_japan(brand_text):
            out["Country of Origin"] = "Japan"
            out["Country/Region of Manufacture"] = "Japan"

        # 2. 寸法 dual format
        for key in _DIMENSION_KEYS:
            if key in out:
                old = out[key]
                new_v = _to_dual_format(old)
                if new_v != old:
                    out[key] = new_v

        # 3. eBay 絶対文字数制限の切詰め (Features 65字 等)
        out = _truncate_overlong_fields(out)

        return out

    except Exception as e:
        print(f"    ⚠️ spec_normalizer 例外、元 specs 採用: {type(e).__name__}: {e}")
        return specs


# ============================================================================
# 内部処理
# ============================================================================
def _collect_brand_text(specs: dict, brand_hint: str) -> str:
    """specs / brand_hint から ブランド判定文字列を組立 (小文字)."""
    parts = [
        str(specs.get("Brand", "") or ""),
        str(specs.get("Manufacturer", "") or ""),
        str(brand_hint or ""),
    ]
    return " ".join(parts).lower()


def _is_made_in_japan(brand_text: str) -> bool:
    """ブランドテキストに JP 確定キーワードを含むか."""
    if not brand_text:
        return False
    return any(kw in brand_text for kw in _MADE_IN_JAPAN_BRANDS)


def _truncate_overlong_fields(specs: dict) -> dict:
    """eBay の絶対文字数制限超過フィールドを切詰め.

    Features 65字 ルール (Porter 11件 入稿全件 Failure 経験から).
    カンマ区切り値はトークン単位で先頭から詰めて切る (中途半端な切断回避).
    トークン区切りでない単一値は単純 substring.
    """
    out = dict(specs)
    for key, max_len in _EBAY_FIELD_MAX_LEN.items():
        v = str(out.get(key, "") or "")
        if not v or len(v) <= max_len:
            continue
        # カンマ区切り → トークン単位で詰める
        if "," in v:
            parts = [p.strip() for p in v.split(",") if p.strip()]
            kept = []
            total = 0
            for p in parts:
                sep = 2 if kept else 0  # ", "
                if total + sep + len(p) <= max_len:
                    kept.append(p)
                    total += sep + len(p)
                else:
                    break
            new_v = ", ".join(kept)
        else:
            # 単一値 → 単純切詰め (空白境界優先)
            cut = v[:max_len].rstrip()
            # 末尾を語境界で揃える
            m = re.match(r"^(.*)\s+\S+$", cut)
            new_v = m.group(1) if m else cut
        if new_v != v:
            out[key] = new_v
            print(f"    🪚 spec_normalizer: '{key}' 切詰め "
                  f"({len(v)}字 → {len(new_v)}字、eBay 上限 {max_len}字)")
    return out


def _to_dual_format(value) -> str:
    """寸法値を `XX in (XX cm)` dual 形式に正規化.

    対応パターン:
      `39.5 cm`        → `15.5 in (39.5 cm)`            (cm 単独 → dual 化)
      `15.5 in (39.5 cm)` → 触らない (冪等、既に dual)
      `15 in`          → 触らない (in 単独、cm 換算は誤差大なので非対応)
      `40` (裸数値、>=6) → `15.7 in (40 cm)`            (cm 推定 → dual 化)
      `4` (裸数値、<6)   → 触らない (曖昧、in/cm 判別不能)
      ``空文字 / None  → 触らない

    cm 推定の根拠:
      バッグ寸法で 6 cm は明らかに小さい (Porter Tanker 最小 Depth でも 7 cm)。
      逆に 6 in (= 15 cm) はバッグ Width で十分あり得る → 6+ なら cm 確定.
      Vision が unit 省略するケース (実走で観測) を救済.
    """
    if value is None:
        return value
    s = str(value).strip()
    if not s:
        return s
    # case 1: 既に in 表記 (in / inch / ") なら触らない (dual 含む)
    if re.search(r'(in\b|inches\b|inch\b|")', s, re.IGNORECASE):
        return s
    # case 2: `XX cm` or `XX.X cm` (前後空白許容) → dual 化
    m_cm = re.match(r"^\s*([\d.]+)\s*cm\s*$", s, re.IGNORECASE)
    if m_cm:
        try:
            cm = float(m_cm.group(1))
            inches = round(cm / 2.54, 1)
            return f"{inches} in ({cm} cm)"
        except ValueError:
            return s
    # case 3: 裸数値 (単位無し) で 6+ → cm 確定として dual 化
    m_bare = re.match(r"^\s*([\d.]+)\s*$", s)
    if m_bare:
        try:
            num = float(m_bare.group(1))
            if num >= 6:
                inches = round(num / 2.54, 1)
                return f"{inches} in ({num} cm)"
        except ValueError:
            pass
        return s  # <6 の裸数値は曖昧なので触らない (in/cm 判別不能)
    # case 4: その他混合形式は触らない (誤変換防止)
    return s


# ============================================================================
# CLI (動作確認用)
# ============================================================================
if __name__ == "__main__":
    # === enforce_brand_prefix test ===
    print("=== enforce_brand_prefix test ===")
    title_samples = [
        ("PORTER Tanker 2Way Briefcase Shoulder Bag Black Nylon Medium Pre-owned Japan",
         "YOSHIDA PORTER Tanker 2Way Briefcase Shoulder Bag Black Nylon Medium Used Japan"),  # 80字超 → 短縮
        ("PORTER Tanker Helmet Bag Black Nylon Pre-owned Japan",
         "YOSHIDA PORTER Tanker Helmet Bag Black Nylon Pre-owned Japan"),  # 通常 prepend
        ("YOSHIDA PORTER Tanker Briefcase Black Nylon Large Pre-owned Japan",
         "YOSHIDA PORTER Tanker Briefcase Black Nylon Large Pre-owned Japan"),  # 既 dual、冪等
        ("HEAD PORTER Brownie 2Way Briefcase Brown Nylon Pre-owned Japan",
         "HEAD PORTER Brownie 2Way Briefcase Brown Nylon Pre-owned Japan"),  # HEAD PORTER は触らない
        ("Tomica No.47 Blue Nissan Vintage Japan",
         "Tomica No.47 Blue Nissan Vintage Japan"),  # PORTER じゃない、触らない
    ]
    for raw, expected in title_samples:
        out = enforce_brand_prefix(raw)
        ok = "✓" if out == expected else "✗"
        print(f"  {ok}  raw={raw!r}")
        print(f"      out={out!r} ({len(out)}字)")
        print(f"      exp={expected!r}")
    print()
    print("=== normalize_specs test ===")
    samples = [
        # Porter (Yoshida) - Country 強制 + dual format
        {
            "Brand": "Porter",
            "Country of Origin": "Does not apply",
            "Country/Region of Manufacture": "",
            "Bag Width": "39.5 cm",
            "Bag Height": "28 cm",
            "Bag Depth": "8 cm",
            "Color": "Brown",
        },
        # Head Porter (裸数値、>=6 → cm 推定 dual 化)
        {
            "Brand": "Head Porter",
            "Country of Origin": "",
            "Bag Width": "40",   # 裸数値 → cm 推定 → dual 化
            "Bag Height": "29",  # 同上
            "Bag Depth": "7",    # 7 >= 6 なので dual 化
        },
        # 裸数値 <6 (曖昧) → 触らない
        {
            "Brand": "Porter",
            "Bag Width": "5",  # <6 in/cm 判別不能 → 触らない
        },
        # Montbell
        {
            "Brand": "Montbell",
            "Country of Origin": "Does not apply",
            "Item Width": "30 cm",
        },
        # 不明ブランド - 触らない
        {
            "Brand": "UnknownBrand",
            "Country of Origin": "Does not apply",
            "Bag Width": "20 cm",
        },
        # 既に in 表記 - 触らない
        {
            "Brand": "Porter",
            "Bag Width": "15.5 in (39.5 cm)",
        },
    ]
    print("=== CLI test ===")
    for i, s in enumerate(samples, 1):
        print(f"--- Sample {i} ---")
        print(f"  IN : {s}")
        out = normalize_specs(s)
        print(f"  OUT: {out}")
        print()
