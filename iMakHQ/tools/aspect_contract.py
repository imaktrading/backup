# -*- coding: utf-8 -*-
"""aspect_contract — カタログの決定表を読んで、出したCSVが表どおりかを照合する。

役割 (2026-08-22 ユーザー確定):
    カタログ = 値を決める / 出品くん = 写すだけ / 監査くん = 表どおりか照合する

表の実体はカタログの worktree にあり、こちらからは読めないので、カタログが
生成のたびに共有領域へコピーを出している (書き手はカタログだけ、こちらは読むだけ):

    C:/dev/iMak_data/catalog/_contract_aspects.yaml

この module は **判断を持たない**。表に書いてあることだけを言う:
    - emit=false の項目に値が入っている        → 止める (ERROR)
    - emit=true の項目が空                     → カタログの空欄として数える (INFO)
    - 表に無い項目                             → 判定しない。カタログに投げる (INFO)
    - 値はあるが catalog の値と違う            → 止める (ERROR)  ← 2026-08-26 追加

表が読めない時は **何も言わない** (従来の検査だけが動く)。表の不在を根拠に
出品を止めると、カタログ側の一時的な不調で出品が止まるため。
"""
from __future__ import annotations

from pathlib import Path

CONTRACT_PATH = Path(r"C:/dev/iMak_data/catalog/_contract_aspects.yaml")

# 契約の対象は Item Specifics (C:*) だけ。価格・送料・画像等は表の管轄外。
_PREFIX = "C:"

# CSV の列名と表の項目名がずれているもの (列名は eBay の CSV 仕様側の綴り)。
_COL_TO_ASPECT = {
    "C:Attribute/MTG:Color": "Attribute/MTG:Color",
    "C:Attack/Power": "Attack/Power",
    "C:Defense/Toughness": "Defense/Toughness",
}


def load_contract(path=None):
    """表を読んで {項目名: row} を返す。読めなければ None (= 照合しない)。"""
    p = Path(path) if path else CONTRACT_PATH
    try:
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    rows = data.get("aspects") or []
    out = {}
    for r in rows:
        name = str(r.get("ebay_aspect") or "").strip()
        if name:
            out[name] = r
    return out or None


def aspect_of(col: str) -> str:
    """CSV の列名 → 表の項目名。"""
    if col in _COL_TO_ASPECT:
        return _COL_TO_ASPECT[col]
    return col[len(_PREFIX):] if col.startswith(_PREFIX) else col


def contract_findings(headers, row, contract=None):
    """1行を表と突き合わせて [(severity, msg)] を返す。純関数 (I/O は load_contract 側)。"""
    if contract is None:
        return []
    out = []
    for idx, col in enumerate(headers):
        if not col.startswith(_PREFIX):
            continue
        val = str(row[idx]).strip() if idx < len(row) and row[idx] is not None else ""
        aspect = aspect_of(col)
        rec = contract.get(aspect)
        if rec is None:
            out.append(("INFO", f"契約表に無い項目です (判定しません・カタログに投げる): {aspect}"))
            continue
        if not rec.get("emit"):
            if val:
                reason = str(rec.get("reason") or "").strip()
                out.append(("ERROR",
                            f"契約で出さないと決めた項目に値が入っています: {aspect}={val!r}"
                            + (f" — {reason}" if reason else "")))
            continue
        if not val:
            owner = str(rec.get("owner") or "")
            src = str(rec.get("source") or "")
            out.append(("INFO",
                        f"空欄です (契約では出す項目): {aspect} — 担当={owner} 出どころ={src}"))
    return out


# ---------------------------------------------------------------------------
# 「値はあるが catalog の値と違う」の照合 (2026-08-26)
#
# なぜ: 8/25 の入稿で 7セルの誤値 (C:Attack/Power に HP / C:Cost に Leader の LIFE /
#   C:Attribute に Vision の色) を通したのに、監査くんは「除外0 / カタログ依頼0 /
#   プログラム依頼0」だった。`contract_findings` は ①出さない項目に値 ②出す項目が空
#   ③表に無い項目 の3つしか見ておらず、**catalog の値と違う** を見ていなかった。
#   突合に要る canonical sidecar (`*.canonical.json`) は毎回出ている。
#
# ここでも判断は持たない。**expected は呼び出し側が catalog から作って渡す**
# (この module は表と2つの値を比べるだけ)。
# 依頼書: hq/requests/2026-08-25_act_code_proposals_tcg.md 提案5
# ---------------------------------------------------------------------------

def _values(v):
    """CSV の複数値 (`Promo|Alternative Art`) と catalog の list を同じ形にする。"""
    if v is None:
        return set()
    parts = ([str(x) for x in v] if isinstance(v, (list, tuple))
             else str(v).split("|"))
    return {p.strip() for p in parts if p.strip()}


def is_catalog_owned(col: str, contract) -> bool:
    """その列の値を catalog が決めるか (emit=true かつ source が specs.*)。"""
    rec = (contract or {}).get(aspect_of(col))
    if not rec or not rec.get("emit"):
        return False
    return str(rec.get("source") or "").startswith("specs.")


def catalog_mismatch_findings(headers, row, contract=None, expected=None):
    """CSV の値と catalog の値の差だけを返す [(severity, msg)] (純関数)。

    expected: {CSV列名: catalog 由来の値}。**引けなかった列は入れない** —
      入っていない列は判定しない (catalog を引けなかったことを「不一致」に倒さない)。
    """
    if contract is None or not expected:
        return []
    out = []
    for idx, col in enumerate(headers):
        if not col.startswith(_PREFIX) or col not in expected:
            continue
        if not is_catalog_owned(col, contract):
            continue
        got = _values(row[idx] if idx < len(row) else "")
        want = _values(expected[col])
        if got == want:
            continue
        aspect = aspect_of(col)
        if got and not want:
            out.append(("ERROR",
                        f"カタログが持たない値が入っています: {aspect}="
                        f"{'|'.join(sorted(got))!r} — カタログは空欄"))
        elif got:
            out.append(("ERROR",
                        f"カタログの値と違います: {aspect}={'|'.join(sorted(got))!r} "
                        f"— カタログ={'|'.join(sorted(want))!r}"))
        else:
            out.append(("ERROR",
                        f"カタログの値を写せていません: {aspect} が空欄 "
                        f"— カタログ={'|'.join(sorted(want))!r}"))
    return out
