#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""カタログ B層監査 (read-only, 2026-06-07)。

辞書(=カタログ)の正しさを機械監査する仕組みの中核。B層(eBay派生)フィールドを
eBay Taxonomy(公式ファセット)と照合し、ズレを検出する。

対象 (今回優先): TCG4ゲーム (one_piece / pokemon / dragonball / gundam)。
  共通カテゴリ 183454 = 同一 eBay Taxonomy で照合。

照合フィールド (specs *_ebay → eBay aspect):
  set_name_ebay → Set / game_ebay → Game / card_type_ebay → Card Type / rarity_ebay → Rarity
判定:
  blank      : 空欄 (fail-closed。未取得。誤りではない)
  in-facet   : eBay公式値と一致 (= フィルタに束ねられる。正)
  off-facet  : 非空だが eBay値に無い → ①em-dash形式(Pokemon.com流, SEO問題) ②それ以外(誤り/typo疑い)
さらに B層生成元(source)を auto(claude/pokeapi番号) vs verified で集計。

read-only。修正はしない (Catalog領域)。--sheet でスプシにも書く。
"""
import collections
import json
import re
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = r"C:\dev\iMak_data\catalog\products.sqlite"
TCG_TAXONOMY = r"C:/dev/iMak_data/catalog/_input/ebay_tcg_filter_lists_api.json"
TARGET_SHEET_ID = "1U0P3gLMYzQMdxIrP2OE31XSGQOStdK0QPIfH2uC88vE"
CREDS_PATH = r"c:\dev\iMak\double-hold-421922-7c0d38d3f73d.json"

TCG_CATS = ["one_piece_tcg", "pokemon_tcg", "dragonball_scg", "gundam_tcg"]

# specs B層フィールド → eBay aspect 名
FIELD_TO_ASPECT = {
    "set_name_ebay": "Set",
    "game_ebay": "Game",
    "card_type_ebay": "Card Type",
    "rarity_ebay": "Rarity",
}

# auto判定する source 接頭 (= 未検証=要確認)
AUTO_SRC = ("claude_api", "pokeapi_official", "pokeapi", "name_copy", "name_en_jp_propagate",
            "product_id_native", "rule_")


def load_facets():
    d = json.load(open(TCG_TAXONOMY, encoding="utf-8"))
    asp = d["aspects"]
    out = {}
    for name, a in asp.items():
        vals = a.get("values", []) if isinstance(a, dict) else []
        out[name] = set(
            (v.get("localizedValue") if isinstance(v, dict) else v).strip().lower()
            for v in vals if (v.get("localizedValue") if isinstance(v, dict) else v))
    return out


def is_emdash(s):
    return "—" in s or "–" in s


def _name_core(val):
    """'Sv2p: Snow Hazard' / 'Sun & Moon—Lost Thunder' → 'snow hazard' / 'lost thunder' 近似コア。"""
    s = val.lower().replace("—", " ").replace("–", " ")
    s = re.split(r":", s)[-1] if ":" in s else s   # 'code: name' → name
    toks = [t for t in re.split(r"[\s]+", s) if t]
    return " ".join(toks[-3:]) if toks else ""


def classify_off(val, facet_raw_lower):
    """off-facet値を format(名前はeBayに有る=要reformat) / absent(eBayに無い=新規or誤り) に分類。"""
    core = _name_core(val)
    if core and any(core in r for r in facet_raw_lower):
        return "format"
    return "absent"


def audit_category(con, cat, facets, facets_raw_lower):
    rows = con.execute(
        "SELECT specs,name_en,name_en_source FROM products WHERE category=?", (cat,)).fetchall()
    n = len(rows)
    field_stat = {f: {"blank": 0, "in": 0, "off": 0, "off_vals": collections.Counter()}
                  for f in FIELD_TO_ASPECT}
    src_tally = collections.Counter()
    nameen_blank = 0
    for sp, name_en, ne_src in rows:
        try:
            d = json.loads(sp) if sp else {}
        except Exception:
            d = {}
        for f, aspect in FIELD_TO_ASPECT.items():
            v = (d.get(f) or "").strip()
            st = field_stat[f]
            if not v:
                st["blank"] += 1
                continue
            if v.lower() in facets.get(aspect, set()):
                st["in"] += 1
            else:
                st["off"] += 1
                st["off_vals"][v] += 1
        src = (ne_src or "(空)")
        src_tally["auto" if any(src.startswith(a) for a in AUTO_SRC) else (
            "blank" if src == "(空)" else "verified/other")] += 1
        if not (name_en or "").strip():
            nameen_blank += 1
    # off を format/absent に再分類 (distinct値で判定 → 件数合算)
    for f, aspect in FIELD_TO_ASPECT.items():
        st = field_stat[f]
        fr = facets_raw_lower.get(aspect, [])
        fmt = absent = 0
        st["fmt_vals"] = collections.Counter()
        st["absent_vals"] = collections.Counter()
        for val, cnt in st["off_vals"].items():
            if classify_off(val, fr) == "format":
                fmt += cnt; st["fmt_vals"][val] = cnt
            else:
                absent += cnt; st["absent_vals"][val] = cnt
        st["off_format"] = fmt
        st["off_absent"] = absent
    return n, field_stat, src_tally, nameen_blank


def fuzzy_suggest(val, facet_raw):
    """off-facet 値に近い eBay 実値を1つ提案 (末尾名詞2語の contains)。"""
    nl = val.lower().replace("—", " ").replace("–", " ")
    toks = [t for t in re.split(r"[\s:]+", nl) if t]
    if not toks:
        return ""
    key = " ".join(toks[-2:]) if len(toks) >= 2 else toks[-1]
    for r in facet_raw:
        if key in r.lower().replace("—", " "):
            return r
    return ""


def main():
    to_sheet = "--sheet" in sys.argv
    con = sqlite3.connect(DB)
    facets = load_facets()
    d = json.load(open(TCG_TAXONOMY, encoding="utf-8"))
    facets_raw_lower = {}
    for name, a in d["aspects"].items():
        vals = a.get("values", []) if isinstance(a, dict) else []
        facets_raw_lower[name] = [
            (v.get("localizedValue") if isinstance(v, dict) else v).lower()
            for v in vals if (v.get("localizedValue") if isinstance(v, dict) else v)]
    set_raw = [(v.get("localizedValue") if isinstance(v, dict) else v)
               for v in d["aspects"]["Set"]["values"]]

    summary_rows = [["カタログ B層監査 (eBay Taxonomy照合) — read-only / 2026-06-07", "", "", "", "", "", ""],
                    ["category", "件数", "field", "空欄(fail-closed)", "in-facet(正)",
                     "off:format(名前はeBay有=要reformat)", "off:absent(eBay無=新規or誤り)"]]
    detail_rows = [["category", "field", "off-facet値", "件数", "種別", "eBay候補(近似)"]]

    for cat in TCG_CATS:
        n, fs, src, ne_blank = audit_category(con, cat, facets, facets_raw_lower)
        print(f"\n========== {cat} (n={n}) ==========")
        print(f"  name_en source: {dict(src)}  | name_en空={ne_blank}")
        for f, aspect in FIELD_TO_ASPECT.items():
            st = fs[f]
            print(f"  [{f:16}→{aspect:10}] 空{st['blank']:6} 正{st['in']:6} "
                  f"format{st['off_format']:6} absent{st['off_absent']:6}")
            summary_rows.append([cat, n, f, st["blank"], st["in"], st["off_format"], st["off_absent"]])
            fr = facets_raw_lower.get(aspect, [])
            for val, cnt in st["off_vals"].most_common(50):
                kind = "format(要reformat)" if classify_off(val, fr) == "format" else "absent(新規/誤り)"
                detail_rows.append([cat, f, val, cnt, kind, fuzzy_suggest(val, set_raw)])
        tot_fmt = sum(fs[f]["off_format"] for f in FIELD_TO_ASPECT)
        tot_abs = sum(fs[f]["off_absent"] for f in FIELD_TO_ASPECT)
        print(f"  >>> off-format(要reformat) {tot_fmt} / off-absent(新規or誤り) {tot_abs}")

    if to_sheet:
        sys.path.insert(0, r"c:\dev\iMak\iMakHQ\tools")
        from sheet_io import write_rows_to_tab
        write_rows_to_tab("監査_サマリー", summary_rows, sheet_id=TARGET_SHEET_ID)
        write_rows_to_tab("監査_要確認", detail_rows, sheet_id=TARGET_SHEET_ID)
        print(f"\n✅ スプシ書込: 監査_サマリー / 監査_要確認")
        print(f"   https://docs.google.com/spreadsheets/d/{TARGET_SHEET_ID}/edit")


if __name__ == "__main__":
    main()
