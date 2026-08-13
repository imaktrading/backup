#!/usr/bin/env python3
"""set_name_ebay 内部整合監査 (Catalog SSOT) — 2026-06-13 新設 (HQ greenlight).

set_name_ebay の系統的誤り (JP限定ハイクラスパックを英語版 main set 名に誤map 等。
例 S8b VMAXクライマックス→"Brilliant Stars"=英S9=別set) を catalog 内部で検出する。
HQ 照合ツール(出力CSV側) と二重で守る (= dual_gate)。

検査:
  1. era整合      : set_code の era (S/SM/SV/XY/BW…) と set_name_ebay の era接頭
                    ("Sword & Shield—" 等) の不一致を flag (= 別era set名への誤map)。
  2. set_code一貫性: 同一 set_code 内で set_name_ebay が複数値に割れている flag。
  3. source棚卸し  : set_name_ebay_source='(none)' (= 由来不明・未検証) を set_code 単位で
                    集計リスト化 (= S8b級の潜在誤りの母数。件数降順)。
  4. name整合      : name_en ≠ specs.character_name (両方非空) を flag
                    (= romaji name_en 修正時の character_name 同期漏れ等。eBay C:Character は
                    character_name 由来のため不整合=誤出品。2026-06-13 HQ依頼で追加)。
  5. empty棚卸し   : set_name_ebay='' (fail_closed_no_map / 単純空欄) の絶対数を category 別に集計。
                    2026-08-11 依頼 (op03_001_p2_set_name_ebay_empty_response.md §段3) で追加。
                    「214→423 に増えたのを誰も見ていなかった」の再発防止。
                    ★0 になっても出し続ける (0 が続く証跡が再発しないことの唯一の証拠)。
  6. canonical ズレ検知: specs.set_name_ebay ≠ 今その場で yaml/filter_map から計算した canonical値
                    の行数を category 別に絶対数で集計。
                    2026-08-12 依頼 (_ssot_contract_master_coverage_and_leaf_check_response_question_response.md)
                    契約 v1.2 §1-5 の「導出化 = restamp + ズレ検知」を実現する検出面。
                    可視化のみ (gate にしない)。★0 になっても出し続ける (§5 と同じ規約)。
                    定義: derive_set_name_ebay(cat, set_name_official, product_id) が
                    非-None を返し、それが stored (specs.set_name_ebay) と異なる行だけを数える
                    (= state (a) canonical のズレ)。state (b) 自由文字列 (filter_map 未収載) と
                    state (c) 空 は drift 対象外 (契約 v1.2 §1-3 の 3 状態を尊重)。

使い方:
  python iMakCatalog/tools/set_name_integrity_audit.py                # pokemon (既定)
  python iMakCatalog/tools/set_name_integrity_audit.py --cat all      # 全カテゴリ
  python iMakCatalog/tools/set_name_integrity_audit.py --out audit.md # md 出力
"""
import argparse
import datetime as _dt
import json
import re
import sqlite3
import sys
from collections import defaultdict

DB_PATH = "C:/dev/iMak_data/catalog/products.sqlite"

# 完走マーカー (途中で死んだ = マーカーが出ない = ログ検知できる).
# prune_daily.log と同型の「=== ... ===」規約に合わせる (2026-07-31 daily cron 化).
_START_MARK = "=== set_name integrity audit START"
_END_MARK = "=== set_name integrity audit COMPLETE"

_ERAS = ["Scarlet & Violet", "Sword & Shield", "Sun & Moon", "Black & White", "XY"]

# §6 canonical ズレ検知用 (api.derive_set_name_ebay と同じ 3 段 fallback を local に実装.
#   api を import して api._DB_PATH に依存させると in-memory temp DB のテストが動かない.
#   ロジック本体は api.derive_set_name_ebay と同順で保つ — 変更する場合は両方同時修正.)
_SET_CODE_BRACKET_RE = re.compile(r"[\[【]([A-Z][A-Z0-9-]*)[\]】]")


def _fmap_lookup(conn, category: str, field: str, source_value):
    if not source_value:
        return None
    row = conn.execute(
        "SELECT ebay_value FROM ebay_filter_map "
        "WHERE category=? AND field=? AND source_value=?",
        (category, field, source_value),
    ).fetchone()
    return row["ebay_value"] if row else None


