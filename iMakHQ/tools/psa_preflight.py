#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSA TCG 出品 pre-flight 監査 (2026-06-11).

出品中に「catalog 未登録」が発覚するのを防ぐため、出品前に cert universe を
**出品が実際に使う resolver (catalog_psa.lookup_*)** で一括判定し、4 分類する:

  RESOLVED       : resolver が canonical product_id を返す (=出品OK)
  INDEX-FAILURE  : resolver は外したが catalog に実在 (=索引不備。0/O・set-code抽出失敗・
                   表記揺れ等。catalog追加でなく resolver/正規化 修正で直る)
  GAP            : recovery でも見つからない (=真の未収録。catalog 収録が要る)
  AMBIGUOUS/REVIEW: recovery で複数候補 (=人 or catalog 判定要)
  CATEGORY-UNKNOWN: brand から franchise 判定不能

= 「索引不備」と「真の未収録」を区別して出品前に先出しする (= 後手の火消し撲滅)。

使い方:
  python psa_preflight.py                  # psa_certs cache 全件
  python psa_preflight.py --certs FILE     # 1行1cert のリスト
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import sqlite3
from pathlib import Path

# ---- paths ----
_CATALOG_ROOT = r"C:/dev/iMak_catalog/iMakCatalog"
PSA_CERTS_DIR = Path(r"C:/dev/iMak/iMakeBayAPI/cache/psa_certs")
CATALOG_DB = r"C:/dev/iMak_data/catalog/products.sqlite"
REPORT_OUT = Path(r"C:/dev/iMak_data/catalog/requests/psa_preflight_report.md")

# catalog resolver は遅延 import (= 純関数の単体テスト時に重い catalog import を避ける +
#  他テストとの psa_to_csv 名前衝突を回避)。
_catalog_psa = None
_api = None
_FRANCHISE = None


def _ensure_catalog():
    """出品と同一 resolver (catalog_psa.lookup_*) を遅延 load."""
    global _catalog_psa, _api, _FRANCHISE
    if _FRANCHISE is not None:
        return
    for _p in (_CATALOG_ROOT, _CATALOG_ROOT + "/integrations"):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    from integrations import psa_to_csv as catalog_psa  # 出品と同一 resolver
    import api
    _catalog_psa, _api = catalog_psa, api
    _FRANCHISE = {
        "one_piece_tcg": (catalog_psa.lookup_one_piece, catalog_psa.extract_set_code_from_brand),
        "pokemon_tcg":   (catalog_psa.lookup_pokemon,   catalog_psa.extract_set_code_from_brand_pokemon),
        "dragonball_scg":(catalog_psa.lookup_dragonball,catalog_psa.extract_set_code_from_brand_dragonball),
        "gundam_tcg":    (catalog_psa.lookup_gundam,    catalog_psa.extract_set_code_from_brand_gundam),
        "yugioh_tcg":    (catalog_psa.lookup_yugioh,    None),
    }

_NOISE = {"HOLO", "PROMO", "PROMOTION", "PROMOTIONAL", "ANNIVERSARY", "EDITION", "SPECIAL",
          "CARD", "PACK", "SET", "ART", "RARE", "FULL", "PCP", "GOLDEN", "BOX", "COLLECTION",
          "STARTER", "DECK", "JAPANESE", "ASIA", "POKEMON", "FA", "SAR", "AR", "SR", "HR", "UR",
          "THE", "AND", "WITH", "VOL", "EX", "GX", "VSTAR", "VMAX", "STAR", "WORLD"}


def detect_category(brand: str):
    b = (brand or "").upper()
    if "ONE PIECE" in b: return "one_piece_tcg"
    if "POKEMON" in b: return "pokemon_tcg"
    if "YU-GI-OH" in b or "YUGIOH" in b: return "yugioh_tcg"
    if "DRAGON BALL" in b or "DRAGONBALL" in b: return "dragonball_scg"
    if "GUNDAM" in b: return "gundam_tcg"
    return None


def _subject_tokens(subject: str):
    toks = re.findall(r"[A-Za-z]{4,}", subject or "")
    return [t for t in toks if t.upper() not in _NOISE]


def _zero_o_variants(set_code: str):
    """set_code の 0<->O 全組合せ + 大小 を生成."""
    if not set_code:
        return []
    out = set()
    pos = [i for i, c in enumerate(set_code) if c in "0Oo"]
    # 0<->O 全組合せ
    base = set_code
    n = len(pos)
    for mask in range(1 << n) if n <= 6 else range(1):
        s = list(base)
        for k, i in enumerate(pos):
            s[i] = "O" if (mask >> k) & 1 else "0"
        v = "".join(s)
        out.add(v); out.add(v.upper()); out.add(v.lower())
    out.discard(set_code)
    return list(out)


