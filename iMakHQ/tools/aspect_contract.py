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
