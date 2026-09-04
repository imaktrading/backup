# -*- coding: utf-8 -*-
"""PORTER の Item Specifics を決定的に整える (2026-09-04 新設)。

## なぜ
ポーターは1点ものでカタログ (products.sqlite) に無く、値を突き合わせる相手が居ない。
そのため Claude が写真から毎回「書けそうな物」を足し引きし、**行ごとに列が変わって**いた。
2026-09-04 の15件の実測:

    C:Series       1/15   ← プロンプトは「Series 必須」と言っているのに落ちている
    C:MPN          1/15   ← 中古1点ものに型番 = 同型番の新品とまとめられる (**間違い**)
    C:Type         1/15   ← バッグでは C:Style が正。書くと重複
    C:Description  1/15   ← eBay にこの項目は無い
    C:Size         Small(幅15.7in) > Medium(幅14.6in) と逆転 (**間違い**)

**決まっている物を毎回考えさせない。** ここで機械的に決める。

★触らないもの (2026-09-04 に「おかしい」と誤って判断したので明記):
  - `Department` の Men / Unisex Adults の割れ … プロンプトの規則どおり
    (基本 Men、ハンドバッグ系のみ Unisex。eBay 実数 Men 1,826 / Unisex 1,321)
  - 寸法の `15.7 in (40.0 cm)` 形式 … 意図した形で、eBay も受けている
    (live 358640735459 に同じ形が入っているのを実機確認)

規約の本体は skill `porter-listing`。
"""
import re

# 出さないと決めた項目 (2026-09-04 ユーザー確定)
DROP = (
    "Description",                    # eBay にこの項目が無い (説明文は *Description 列)
    "MPN",                            # 中古1点ものに型番を付けない
    "Type",                           # バッグでは Style が正。書くと重複
    "Country/Region of Manufacture",  # Country of Origin と重複。産地はそちらだけ
)

# タイトルから拾うシリーズ名 (プロンプトの「Series 必須」一覧)
SERIES = ("Tanker", "Heat", "Smoky", "Lift", "Current", "Force", "Filter",
          "Flex", "Union", "Free Style", "Howl", "Drive", "Yoshida")

# 幅(inch)で決めるサイズ。実寸が在るのに写真で判断させない
SIZE_BY_WIDTH_IN = ((9.9, "Small"), (15.0, "Medium"), (19.7, "Large"))
SIZE_MAX = "Extra Large"


def series_from_title(title):
    """タイトルからシリーズ名を拾う (純関数)。見つからなければ ""。"""
    t = title or ""
    for s in SERIES:
        if re.search(r"\b%s\b" % re.escape(s), t, re.I):
            return s
    return ""


def width_inches(value):
    """'15.7 in (40.0 cm)' / '15.7 in' → 15.7 (純関数)。読めなければ None。"""
    m = re.search(r"([\d.]+)\s*in", str(value or ""), re.I)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def size_from_width(width_in):
    """幅(inch) → Small/Medium/Large/Extra Large (純関数)。不明は ""。"""
    if width_in is None:
        return ""
    for upper, name in SIZE_BY_WIDTH_IN:
        if width_in <= upper:
            return name
    return SIZE_MAX


def finalize(specs, title):
    """Porter の Item Specifics を決定的に整える (純関数)。

    ① 出さないと決めた項目を落とす
    ② Series をタイトルから入れる (既に入っていれば触らない)
    ③ Size を実寸(幅)から決める。実寸が無い時は元の値を残す (推測を消さない)
    ④ 寸法の 'Does not apply' は空にする (寸法欄に入れる値ではない)
    """
    out = {k: v for k, v in (specs or {}).items() if k not in DROP}

    if not str(out.get("Series", "")).strip():
        s = series_from_title(title)
        if s:
            out["Series"] = s

    w = width_inches(out.get("Bag Width"))
    sz = size_from_width(w)
    if sz:
        out["Size"] = sz

    for k in ("Bag Width", "Bag Height", "Bag Depth"):
        if str(out.get(k, "")).strip().lower() in ("does not apply", "n/a", "-"):
            out[k] = ""
    return out