def classify(cert: str, meta: dict, con: sqlite3.Connection):
    brand = meta.get("Brand", "") or ""
    subject = meta.get("Subject", "") or ""
    num = meta.get("CardNumber", "") or ""
    cat = detect_category(brand)
    res = {"cert": cert, "category": cat, "brand": brand, "subject": subject, "num": num}
    if not cat:
        res["status"] = "CATEGORY-UNKNOWN"; return res
    _ensure_catalog()
    lookup_fn, extract_fn = _FRANCHISE[cat]
    # 1) 出品と同一 resolver
    try:
        rec = lookup_fn(brand, num, subject, verbose=False)
    except TypeError:
        rec = lookup_fn(brand, num, subject)
    except Exception as e:
        rec = None; res["resolver_error"] = f"{type(e).__name__}: {e}"
    # lookup_* は legacy dict を返す: 解決IDは card_id (product_id でない)
    pid = (rec.get("card_id") or rec.get("product_id")) if rec else None
    if pid:
        res["status"] = "RESOLVED"; res["product_id"] = pid; return res
    # 2) recovery — 索引不備 vs 真の未収録 を区別
    cur = con.cursor()
    # 2a) set_code の 0/O・大小 変種 で再 lookup
    set_code = None
    if extract_fn:
        try:
            set_code = extract_fn(brand)
        except Exception:
            set_code = None
    if set_code and num:
        for v in _zero_o_variants(set_code):
            r = cur.execute("SELECT product_id,name_en FROM products WHERE category=? AND product_id=?",
                            (cat, f"{v}-{num}")).fetchone()
            if r:
                res["status"] = "INDEX-FAILURE"; res["recovered"] = r[0]
                res["reason"] = f"set_code 0/O・表記揺れ (抽出={set_code} → 実在={v})"
                return res
    # 2b) name + number ピンポイント (catalog に同名・同番号が在るか)
    toks = _subject_tokens(subject)
    hits = []
    if num and toks:
        for pat in (f"%-{num}", f"%-{num}\\_%"):
            for r in cur.execute(
                "SELECT product_id,name_en,name FROM products WHERE category=? AND product_id LIKE ? ESCAPE '\\'",
                (cat, pat)).fetchall():
                pid, nen, njp = r[0], (r[1] or ""), (r[2] or "")
                hay = (nen + " " + njp).lower()
                if any(t.lower() in hay for t in toks):
                    hits.append(pid)
    hits = sorted(set(hits))
    if hits:
        # name+番号 で候補在り = 索引不備の疑いだが別セット同番号の偶然もある → 断定せず REVIEW
        res["status"] = "REVIEW"; res["candidates"] = hits[:8]
        res["reason"] = (f"set_code抽出={set_code} で外したが name+番号で候補在り"
                         " (索引不備 or 別セット同番号 → 要判定)")
        return res
    res["status"] = "GAP"; res["reason"] = f"recovery不一致 (set_code={set_code})"
    return res


def load_certs(certs_file):
    if certs_file:
        certs = [l.strip() for l in Path(certs_file).read_text(encoding="utf-8").splitlines() if l.strip()]
        out = []
        for c in certs:
            f = PSA_CERTS_DIR / f"{c}.json"
            if f.exists():
                out.append((c, json.loads(f.read_text(encoding="utf-8"))))
        return out
    out = []
    for f in sorted(PSA_CERTS_DIR.glob("*.json")):
        try:
            out.append((f.stem, json.loads(f.read_text(encoding="utf-8"))))
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--certs", default=None, help="1行1cert のリストファイル")
    args = ap.parse_args()
    certs = load_certs(args.certs)
    con = sqlite3.connect(CATALOG_DB)
    buckets = {"RESOLVED": [], "INDEX-FAILURE": [], "REVIEW": [], "GAP": [], "AMBIGUOUS": [], "CATEGORY-UNKNOWN": []}
    for cert, meta in certs:
        r = classify(cert, meta, con)
        buckets.setdefault(r["status"], []).append(r)
    total = len(certs)
    print(f"PSA pre-flight: {total} certs")
    for k in ("RESOLVED", "INDEX-FAILURE", "REVIEW", "GAP", "AMBIGUOUS", "CATEGORY-UNKNOWN"):
        print(f"  {k:16}: {len(buckets[k])}")
    # report
    lines = [f"# PSA pre-flight report ({total} certs)", ""]
    lines.append(f"- RESOLVED {len(buckets['RESOLVED'])} / INDEX-FAILURE {len(buckets['INDEX-FAILURE'])} / "
                 f"GAP {len(buckets['GAP'])} / AMBIGUOUS {len(buckets['AMBIGUOUS'])} / "
                 f"CATEGORY-UNKNOWN {len(buckets['CATEGORY-UNKNOWN'])}")
    for k in ("INDEX-FAILURE", "REVIEW", "GAP", "AMBIGUOUS", "CATEGORY-UNKNOWN"):
        lines.append("")
        lines.append(f"## {k} ({len(buckets[k])})")
        for r in buckets[k]:
            extra = r.get("recovered") or (",".join(r.get("candidates", [])) if r.get("candidates") else "")
            lines.append(f"- cert {r['cert']} [{r.get('category')}] {r['subject'][:40]} #{r['num']}"
                         + (f" → 実在 {extra}" if extra else "")
                         + (f" | {r['reason']}" if r.get("reason") else ""))
    REPORT_OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"report: {REPORT_OUT}")
    return buckets


if __name__ == "__main__":
    main()
