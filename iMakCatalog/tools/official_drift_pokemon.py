"""ポケモン公式と catalog を突き合わせる (2026-09-03 新設).

One Piece 版 (`official_drift_check.py`) の同型。**公式を今その場で取り直す**。

## 突合のしかた

公式の `resultAPI.php?pg=<弾コード>` は、その弾のカードを JSON で返す:

    {"cardID": "43843",
     "cardThumbFile": "/assets/images/card_images/large/SV3/043843_P_NAZONOKUSA.jpg",
     "cardNameViewText": "ナゾノクサ"}

**印刷番号は返らない**ので、画像のファイル名 (`043843_P_NAZONOKUSA.jpg`) を鍵にする。
catalog も同じ URL を images に持っているので、1対1で突き合わせられる。

見るのは2つ:
    A. 公式に在るのに catalog に無い (画像ファイル名で照合)  → 取り込み漏れ
    B. カード名が違う                                        → parse ミス or 公式の訂正

★弾コードは catalog の product_id の頭から作る (公式 `pg` と同じ綴り)。
★fail-closed: 取れなかった弾は「差分0」ではなく **取得失敗** として数える。
★差分が残っている弾は **次回も必ず先に見る** (順番から外れて緑にならないように)。

使い方:
    python tools/official_drift_pokemon.py            # 最後に見た順に 5弾
    python tools/official_drift_pokemon.py --pg SV3   # 弾を指定
    python tools/official_drift_pokemon.py --n 30
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
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

API = "https://www.pokemon-card.com/card-search/resultAPI.php"
STATE = Path("C:/dev/iMak_data/catalog/_official_drift_pokemon_state.json")
UA = {"User-Agent": "Mozilla/5.0"}
CAT = "pokemon_tcg"
KNOWN_IDS: dict = {}
SLEEP = 0.6


def _fetch(pg: str, page: int) -> dict:
    u = API + "?" + urllib.parse.urlencode(
        {"pg": pg, "page": page, "regulation_sidebar_form": "all"})
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _clean(t: str) -> str:
    """名前の比較前に **書き方**だけ畳む (中身は変えない).

    2026-09-03 初回走査で「名前が違う」と出た 40件は catalog の誤りではなく読み取りの粗さ:
      `フェローチェ&amp;マッシブーンGX`                     … 実体参照を戻していない
      `シェイミ<span class="pcg pcg-prismstar"></span>`   … 公式は ◇(プリズムスター) を span で出す
    """
    t = re.sub(r"<[^>]+>", "", html.unescape(t or ""))
    return t.replace("＆", "&").replace("　", " ").strip()


def official_cards(pg: str) -> list[dict]:
    """その弾の公式カード [{cardID, name, img}]."""
    d = _fetch(pg, 1)
    out = list(d.get("cardList") or [])
    for page in range(2, int(d.get("maxPage", 1)) + 1):
        time.sleep(SLEEP)
        out.extend(_fetch(pg, page).get("cardList") or [])
    return [{"id": str(c.get("cardID") or ""),
             "name": _clean(c.get("cardNameViewText") or c.get("cardNameAltText") or ""),
             "img": (c.get("cardThumbFile") or "").rsplit("/", 1)[-1]} for c in out]


# ★catalog に **登録しないと決めてある**もの (CLAUDE.md「番号が無いカードは登録しない」)。
#   公式には在るが、印刷番号が無く product_id を作れない = 構造的に入らない。
#   差分に数えると永久に赤のままになるので、別枠で数える (隠さない)。
_OUT_OF_SCOPE = re.compile(r"^基本.*エネルギー$")


def _is_out_of_scope(name: str) -> bool:
    return bool(_OUT_OF_SCOPE.match((name or "").strip()))


def catalog_rows(conn, pg: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT product_id, name, name_jp, images FROM products "
        "WHERE category=? AND (product_id=? OR product_id LIKE ?)",
        (CAT, pg, pg + "-%")).fetchall()


def check_pg(conn, pg: str) -> dict:
    cards = official_cards(pg)
    if not cards:
        return {"pg": pg, "fetched": 0, "error": "公式が0件を返した (弾コードが違う?)"}
    rows = catalog_rows(conn, pg)
    by_img, names = {}, set()
    for r in rows:
        for u in json.loads(r["images"] or "[]"):
            by_img[str(u).rsplit("/", 1)[-1]] = r
        names.add((r["name"] or "").strip())
        names.add((r["name_jp"] or "").strip())
    # ★cardID でも引けるようにする (2026-09-04)。
    #   画像のファイル名だけで照合すると、catalog が別の刷りの絵を持っている行や
    #   `cardID-20514` 形の索引行を「無い」と誤検出する (429件のうち大半がこれだった)。
    #   公式と同じ id なので、これが在れば **そのカードは catalog に在る**。
    known_ids = KNOWN_IDS.get(pg)
    if known_ids is None:
        known_ids = set()
        for (pid, url) in conn.execute(
                "SELECT product_id, IFNULL(source_url,'') FROM products WHERE category=?", (CAT,)):
            if "details.php/card/" in url:
                known_ids.add(url.rstrip("/").rsplit("/", 1)[-1])
            if (pid or "").startswith("cardID-"):
                known_ids.add(pid.split("-", 1)[1])
        KNOWN_IDS["*"] = known_ids
        KNOWN_IDS[pg] = known_ids

    missing, name_ng, excluded, reprint = [], [], [], []
    for c in cards:
        r = by_img.get(c["img"])
        if r is None and c["id"] in known_ids:
            continue                      # cardID で catalog に在る (絵の刷り違い等)
        if r is None:
            if _is_out_of_scope(c["name"]):
                excluded.append(c)          # 差分ではない (登録しないと決めてある)
            elif c["name"] in names:
                # 同じ弾に **同じ名前の行が在る** = 別刷り (公式が絵を差し替え/再録した)。
                # catalog は 1カード1行なので「カードが無い」わけではない。別枠で数える。
                reprint.append(c)
            else:
                missing.append(c)
            continue
        if c["name"] and c["name"] not in {_clean(r["name"] or ""), _clean(r["name_jp"] or "")}:
            name_ng.append((c, r["product_id"], r["name_jp"] or r["name"]))
    return {"pg": pg, "fetched": len(cards), "rows": len(rows),
            "missing": missing, "name_ng": name_ng, "excluded": excluded,
            "reprint": reprint}


def pg_of(product_id: str) -> str:
    """product_id → 公式の弾コード (`pg`).

    ★**最後の `-` より前が弾コード**。頭だけを取ると古い弾を落とす (2026-09-03):
        BW1-Bb-001 → `BW1-Bb`   (`BW1` では公式が0件を返す)
        DPt1-B-001 → `DPt1-B`   L1-Bhg-001 → `L1-Bhg`   M-P-001 → `M-P`
    公式の画像フォルダ名 (`.../large/BW1-Bb/027101_P_KURUMIRU.jpg`) と一致する。
    """
    pid = (product_id or "").split("_")[0]
    return pid.rsplit("-", 1)[0] if "-" in pid else ""


def all_pgs(conn) -> list[str]:
    """catalog に在る弾コード。数の多い順."""
    c = Counter()
    for (pid,) in conn.execute("SELECT product_id FROM products WHERE category=?", (CAT,)):
        pg = pg_of(pid)
        if pg and pg != "cardID":
            c[pg] += 1
    return [k for k, _ in c.most_common()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg", help="弾コードを指定")
    ap.add_argument("--n", type=int, default=5, help="見る弾の数 (既定 5)")
    a = ap.parse_args()

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    conn = sqlite3.connect(str(api._DB_PATH))
    conn.row_factory = sqlite3.Row

    if a.pg:
        targets = [a.pg]
    else:
        pgs = all_pgs(conn)
        # ★差分が残っている弾を必ず先に (緑に見せない)
        pending = [p for p in pgs if (state.get(p) or {}).get("ng")]
        rest = sorted([p for p in pgs if p not in pending],
                      key=lambda p: (state.get(p) or {}).get("at", ""))
        targets = (pending + rest)[:max(a.n, len(pending))]

    now = datetime.now().isoformat(timespec="seconds")
    print(f"=== 公式との突合 (pokemon / {len(targets)}弾) {now} ===")
    total = ng = fail = exc = rep = 0
    for pg in targets:
        try:
            res = check_pg(conn, pg)
        except Exception as e:
            fail += 1
            print(f"  ✗ pg={pg} 取得失敗: {e}")
            continue
        if res.get("error"):
            fail += 1
            print(f"  ✗ pg={pg} {res['error']}")
            continue
        n = len(res["missing"]) + len(res["name_ng"])
        exc += len(res.get("excluded") or [])
        rep += len(res.get("reprint") or [])
        total += res["fetched"]
        ng += n
        print(f"  {'OK ' if n == 0 else '★NG'} pg={pg:8s} 公式 {res['fetched']:4d}枚 "
              f"/ catalog {res['rows']:4d}行 / 差分 {n}")
        for c in res["missing"][:5]:
            print(f"      [欠落] {c['name']} (cardID {c['id']} / {c['img']})")
        for c, pid, got in res["name_ng"][:5]:
            print(f"      [名前] {pid} 公式={c['name']!r} catalog={got!r}")
        state[pg] = {"at": now, "ng": n}
        time.sleep(SLEEP)
    conn.close()

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    left = [p for p, v in state.items() if v.get("ng")]
    print("")
    if fail:
        print(f"⚠️ 取得できなかった弾 {fail} 件 (= 検査できていない。正常ではない)")
    print(f"突合 {total}枚 / 差分 {ng}件 / 別刷り {rep}枚 / 対象外 {exc}枚 / "
          f"**差分が残っている弾 {len(left)}** {left[:8]}")


if __name__ == "__main__":
    main()
