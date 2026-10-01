# -*- coding: utf-8 -*-
"""ワンピの版の対応表を **絵** で作る (bandai-tcg-plus の行 → 公式 onepiece-cardgame の行).

依頼: `requests/2026-10-01_onepiece_variant_md5_map_go.md` [IMPLEMENT-GO]

## md5 では決まらない (2026-10-01 実測)

2つの公式は **同じ絵を別の大きさで配っている**ので、バイト列の md5 は一致しない:

    bandai   OP06-022.png   162,089 bytes  640x894
    公式     OP06-022.png   125,572 bytes  600x838   ← 同じ絵なのに md5 は別

そこで **絵を 16x16 の白黒に落として平均より明るいかの 256bit** にして比べる。
同じ絵なら大きさが違っても **差 0**、別の絵なら 58 以上 離れた (実測):

    bandai 通常版 vs 公式 通常版        0/256   ← 同じ絵
    bandai _p     vs 公式 _p1           0/256   ← 同じ絵 (これが欲しい対応)
    bandai _p     vs 公式 _p2         128/256
    bandai 通常版 vs 公式 _p2          58/256

## 決め方 (fail-closed)

同じカード番号の中で **差が `MAX_DIST` 以下の公式行が1つだけ**、かつ
**2番目が `MIN_GAP` 以上 離れている**時だけ採る。それ以外は空のまま。

## 途中保存

絵の指紋は `_op_variant_hash.json` に1枚ずつ足す。**再実行は残りだけ**。
落とした絵は共有側の `C:/dev/iMak_data/catalog/_raw/op_variant_imgs/` に置く (bandai 側は消えると取り直せない)。

実行:
    python tools/op_variant_image_map.py            # 指紋を集めて表を作る
    python tools/op_variant_image_map.py --map-only # 集めずに表だけ作り直す
    python tools/op_variant_image_map.py --limit 50 # 少しだけ試す
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
import time
import urllib.error
import re
import urllib.request
from datetime import datetime
from pathlib import Path

DB = "C:/dev/iMak_data/catalog/products.sqlite"
DATA = Path("C:/dev/iMak_data/catalog")
STATE = DATA / "_op_variant_hash.json"
OUT = DATA / "op_variant_official_map.json"
# ★共有側の倉庫に置く。worktree の中は毎朝の zip に入らない (2026-09-30 backup_gaps)
RAW = DATA / "_raw" / "op_variant_imgs"
CATEGORY = "one_piece_tcg"
MAX_DIST = 4      # 同じ絵と見なす上限 (実測は 0。にじみに少し余裕)
MIN_GAP = 16      # 2番目との差。これより近いものが2つ在れば決めない
UA = {"User-Agent": "Mozilla/5.0"}

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def ahash(raw: bytes) -> str:
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("L").resize((16, 16))
    px = list(im.tobytes())
    avg = sum(px) / len(px)
    bits = "".join("1" if p > avg else "0" for p in px)
    return f"{int(bits, 2):064x}"


def dist(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _base(pid: str) -> str:
    """カード番号 (版の印を落とした形)。`OP06-022_p` → `OP06-022`."""
    head = pid.split("_", 1)[0]
    return head


def set_code(name: str) -> str | None:
    """収録名から弾コードを取る。`[OP-06]` も `【OP-06】` も `OP06` にする.

    bandai は英語名 / 公式は日本語名なので、名前そのままでは突き合わせられない。
    """
    m = re.search(r"[\[【]\s*([A-Z]{2,4}-?\d{1,2})\s*[\]】]", name or "")
    if m:
        return m.group(1).replace("-", "")
    n = (name or "").strip()
    if "プロモーション" in n or "romotion" in n or "PROMOTION" in n:
        return "PROMO"
    return None


def rows() -> list[tuple[str, str, str]]:
    """(product_id, 出所の種類, 絵の場所) を返す."""
    c = sqlite3.connect(DB, timeout=120)
    out = []
    for pid, src, im, sname in c.execute(
            "SELECT product_id, source, images, set_name_official FROM products WHERE category=?", (CATEGORY,)):
        try:
            imgs = json.loads(im or "[]")
        except ValueError:
            imgs = []
        if not isinstance(imgs, list) or not imgs:
            continue
        kind = ("official" if (src or "").startswith("opcg_official")
                else "bandai" if (src or "") == "bandai_tcg_plus" else None)
        if kind is None:
            continue
        local = next((u for u in imgs if isinstance(u, str) and not u.startswith("http")
                      and Path(u).exists()), None)
        remote = next((u for u in imgs if isinstance(u, str) and u.startswith("http")), None)
        where = local or remote
        if where:
            out.append((pid, kind, where, sname or ""))
    c.close()
    return out


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except ValueError:
            print("⚠️ 指紋の控えが読めないので作り直します")
    return {}


def collect(limit: int | None) -> dict:
    state = load_state()
    todo = [(p, k, w, n) for p, k, w, n in rows() if p not in state]
    print(f"指紋: 済み {len(state)}枚は飛ばす / 残り {len(todo)}枚")
    if limit:
        todo = todo[:limit]
    RAW.mkdir(parents=True, exist_ok=True)
    ok = ng = 0
    for i, (pid, kind, where, sname) in enumerate(todo, 1):
        try:
            if where.startswith("http"):
                raw = urllib.request.urlopen(
                    urllib.request.Request(where, headers=UA), timeout=40).read()
                if kind == "bandai":          # 消えると取り直せない方だけ残す
                    (RAW / f"{pid}.png").write_bytes(raw)
            else:
                raw = Path(where).read_bytes()
            state[pid] = {"kind": kind, "hash": ahash(raw), "src": where,
                          "set": set_code(sname)}
            ok += 1
        except (OSError, urllib.error.URLError, ValueError) as e:
            state[pid] = {"kind": kind, "hash": None, "src": where,
                          "set": set_code(sname), "error": f"{type(e).__name__}: {str(e)[:80]}"}
            ng += 1
        if i % 100 == 0 or i == len(todo):    # ★途中保存
            STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            print(f"  {i}/{len(todo)} 取得 {ok} / 失敗 {ng}", flush=True)
        if where.startswith("http"):
            time.sleep(0.15)
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return state


def build(state: dict) -> dict:
    # 弾コードは **その場で DB から引く** (指紋の控えに入っていない古い控えでも効くように)
    c = sqlite3.connect(DB, timeout=120)
    codes = {pid: set_code(sn or "") for pid, sn in c.execute(
        "SELECT product_id, set_name_official FROM products WHERE category=?", (CATEGORY,))}
    c.close()
    off, ban = {}, {}
    for pid, v in state.items():
        if not v.get("hash"):
            continue
        (off if v["kind"] == "official" else ban).setdefault(
            _base(pid), []).append((pid, v["hash"], codes.get(pid)))
    table, undecided = {}, []
    reasons = {"公式の行が無い": 0, "近い公式行が無い": 0, "近い公式行が複数": 0}
    by_set = 0
    for b, lst in ban.items():
        cands = off.get(b) or []
        for pid, h, bset in lst:
            if not cands:
                undecided.append({"product_id": pid, "why": "公式の行が無い"})
                reasons["公式の行が無い"] += 1
                continue
            scored = sorted(((dist(h, oh), opid) for opid, oh, _ in cands))
            best, second = scored[0], (scored[1] if len(scored) > 1 else (999, None))
            if best[0] > MAX_DIST:
                undecided.append({"product_id": pid, "why": "近い公式行が無い",
                                  "nearest": best[1], "dist": best[0]})
                reasons["近い公式行が無い"] += 1
            elif second[0] - best[0] < MIN_GAP:
                # ★絵が同じ公式行が2つ以上 = 同じ絵が別の商品にも入っている。
                #   その時は **収録の弾コードが合う1行**だけ採る (それでも1つに絞れなければ空)。
                near = {opid for d, opid in scored if d <= MAX_DIST}
                same = [opid for opid, _, oset in cands
                        if opid in near and bset and oset == bset]
                if len(same) == 1:
                    table[pid] = same[0]
                    by_set += 1
                else:
                    undecided.append({"product_id": pid, "why": "近い公式行が複数",
                                      "candidates": sorted(near)})
                    reasons["近い公式行が複数"] += 1
            else:
                table[pid] = best[1]
    doc = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "method": f"16x16 白黒の平均より明るいかの 256bit。差 {MAX_DIST} 以下で、"
                  f"2番目が {MIN_GAP} 以上 離れている時だけ採る (md5 は大きさが違うので使えない)",
        "owner": "CATALOG",
        "decided": len(table), "undecided": len(undecided), "why": reasons,
        "decided_by_set_code": by_set,
        "map": dict(sorted(table.items())),
        "undecided_rows": undecided,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n決まった {len(table)} / 決まらない {len(undecided)}  {reasons}")
    print("表:", OUT)
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map-only", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    state = load_state() if a.map_only else collect(a.limit)
    build(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
