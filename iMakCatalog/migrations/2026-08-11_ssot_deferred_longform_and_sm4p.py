"""SSOT契約 deferred 反映 (Advisor GO 2026-08-11) — 22set長形 + SM4p canonical

依頼: 2026-08-11_tcg_ssot_apply_result_and_deferred_response.md [IMPLEMENT-GO]
  §1 表記規約: master に2形ある set は **長形(人が読める方)** を採用。
  §4 SM4p 121件(SM-P-145含): canonical `Sm4+: GX Battle Boost`。327→206。

方式: 現値ベース。跨ぎ衝突なし(全 pokemon 実在 set)。backup+dry-run+before-JSON。
"""
from __future__ import annotations
import json, re, shutil, sqlite3, sys
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass

DB = "C:/dev/iMak_data/catalog/products.sqlite"
MASTER = str(Path(__file__).resolve().parent.parent / "data/ebay_filter_masters/tcg.json")
SRC_TAG = "ssot_canonical_upgrade_20260810"
SM4P_CANON = "Sm4+: GX Battle Boost"
BEFORE = Path("C:/dev/iMak_data/catalog/ssot_deferred_before_20260811.json")
master = list(json.load(open(MASTER, encoding="utf-8"))["aspects"]["Set"]["values"])
def norm(s):
    if not s: return ""
    s = s.strip().lower(); s = re.sub(r"[\u3000\s]+", " ", s); s = s.replace("＆", "&")
    return re.sub(r"[^\w& ]", "", s).strip()
def tail(s):
    if not s: return ""
    for sep in ("\u2014", "\u2015", "—", ": ", " - "):
        if sep in s: s = s.split(sep)[-1]
    return norm(re.sub(r"^[A-Za-z0-9+\-]{1,8}:\s*", "", s))
mfull = {norm(m) for m in master}; mtail = defaultdict(list)
for m in master: mtail[tail(m)].append(m)


def collect(con):
    tg = []
    # §1 長形: multi-candidate set の現値行を長形へ
    for r in con.execute("select id, product_id, specs, set_name_official off from products where category='pokemon_tcg'"):
        d = json.loads(r["specs"]) if r["specs"] else {}
        cur = d.get("set_name_ebay")
        if cur and norm(cur) not in mfull and tail(cur) in mtail and len(mtail[tail(cur)]) > 1:
            cands = mtail[tail(cur)]
            longf = [c for c in cands if not re.match(r"^[A-Za-z0-9+]{1,8}:\s", c)]
            pick = longf[0] if longf else cands[0]
            if cur != pick:
                tg.append((r["id"], r["product_id"], d, cur, pick))
    # §4 SM4p (+SM-P-145): blanked → canonical
    for r in con.execute("select id, product_id, specs from products where category='pokemon_tcg' and (product_id like 'SM4p-%' or product_id='SM-P-145')"):
        d = json.loads(r["specs"]) if r["specs"] else {}
        if d.get("set_name_ebay") != SM4P_CANON:
            tg.append((r["id"], r["product_id"], d, d.get("set_name_ebay"), SM4P_CANON))
    return tg


def main(apply):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    tg = collect(con)
    print(f"=== deferred 反映 ({'APPLY' if apply else 'DRY-RUN'}): {len(tg)} 行 ===")
    for k, n in Counter(f"{t[3]!r}->{t[4]!r}" for t in tg).most_common(20): print(f"    {n:4d} {k}")
    if not apply:
        con.close(); return
    bk = Path(DB).with_name(Path(DB).name + ".pre_ssot_deferred_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB, bk); print(f"backup: {bk.name}")
    BEFORE.write_text(json.dumps([{"id": t[0], "product_id": t[1], "before": t[3], "after": t[4]} for t in tg], ensure_ascii=False), encoding="utf-8")
    now = datetime.now().isoformat()
    for _id, pid, d, before, canon in tg:
        d["set_name_ebay"] = canon; d["set_name_ebay_source"] = SRC_TAG
        con.execute("update products set specs=?, updated_at=? where id=?", (json.dumps(d, ensure_ascii=False), now, _id))
    con.commit(); con.close()
    print(f"=== done: {len(tg)} 行 ===")


if __name__ == "__main__":
    main("--apply" in sys.argv)
