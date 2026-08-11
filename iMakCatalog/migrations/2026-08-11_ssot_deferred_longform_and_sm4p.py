"""SSOT契約 deferred 反映 (Advisor 2026-08-11 [IMPLEMENT-GO]) — 22set長形 + SM4p canonical.

依頼: 2026-08-11_tcg_ssot_apply_result_and_deferred_response.md
  §1 表記規約22セット → **長形** (`Sword & Shield - Lost Origin` 等):
     master に code形 `Swsh11:` と長形 `Sword & Shield - Lost Origin` が両在するセットは、
     人が読める **長形** を採る。長形が bare (例 `Astral Radiance`) のみの場合は bare を採る。
  §4 SM4p 121件 (SM4p-* 120 + SM-P-145 1): canonical `Sm4+: GX Battle Boost`
     (master 実在確定・2026-08-10 filter_map 571 の tail-only 誤値の解消)。
     327 blanked → 206 blanked に減る (ウルトラサン/ムーン/フォース の 206件は master canonical 無し=空欄維持)。

方式: 現値ベース + master 突合 + 期待件数の安全 guard。跨ぎ衝突なし (全 pokemon_tcg 実在 set)。
      backup + dry-run + before-JSON。冪等 (再実行しても差分ゼロ)。

実行:
  python migrations/2026-08-11_ssot_deferred_longform_and_sm4p.py           # dry-run
  python migrations/2026-08-11_ssot_deferred_longform_and_sm4p.py --apply   # commit
"""
from __future__ import annotations
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "C:/dev/iMak_data/catalog/products.sqlite"
MASTER = str(Path(__file__).resolve().parent.parent / "data/ebay_filter_masters/tcg.json")
BEFORE_JSON = Path("C:/dev/iMak_data/catalog/ssot_deferred_before_20260811.json")

# 分離タグ (Task ごとに audit 可能)。7/31 の blanked 系タグは温存 (SM4p 更新で自動消える)。
SRC_TAG_LONG = "ssot_canonical_dual_long_20260811"       # §1
SRC_TAG_SM4P = "sm4p_canonical_populate_20260811"        # §4
SM4P_CANON = "Sm4+: GX Battle Boost"
SM4P_EXPECTED = 121                                      # 120 SM4p + 1 SM-P-145

# 7/31 blanked 全体 (327) と SM4p 分 (121) を差し引いた期待残数 (§4 の副作用)
BLANKED_TAG = "blanked_by_ultra_prism_mismap_20260731"
BLANKED_EXPECTED_AFTER = 206                             # 327 - 121

master = list(json.load(open(MASTER, encoding="utf-8"))["aspects"]["Set"]["values"])


def norm(s: str) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"[　\s]+", " ", s)
    s = s.replace("＆", "&")
    return re.sub(r"[^\w& ]", "", s).strip()


def tail(s: str) -> str:
    if not s:
        return ""
    for sep in ("—", "―", "—", ": ", " - "):
        if sep in s:
            s = s.split(sep)[-1]
    return norm(re.sub(r"^[A-Za-z0-9+\-]{1,8}:\s*", "", s))


def is_code_form(v: str) -> bool:
    return bool(re.match(r"^[A-Za-z]{1,6}\d+[A-Za-z+]*:\s", v or ""))


mfull = {norm(m) for m in master}
mtail: dict[str, list[str]] = defaultdict(list)
for m in master:
    mtail[tail(m)].append(m)


def _pick_long(cands: list[str]) -> str:
    """長形選択: 非 code 形を優先。複数あれば ' - ' (regular dash) 付きを優先、なければ bare。"""
    longs = [c for c in cands if not is_code_form(c)]
    if not longs:
        return cands[0]
    with_dash = [c for c in longs if " - " in c]
    return with_dash[0] if with_dash else longs[0]


def collect_longform(con: sqlite3.Connection) -> list[dict]:
    """§1: 現値が master に無く、tail が master の dual 群にマッチする行を長形にする."""
    out = []
    for r in con.execute(
        "select id, product_id, specs from products where category='pokemon_tcg'"
    ):
        specs = json.loads(r["specs"]) if r["specs"] else {}
        cur = specs.get("set_name_ebay")
        if not cur:
            continue
        if norm(cur) in mfull:
            continue
        cands = mtail.get(tail(cur))
        if not cands or len(cands) < 2:
            continue
        pick = _pick_long(cands)
        if cur == pick:
            continue
        out.append({
            "id": r["id"], "product_id": r["product_id"],
            "specs_dict": specs, "before": cur, "after": pick,
        })
    return out


