#!/usr/bin/env python3
"""ebay_filter_map の値を eBay 公式 aspect リストに照合する (A/B/U 判定 + 綴り引き当て).

決定: requests/2026-08-21_set_rarity_final_plan_response_go.md [IMPLEMENT-GO]
      (ユーザー委任 → 出品くん / カタログ / Gemini の3者合意)

## 何をするか
eBay の getItemAspectsForCategory(183454) の返り (_input/ebay_tcg_filter_lists_api.json)
を唯一の照合相手にして、変換表の各値を3状態に分ける。

  A = eBay のリストにその綴りが在る          → 触らない
  B = リストに無いが **実際に出品データに載っている** → 値は変えない。印だけ (追加申請候補)
  U = リストにも無く、まだどの行にも載っていない      → **誤りではなく未使用**

## ★規則で変換しない (3者合意 #2)
eBay の綴りは一貫していない:
    S6a: Eevee Heroes        ← 弾番号つきしか無い
    Shiny Star V             ← 素の名前で在る
「頭に弾番号を付ける」を規則にすると、素の名前で既に一致している値を壊す。
**リストに在る綴りをそのまま採る (引き当て)**。無ければ触らない。

## ★fuzzy で寄せない (3者合意 #4)
GX Battle Boost (SM4+) と Ex Battle Boost (EXバトルブースト BW期) は別セット。
綴りが似ているだけで寄せると別セットとして出品される。
引き当ては「弾番号を外した部分が完全一致」かつ「候補が1つだけ」の時のみ採る。

## 凍結 (3者合意 #3)
one_piece_tcg / gundam_tcg / dragonball_scg は eBay にセット名がほぼ無いので値を触らない。
引き当ての対象は pokemon_tcg のみ。

実行:
  python tools/ebay_value_reconcile.py            # 一覧を出すだけ (既定)
  python tools/ebay_value_reconcile.py --commit   # status 列 + ポケモンの綴り引き当てを適用
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

EBAY_JSON = Path(r"C:\dev\iMak_data\catalog\_input\ebay_183454_facet_master_20260821.json")
# 2026-08-21 窓口確定: Game で絞れる新マスタを正とする (旧 ebay_tcg_filter_lists_api.json は
# 全ゲーム混在の 2,290値で、ポケモン以外のセット名まで候補に入っていた)。
# category -> eBay の Game 名。ここに無いカテゴリは all を使う。
GAME_OF = {"pokemon_tcg": "Pokémon TCG", "one_piece_tcg": "One Piece CCG",
           "dragonball_scg": "Dragon Ball Super Card Game"}
OUT_MD = Path(r"C:\dev\iMak_data\catalog\requests\2026-08-21_ebay_value_reconcile_report.md")
NOW = datetime.now().isoformat()

ADOPT_CATEGORIES = {"pokemon_tcg"}       # 引き当て対象。他は凍結
SET_FIELDS = ("set", "set_code")
CATS = ("one_piece_tcg", "pokemon_tcg", "dragonball_scg", "gundam_tcg")

PREFIX_RE = re.compile(r"^[A-Za-z]{1,4}\d*[A-Za-z+]*:\s*")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_ebay():
    """(Set 全体, Rarity 全体, Game 別 Set) を返す."""
    d = json.loads(EBAY_JSON.read_text(encoding="utf-8"))

    def vals(node):
        return [v.strip() for v in node if isinstance(v, str) and v.strip()]

    st = d["aspects"]["Set"]
    ra = d["aspects"]["Rarity"]
    by_game = {g: vals(v) for g, v in st.get("by_game", {}).items()}
    return vals(st["all"]), vals(ra["all"]), by_game


def build_index(values):
    idx = {}
    for v in values:
        idx.setdefault(norm(PREFIX_RE.sub("", v)), []).append(v)
    return idx


def real_sources(db):
    official = {r[0] for r in db.execute(
        "SELECT DISTINCT set_name_official FROM products WHERE set_name_official IS NOT NULL")}
    prefixes = {r[0] for r in db.execute(
        "SELECT DISTINCT substr(product_id,1,instr(product_id,'-')-1) FROM products "
        "WHERE instr(product_id,'-')>0")}
    brackets = set()
    for s in official:
        brackets.update(re.findall(r"[\[\u3010]([A-Z0-9-]+)[\]\u3011]", s or ""))
    return official, prefixes, brackets


def classify(db):
    set_vals, rar_vals, by_game = load_ebay()
    set_exact, rar_exact = set(set_vals), set(rar_vals)
    set_low = {v.lower(): v for v in set_vals}
    rar_low = {v.lower(): v for v in rar_vals}
    set_idx = build_index(set_vals)
    official, prefixes, brackets = real_sources(db)

    # 実際に products に載っている値 (= 出品に出る値)。B / U の判定はこれで行う。
    # ★source_value が公式セット名と一致するかで見ると、set_code 経由の正しい行や
    #   DON!! のような行まで「裏が取れない」に落ちる (2026-08-21 実測。890行 使われている
    #   'Premium Booster One Piece The Best' が C に入っていた)。
    used_set, used_rar = {}, {}
    for cat in CATS:
        used_set[cat] = {r[0] for r in db.execute(
            "SELECT DISTINCT json_extract(specs,'$.set_name_ebay') FROM products WHERE category=? "
            "AND json_extract(specs,'$.set_name_ebay') IS NOT NULL "
            "AND json_extract(specs,'$.set_name_ebay')<>''", (cat,))}
        used_rar[cat] = {r[0] for r in db.execute(
            "SELECT DISTINCT json_extract(specs,'$.rarity_ebay') FROM products WHERE category=? "
            "AND json_extract(specs,'$.rarity_ebay') IS NOT NULL "
            "AND json_extract(specs,'$.rarity_ebay')<>''", (cat,))}

    out = []
    for r in db.execute("SELECT id, category, field, source_value, ebay_value FROM ebay_filter_map "
                        "ORDER BY category, field, source_value"):
        ev = (r["ebay_value"] or "").strip()
        if not ev:
            continue
        is_set = r["field"] in SET_FIELDS
        # ★Game で絞る (2026-08-21 窓口確定)。よそのゲームのセット名に当たらないようにする。
        game = GAME_OF.get(r["category"])
        if is_set:
            # ★Game 別リストしか使わない。全ゲーム混在の all を使うと、
            #   'Promo Cards' が Final Fantasy の 'FF: Promo Cards' に寄る (2026-08-21 実測)。
            #   Game が無いカテゴリ (gundam) は「eBay に一覧が無い」扱い = 全部 B/U 判定へ。
            gvals = by_game.get(game) or []
            exact = set(gvals)
            low = {v.lower(): v for v in gvals}
            gidx = build_index(gvals)
        else:
            gvals = []
            exact, low, gidx = rar_exact, rar_low, {}
        proposal = None

        if ev in exact:
            status = "A"
            # ★code 形が正 (2026-08-21 窓口確定)。素の名前と code 付きが両方在るなら
            #   code 付きを採る。日本語版カードは日本語版セットの code 形で出す。
            if r["category"] in ADOPT_CATEGORIES:
                cands = gidx.get(norm(ev), [])
                pref = [c for c in cands if PREFIX_RE.match(c)]
                if pref and not PREFIX_RE.match(ev):
                    proposal = sorted(pref)[0]
        elif ev.lower() in low:
            status, proposal = "A", low[ev.lower()]
        else:
            # B = eBay のリストには無いが **実際に出品データに載っている** = 正しい値。凍結
            # U = まだどの行にも載っていない = **誤りではなく未使用**
            #     (HQ 2026-08-21: 消すと、そのカードが入った時にまた同じ変換を書くことになる)
            used = used_set if is_set else used_rar
            if ev in used.get(r["category"], set()):
                status = "B"
            elif is_set and ((r["source_value"] in official)
                             or (r["source_value"] in prefixes)
                             or (r["source_value"] in brackets)
                             or (r["source_value"].replace("-", "") in prefixes)):
                status = "B"
            else:
                status = "U"
            if is_set and r["category"] in ADOPT_CATEGORIES:
                cands = gidx.get(norm(ev), [])
                if len(cands) == 1 and cands[0] != ev:
                    proposal = cands[0]
        out.append(dict(id=r["id"], category=r["category"], field=r["field"],
                        source_value=r["source_value"], ebay_value=ev,
                        status=status, proposal=proposal))
    return out


def ensure_columns(db):
    cols = {c[1] for c in db.execute("PRAGMA table_info(ebay_filter_map)")}
    for name in ("status", "verified_at", "verify_source"):
        if name not in cols:
            db.execute("ALTER TABLE ebay_filter_map ADD COLUMN %s TEXT" % name)


def write_report(rows, prop, cs):
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with OUT_MD.open("w", encoding="utf-8") as f:
        f.write("# eBay 値 照合レポート (書込前の一覧)\n\n")
        f.write("生成: %s\n\n照合相手: `%s`\n\n" % (NOW, EBAY_JSON))
        f.write("## status 内訳\n\n| category | A | B | U(未使用) | 引き当て |\n|---|--:|--:|--:|--:|\n")
        for cat in CATS:
            c = Counter(x["status"] for x in rows if x["category"] == cat)
            adopt = sum(1 for x in rows if x["category"] == cat and x["proposal"])
            f.write("| %s | %d | %d | %d | %d |\n" % (cat, c["A"], c["B"], c["U"], adopt))
        f.write("\n- **A** = eBay のリストに在る綴り。触らない\n")
        f.write("- **B** = リストに無いが公式データに実在。値は変えず印だけ (eBay への追加申請候補)\n")
        f.write("- **U** = eBay にも無く、まだどの行にも載っていない。**誤りではなく未使用**。\n")
        f.write("  消すと、そのカードが入ってきた時にまた同じ変換を書くことになる (HQ 2026-08-21)\n")
        f.write("\n## eBay の綴りに寄せる候補 (%d 件 / pokemon のみ)\n\n" % len(prop))
        f.write("| category | field | 今の値 | eBay の綴り |\n|---|---|---|---|\n")
        for x in prop:
            f.write("| %s | %s | `%s` | `%s` |\n"
                    % (x["category"], x["field"], x["ebay_value"], x["proposal"]))
        f.write("\n## U = まだ使われていない (%d 件) ※誤りではない\n\n" % len(cs))
        f.write("| category | field | 値 | 変換元 |\n|---|---|---|---|\n")
        for x in cs:
            f.write("| %s | %s | `%s` | `%s` |\n"
                    % (x["category"], x["field"], x["ebay_value"], x["source_value"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(api._DB_PATH)
    db.row_factory = sqlite3.Row
    rows = classify(db)
    prop = [x for x in rows if x["proposal"]]
    cs = [x for x in rows if x["status"] == "U"]

    print("=== ebay_filter_map 照合 (%s) ===" % ("APPLY" if args.commit else "REPORT"))
    print("対象 %d 行 / 照合相手 %s\n" % (len(rows), EBAY_JSON.name))
    for cat in CATS:
        c = Counter(x["status"] for x in rows if x["category"] == cat)
        adopt = sum(1 for x in rows if x["category"] == cat and x["proposal"])
        frozen = "" if cat in ADOPT_CATEGORIES else "  (凍結=引き当てなし)"
        print("  %-16s A%4d B%4d U%4d   引き当て %3d%s"
              % (cat, c["A"], c["B"], c["U"], adopt, frozen))

    print("\n--- eBay の綴りに寄せる候補 %d 件 (pokemon のみ) ---" % len(prop))
    for x in prop:
        print("  %-9s %r -> %r" % (x["field"], x["ebay_value"], x["proposal"]))

    print("\n--- U (まだ使われていない) %d 件 ※誤りではない ---" % len(cs))
    for x in cs:
        print("  %-14s %-9s %r  <- %r"
              % (x["category"], x["field"], x["ebay_value"], x["source_value"]))

    write_report(rows, prop, cs)
    print("\nレポート: %s" % OUT_MD)

    if args.commit:
        ensure_columns(db)
        for x in rows:
            ev = x["proposal"] or x["ebay_value"]
            db.execute("UPDATE ebay_filter_map SET ebay_value=?, status=?, verified_at=?, "
                       "verify_source=? WHERE id=?",
                       (ev, x["status"], NOW,
                        "ebay_getItemAspectsForCategory_183454", x["id"]))
        db.commit()
        print("[OK] 適用 (status %d 行 / 綴り引き当て %d 行)" % (len(rows), len(prop)))
    else:
        print("(report のみ — --commit で適用)")
    db.close()


if __name__ == "__main__":
    main()