def _derive_set_name_ebay(conn, category: str, set_name_official, product_id):
    """derive_set_name_ebay と同順 (①set_official ②[CODE] ③pid prefix) — 無ければ None."""
    if set_name_official:
        v = _fmap_lookup(conn, category, "set", set_name_official)
        if v:
            return v
        m = _SET_CODE_BRACKET_RE.search(set_name_official)
        if m:
            v = _fmap_lookup(conn, category, "set_code", m.group(1))
            if v:
                return v
    if product_id and "-" in product_id:
        pref = product_id.split("-", 1)[0]
        for cand in {pref, pref.upper(), pref.lower()}:
            v = _fmap_lookup(conn, category, "set_code", cand)
            if v:
                return v
    return None


_RARITY_STAR_RE = re.compile(r"[★☆]+\s*$")


def _derive_rarity_ebay(conn, category: str, rarity_raw):
    """api.derive_rarity_ebay と同順 (★ を落として filter_map) — 無ければ None."""
    if not rarity_raw:
        return None
    base = _RARITY_STAR_RE.sub("", str(rarity_raw).strip()).strip()
    if not base:
        return None
    return _fmap_lookup(conn, category, "rarity", base)


def setcode_era(sc: str):
    sc = sc or ""
    if sc.startswith("SV"):
        return "Scarlet & Violet"
    if sc.startswith("SM"):
        return "Sun & Moon"
    if sc.startswith("XY"):
        return "XY"
    if sc.startswith("BW"):
        return "Black & White"
    if re.match(r"^S\d", sc):
        return "Sword & Shield"
    return None  # legacy(DP/L/M…) や promo は era 判定対象外


def ebay_era(name: str):
    name = name or ""
    for era in _ERAS:
        if name.startswith(era + "—") or name.startswith(era + " "):
            return era
    return None


def setcode_of(product_id: str, specs: dict) -> str:
    return specs.get("set_code") or (product_id.split("-")[0] if product_id else "")


