"""SSOT canonical UPGRADE (テストゲート版・安全部分のみ) — 2026-08-10

第1弾一括(9,465行)が既存の意図的決定と衝突しテスト5件を落としたため撤回。
本版は **現値ベースのみ**(blanked の set_code fallback は Golden Box を壊すので不採用) かつ
**既存テストを壊すセットを除外**した安全部分だけを当てる。

除外:
  - 跨ぎ衝突 (OP「25th Anniversary Collection」→ Pokemon S8a)  ← コード照合で機械除外
  - 既存の意図値 (test-backed): 'Si: Start Deck 100' / 'CP4: Premium Champion Pack'
    → Advisor 個別確認へ回す (master canonical に寄せてよいか未確定)
除外されるが別扱い: SM4p 等 blanked セット (327 テストと絡む/Golden Box 型リスク) は本版対象外。

実行: python migrations/2026-08-10_ssot_canonical_upgrade_testgated.py          # dry-run
      python migrations/2026-08-10_ssot_canonical_upgrade_testgated.py --apply
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
BEFORE_JSON = Path("C:/dev/iMak_data/catalog/ssot_canonical_testgated_before_20260810.json")
# 既存テストが守る意図値 = master に寄せず Advisor 個別確認へ
SKIP_CANON = {"Si: Start Deck 100", "CP4: Premium Champion Pack"}

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
def codekey(s):
    if not s: return None
    m = re.match(r"^([a-z]+)0*(\d+)", s.lower()); return (m.group(1), m.group(2)) if m else None
def mcode(m):
    x = re.match(r"^([A-Za-z0-9+]{1,8}):\s", m); return codekey(x.group(1)) if x else None
mfull = {norm(m) for m in master}; mtail = defaultdict(list)
for m in master: mtail[tail(m)].append(m)


def mappings(con):
    def jpcode(cat, off):
        r = con.execute("select product_id from products where category=? and set_name_official=? limit 1", (cat, off)).fetchone()
        return codekey(re.split(r"[-_]", r["product_id"])[0]) if r else None
    amap = {}
    for cat in ("one_piece_tcg", "pokemon_tcg", "gundam_tcg", "dragonball_scg"):
        for r in con.execute("select set_name_official off,json_extract(specs,'$.set_name_ebay') se from products where category=? group by off,se", (cat,)):
            cur, off = r["se"], r["off"]
            if not off or not cur: continue           # ★現値ありのみ (blanked は対象外)
            if norm(cur) in mfull: continue           # 既に canonical
            if not (tail(cur) in mtail and len(mtail[tail(cur)]) == 1): continue
            canon = mtail[tail(cur)][0]
            if cur == canon or canon in SKIP_CANON: continue
            mc, jc = mcode(canon), jpcode(cat, off)
            if mc and (not jc or jc != mc): continue   # 跨ぎ衝突除外
            amap[(cat, off)] = canon
    return amap


def main(apply):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    amap = mappings(con)
    targets = []
    for (cat, off), canon in amap.items():
        for r in con.execute("select id, product_id, specs from products where category=? and set_name_official=?", (cat, off)):
            d = json.loads(r["specs"]) if r["specs"] else {}
            if d.get("set_name_ebay") == canon or not d.get("set_name_ebay"): continue
            targets.append((r["id"], r["product_id"], cat, d, d.get("set_name_ebay"), canon))
    print(f"=== SSOT canonical UPGRADE testgated ({'APPLY' if apply else 'DRY-RUN'}) ===")
    print(f"  マッピング {len(amap)} set / 更新対象 {len(targets)} 行 (SKIP: {sorted(SKIP_CANON)})")
    if not apply:
        for k, n in Counter(f"{t[4]!r}->{t[5]!r}" for t in targets).most_common(8): print(f"    {n:5d} {k}")
        con.close(); return
    bk = Path(DB).with_name(Path(DB).name + ".pre_ssot_testgated_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(DB, bk); print(f"backup: {bk.name}")
    BEFORE_JSON.write_text(json.dumps([{"id": t[0], "product_id": t[1], "before": t[4], "after": t[5]} for t in targets], ensure_ascii=False), encoding="utf-8")
    now = datetime.now().isoformat(); n = 0
    for _id, pid, cat, d, before, canon in targets:
        d["set_name_ebay"] = canon; d["set_name_ebay_source"] = SRC_TAG
        con.execute("update products set specs=?, updated_at=? where id=?", (json.dumps(d, ensure_ascii=False), now, _id)); n += 1
    con.commit(); con.close()
    print(f"=== done: {n} 行 UPGRADE ===")


if __name__ == "__main__":
    main("--apply" in sys.argv)