def collect_sm4p(con: sqlite3.Connection) -> list[dict]:
    """§4: SM4p-* + SM-P-145 を canonical `Sm4+: GX Battle Boost` に."""
    out = []
    for r in con.execute(
        "select id, product_id, specs from products "
        "where category='pokemon_tcg' and (product_id like 'SM4p-%' or product_id='SM-P-145')"
    ):
        specs = json.loads(r["specs"]) if r["specs"] else {}
        if specs.get("set_name_ebay") == SM4P_CANON:
            continue
        out.append({
            "id": r["id"], "product_id": r["product_id"],
            "specs_dict": specs, "before": specs.get("set_name_ebay"), "after": SM4P_CANON,
        })
    return out


def collect_b_layer_updates(con: sqlite3.Connection) -> list[dict]:
    """§4 の付随: SM4p+SM-P-145 の b_layer_status を unverified → verified_auto に."""
    out = []
    try:
        rows = con.execute(
            "select b.product_id_ref, b.category, b.product_code, b.status "
            "from b_layer_status b join products p on p.id=b.product_id_ref "
            "where b.field='set_name_ebay' and b.status='unverified' "
            "and p.category='pokemon_tcg' "
            "and (p.product_id like 'SM4p-%' or p.product_id='SM-P-145')"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    for r in rows:
        out.append({"product_id_ref": r[0], "product_code": r[2]})
    return out


def main(apply: bool) -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    tgt_long = collect_longform(con)
    tgt_sm4p = collect_sm4p(con)
    tgt_bl = collect_b_layer_updates(con)

    print(f"=== SSOT deferred ({'APPLY' if apply else 'DRY-RUN'}) ===")
    print(f"  §1 longform 対象行: {len(tgt_long)}")
    for k, n in Counter(f"{t['before']!r}->{t['after']!r}" for t in tgt_long).most_common(20):
        print(f"      {n:4d} {k}")
    print(f"  §4 SM4p 対象行:     {len(tgt_sm4p)} (期待={SM4P_EXPECTED} 又は 0=既済)")
    print(f"  §4 b_layer_status unverified→verified_auto: {len(tgt_bl)} 行")

    # 期待件数 safety guard (§4 は 121 か 0 のどちらか)
    if tgt_sm4p and len(tgt_sm4p) != SM4P_EXPECTED:
        print(f"\n⛔ ABORT: SM4p 対象数 {len(tgt_sm4p)} ≠ 期待 {SM4P_EXPECTED}. 別経路変更の疑い。")
        sys.exit(2)

    if not apply:
        print("dry-run 終了。--apply で実行。")
        return

    if not (tgt_long or tgt_sm4p or tgt_bl):
        print("差分なし (冪等 no-op)。")
        return

    bk = Path(DB).with_name(
        Path(DB).name + ".pre_ssot_deferred_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB, bk)
    print(f"backup: {bk.name}")

    BEFORE_JSON.write_text(
        json.dumps(
            [{"section": "longform", **{k: v for k, v in t.items() if k != "specs_dict"}}
             for t in tgt_long]
            + [{"section": "sm4p", **{k: v for k, v in t.items() if k != "specs_dict"}}
               for t in tgt_sm4p]
            + [{"section": "b_layer", **t} for t in tgt_bl],
            ensure_ascii=False, indent=1),
        encoding="utf-8")

    now = datetime.now().isoformat()
    for t in tgt_long:
        d = t["specs_dict"]
        d["set_name_ebay"] = t["after"]
        d["set_name_ebay_source"] = SRC_TAG_LONG
        con.execute("update products set specs=?, updated_at=? where id=?",
                    (json.dumps(d, ensure_ascii=False), now, t["id"]))
    for t in tgt_sm4p:
        d = t["specs_dict"]
        d["set_name_ebay"] = t["after"]
        d["set_name_ebay_source"] = SRC_TAG_SM4P
        con.execute("update products set specs=?, updated_at=? where id=?",
                    (json.dumps(d, ensure_ascii=False), now, t["id"]))
    for t in tgt_bl:
        con.execute(
            "update b_layer_status set status='verified_auto', oracle=?, note=?, checked_at=? "
            "where product_id_ref=? and field='set_name_ebay'",
            (SRC_TAG_SM4P, "SM4p canonical populated (master 実在 'Sm4+: GX Battle Boost')",
             now, t["product_id_ref"]))
    con.commit()

    # 事後確認 (副作用: BLANKED_TAG が SM4p 更新で 121 減っているはず)
    n_blank = con.execute(
        "select count(*) from products where json_extract(specs,'$.set_name_ebay_source')=?",
        (BLANKED_TAG,)).fetchone()[0]
    con.close()
    print(f"=== done ===")
    print(f"  longform 反映: {len(tgt_long)}")
    print(f"  SM4p 反映:     {len(tgt_sm4p)}")
    print(f"  b_layer 反映:  {len(tgt_bl)}")
    print(f"  {BLANKED_TAG} 残: {n_blank} (期待 {BLANKED_EXPECTED_AFTER})")


if __name__ == "__main__":
    main("--apply" in sys.argv)