def audit(categories):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    q = "SELECT category, product_id, name_en, set_name_official, specs FROM products"
    if categories:
        ph = ",".join("?" for _ in categories)
        q += f" WHERE category IN ({ph})"
        rows = conn.execute(q, categories).fetchall()
    else:
        rows = conn.execute(q).fetchall()

    # set_code -> {set_name_ebay -> count}, set_code -> source set, set_code -> category
    by_code = defaultdict(lambda: defaultdict(int))
    code_src = defaultdict(set)
    code_cat = {}
    none_src = defaultdict(lambda: defaultdict(int))  # source=(none) 棚卸し
    era_mismatch = []  # (set_code, ebay, sc_era, ebay_era, count)
    name_desync = []  # (product_id, name_en, character_name)
    # 5. empty棚卸し: category -> {'fail_closed_no_map': N, 'blank': M, 'total_empty': N+M}
    empty_by_cat = defaultdict(lambda: {"fail_closed_no_map": 0, "blank": 0, "total_empty": 0})
    # 6. canonical ズレ検知: category -> drift 件数 (state (a) canonical のみ)
    drift_by_cat = defaultdict(int)
    # 7. rarity 生値焼き付き検知 (2026-08-13): category -> {raw_stamped, map_drift}
    #    raw_stamped = specs.rarity_ebay が公式生コードのまま (変換されていない) 行。
    #      2026-08-13 の実害 (rarity_ebay='L★' → 禁止文字除去で 'L' 1文字) と同型で、
    #      'U' / 'SPカード' / 'LR+' のような値が C:Rarity に出るのを毎日可視化する。
    #    map_drift = filter_map から今その場で計算した値 ≠ stored (契約 v1.2 §1-5 のズレ検知)。
    #      yaml 側が旧短縮コードのまま (pokemon/one_piece/gundam) なら大量に出る = yaml 未同期の指標。
    rarity_by_cat = defaultdict(lambda: {"raw_stamped": 0, "map_drift": 0})

    tmp_era = defaultdict(int)  # (set_code,ebay) count for era check
    for r in rows:
        s = json.loads(r["specs"])
        sc = setcode_of(r["product_id"], s)
        e = s.get("set_name_ebay") or ""
        src = s.get("set_name_ebay_source") or "(none)"
        by_code[sc][e] += 1
        code_src[sc].add(src)
        code_cat[sc] = r["category"]
        if e:
            tmp_era[(sc, e)] += 1
            if src == "(none)":
                none_src[sc][e] += 1
        else:
            # empty 側の内訳: fail_closed_no_map か、それ以外 (blank)
            bucket = empty_by_cat[r["category"]]
            if src == "fail_closed_no_map":
                bucket["fail_closed_no_map"] += 1
            else:
                bucket["blank"] += 1
            bucket["total_empty"] += 1
        # 4. name_en ↔ character_name 整合 (両方非空で不一致)
        #    接頭辞一致 ("Pikachu V" vs "Pikachu" の V/VMAX/ex 接尾差) は正当として除外し、
        #    真の名前相違 (romaji 同期漏れ等) のみ flag。
        cn = s.get("character_name")
        ne = r["name_en"]
        if ne and cn and ne != cn \
                and not ne.startswith(cn) and not cn.startswith(ne):
            name_desync.append((r["product_id"], ne, cn))
        # 6. canonical ズレ検知: 今その場で filter_map から計算し、stored と比較.
        #    computed が非-None (= state (a) canonical に該当) かつ stored != computed の行のみ数える.
        #    computed=None のケース (state (b) 自由文字列 / state (c) 空) は drift 対象外.
        computed = _derive_set_name_ebay(conn, r["category"], r["set_name_official"],
                                          r["product_id"])
        if computed is not None and computed != e:
            drift_by_cat[r["category"]] += 1
        # 7. rarity 生値焼き付き / map ズレ (computed=None は filter_map 未登録 = 別問題)
        r_raw, r_stored = s.get("rarity"), s.get("rarity_ebay")
        # yugioh は生値が既に英語 canonical ("Secret Rare" 等) で passthrough が正 → 対象外
        if r_raw and r_stored and r["category"] != "yugioh_tcg" \
                and str(r_raw).strip() == str(r_stored).strip():
            rarity_by_cat[r["category"]]["raw_stamped"] += 1
        computed_rarity = _derive_rarity_ebay(conn, r["category"], r_raw)
        if computed_rarity is not None and computed_rarity != r_stored:
            rarity_by_cat[r["category"]]["map_drift"] += 1

    conn.close()

    # 1. era mismatch
    for (sc, e), cnt in tmp_era.items():
        sce, ee = setcode_era(sc), ebay_era(e)
        if sce and ee and sce != ee:
            era_mismatch.append((sc, e, sce, ee, cnt))
    era_mismatch.sort(key=lambda x: -x[4])

    # 2. set_code 一貫性 (set_name_ebay が空でない値が2種以上)
    inconsistent = []
    for sc, d in by_code.items():
        vals = {k: v for k, v in d.items() if k}
        if len(vals) >= 2:
            inconsistent.append((sc, dict(vals)))
    inconsistent.sort(key=lambda x: -sum(x[1].values()))

    # 3. source=(none) 棚卸し (set_code 単位・件数降順)
    none_list = []
    for sc, d in none_src.items():
        total = sum(d.values())
        # 単一値のものだけ (複数値は #2 で別途出る)
        val = max(d.items(), key=lambda kv: kv[1])[0] if d else ""
        none_list.append((sc, val, total, code_cat.get(sc, "")))
    none_list.sort(key=lambda x: -x[2])
    name_desync.sort(key=lambda x: x[0])

    return (era_mismatch, inconsistent, none_list, name_desync,
            dict(empty_by_cat), dict(drift_by_cat), dict(rarity_by_cat))


def render(era_mismatch, inconsistent, none_list, name_desync, empty_by_cat,
           drift_by_cat, rarity_by_cat, categories):
    out = []
    cat_s = ",".join(categories) if categories else "all"
    out.append(f"# set_name_ebay integrity audit (cat={cat_s})\n")
    out.append(f"## 1. era 不一致 (別era set名への誤map疑い) — {len(era_mismatch)} 件\n")
    if not era_mismatch:
        out.append("(なし)\n")
    for sc, e, sce, ee, cnt in era_mismatch:
        out.append(f"- ⚠️ `{sc}` ({sce}) → set_name_ebay=`{e}` ({ee}) × {cnt}件\n")

    out.append(f"\n## 2. set_code 内 set_name_ebay 不統一 — {len(inconsistent)} 件\n")
    if not inconsistent:
        out.append("(なし)\n")
    for sc, vals in inconsistent[:40]:
        out.append(f"- `{sc}`: {vals}\n")

    out.append(
        f"\n## 3. source=(none) 棚卸し (由来不明=未検証, set_code単位) — "
        f"{len(none_list)} set_code / 計 {sum(x[2] for x in none_list)} 件\n"
    )
    out.append("| set_code | set_name_ebay | 件数 | category |\n|---|---|---|---|\n")
    for sc, val, cnt, cat in none_list[:120]:
        out.append(f"| {sc} | {val} | {cnt} | {cat} |\n")

    out.append(
        f"\n## 4. name_en ≠ character_name (eBay C:Character 不整合) — "
        f"{len(name_desync)} 件\n"
    )
    if not name_desync:
        out.append("(なし)\n")
    for pid, ne, cn in name_desync[:60]:
        out.append(f"- `{pid}`: name_en=`{ne}` ≠ character_name=`{cn}`\n")

    # 5. empty 棚卸し (fail_closed_no_map + 単純空欄) を category 別に絶対数で。
    #    ★ 0 になっても出し続ける (0 が続いている証跡が再発しないことの唯一の証拠)。
    total_empty = sum(v["total_empty"] for v in empty_by_cat.values())
    total_fail_closed = sum(v["fail_closed_no_map"] for v in empty_by_cat.values())
    out.append(
        f"\n## 5. set_name_ebay 空欄 棚卸し (絶対数・毎日出す) — "
        f"合計 {total_empty} 件 (うち fail_closed_no_map {total_fail_closed})\n"
    )
    if not empty_by_cat:
        out.append("(全カテゴリで空欄ゼロ)\n")
    else:
        out.append("| category | fail_closed_no_map | blank(other) | total_empty |\n")
        out.append("|---|---:|---:|---:|\n")
        for cat in sorted(empty_by_cat.keys()):
            v = empty_by_cat[cat]
            out.append(
                f"| {cat} | {v['fail_closed_no_map']} | {v['blank']} | {v['total_empty']} |\n"
            )

    # 6. canonical ズレ検知 (specs.set_name_ebay ≠ 今その場で filter_map から計算した canonical)
    #    契約 v1.2 §1-5 (導出化=restamp+ズレ検知) の検出面。可視化のみ・gate にしない。
    #    ★ 0 になっても出し続ける (§5 と同じ規約)。
    #    state (a) canonical のズレのみ数える (computed が None = state (b)/(c) は除外)。
    total_drift = sum(drift_by_cat.values())
    out.append(
        f"\n## 6. canonical ズレ検知 (絶対数・毎日出す) — "
        f"合計 {total_drift} 件\n"
    )
    out.append(
        "定義: derive_set_name_ebay(cat, set_name_official, product_id) が非-None で、"
        "stored (specs.set_name_ebay) と異なる行 (= state (a) canonical のズレ)。"
        "state (b) 自由文字列 / state (c) 空 は drift 対象外 (契約 v1.2 §1-3)。"
        "★ gate にはしない (可視化のみ)。0 になっても出し続ける。\n"
    )
    if not drift_by_cat:
        out.append("(全カテゴリで drift ゼロ)\n")
    else:
        out.append("| category | drift |\n|---|---:|\n")
        for cat in sorted(drift_by_cat.keys()):
            out.append(f"| {cat} | {drift_by_cat[cat]} |\n")

    # 7. rarity 生値焼き付き検知 (2026-08-13 追加)
    #    2026-08-13 の実害 (cert158452539: rarity_ebay='L★' → 禁止文字除去で 'L' の1文字) と
    #    同型の値が C:Rarity に出ていないかを毎日可視化。§6 と同じく可視化のみ・gate にしない。
    total_raw = sum(v["raw_stamped"] for v in rarity_by_cat.values())
    total_md = sum(v["map_drift"] for v in rarity_by_cat.values())
    out.append(
        f"\n## 7. rarity 生値焼き付き検知 (絶対数・毎日出す) — "
        f"raw_stamped 合計 {total_raw} 件 / map_drift 合計 {total_md} 件\n"
    )
    out.append(
        "- **raw_stamped** = specs.rarity_ebay が公式生コードのまま (= 変換されていない)。"
        "'U' / 'LR+' / 'SPカード' 等がそのまま C:Rarity に出る = 2026-08-13 実害と同型。**要対応**。\n"
        "- **map_drift** = derive_rarity_ebay(cat, specs.rarity) ≠ stored。"
        "yaml/filter_map が旧短縮コードのままだと大量に出る (= yaml 未同期の指標)。\n"
        "★ は公式 rarity 語彙に無い刷り違いマーカーなので落としてから引く"
        "(公式 dbs-cardgame.com/fw の rarity filter = L/C/UC/R/SR/SCR/PR の 7 値, 2026-08-13 実取得)。\n"
    )
    if not rarity_by_cat:
        out.append("(全カテゴリでゼロ)\n")
    else:
        out.append("| category | raw_stamped | map_drift |\n|---|---:|---:|\n")
        for cat in sorted(rarity_by_cat.keys()):
            v = rarity_by_cat[cat]
            out.append(f"| {cat} | {v['raw_stamped']} | {v['map_drift']} |\n")
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cat", default="pokemon_tcg",
                    help="category (pokemon_tcg 既定 / 'all' で全カテゴリ)")
    ap.add_argument("--out", default=None, help="md 出力先 (省略時 stdout)")
    args = ap.parse_args()
    categories = None if args.cat == "all" else [args.cat]

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    cat_s = ",".join(categories) if categories else "all"
    ts = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{_START_MARK} {ts} (cat={cat_s}) ===")

    (era_mismatch, inconsistent, none_list, name_desync,
     empty_by_cat, drift_by_cat, rarity_by_cat) = audit(categories)
    report = render(era_mismatch, inconsistent, none_list, name_desync,
                    empty_by_cat, drift_by_cat, rarity_by_cat, categories or [])
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"wrote {args.out}")
    else:
        print(report)

    # ── base→_pN name 誤伝播の継続検出 (2026-08-01 name-guard, WARN のみ・自動修正なし) ──
    #   name_jp≠base なのに name_en/character_name が base と一致する _pN = 別カードに別キャラ名。
    #   これが >0 は name_guard.propagate_name_fields を通さない別経路の再混入。
    import os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from name_guard import find_variant_name_violations, find_facet_n1_candidates  # noqa: E402
    _conn = sqlite3.connect(str(DB_PATH))
    _cats = categories or ["pokemon_tcg", "one_piece_tcg", "gundam_tcg",
                           "dragonball_scg", "yugioh_tcg"]
    name_viol = []
    for _cat in _cats:
        name_viol += find_variant_name_violations(_conn, _cat)
    if name_viol:
        print(f"\n⚠️ [name-guard] base→_pN 名前誤伝播 {len(name_viol)} 件 (WARN, 自動修正なし):")
        for v in name_viol[:20]:
            print(f"    {v['product_id']}: name_jp={v['name_jp']!r} ≠ base={v['base_name_jp']!r} "
                  f"だが name_en/char が base と一致 (name_en={v['name_en']!r})")

    # set_name_ebay N:1 誤マップ候補 (WARN のみ・自動修正なし。allowlist=facet_n1_allowlist.yaml)
    facet_n1 = []
    for _cat in _cats:
        facet_n1 += [{**x, "category": _cat} for x in find_facet_n1_candidates(_conn, _cat)]
    _conn.close()
    if facet_n1:
        print(f"\n⚠️ [facet-N:1] allowlist 外の N:1 誤マップ候補 {len(facet_n1)} facet "
              f"(WARN・自動修正なし・一括null禁止。per-facet で窓口 GO 要):")
        for x in facet_n1[:30]:
            print(f"    {x['set_name_ebay']!r} <- stranger {list(x['strangers'].items())[:4]}")

    # 完走マーカー (末尾に必ず出す。ログの grep でこれが無ければ途中死亡).
    print(
        f"{_END_MARK}: era={len(era_mismatch)} inconsistent={len(inconsistent)} "
        f"none_src={len(none_list)} name_desync={len(name_desync)} "
        f"name_propagate_viol={len(name_viol)} facet_n1_candidates={len(facet_n1)} "
        f"canonical_drift={sum(drift_by_cat.values())} "
        f"rarity_raw_stamped={sum(v['raw_stamped'] for v in rarity_by_cat.values())} "
        f"rarity_map_drift={sum(v['map_drift'] for v in rarity_by_cat.values())} ==="
    )


if __name__ == "__main__":
    main()
