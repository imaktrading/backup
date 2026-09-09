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
import unicodedata
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
    # ★NFC に寄せる (2026-09-05)。公式が互換漢字を使っている字があり、
    #   画面では同じに見えるのに一致しない (ワンピの `蓮` で実際に出た)。
    t = unicodedata.normalize("NFC", re.sub(r"<[^>]+>", "", html.unescape(t or "")))
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
             # ★別綴り (2026-09-05)。公式は「メガ」「◇」等の**印を span 画像**で出すので、
             #   タグを剥がすと文字が消える (`<span pcg-megamark>ルカリオEX` → `ルカリオEX`)。
             #   alt には印が文字で入っている (`メガルカリオEX`) ので、**どちらか一致でOK**にする。
             #   片方だけを正にすると、正しい行が2つの綴りの間で行ったり来たりする。
             "alt": _clean(c.get("cardNameAltText") or ""),
             "img": (c.get("cardThumbFile") or "").rsplit("/", 1)[-1]} for c in out]


# ★catalog に **登録しないと決めてある**もの (CLAUDE.md「番号が無いカードは登録しない」)。
#   公式には在るが、印刷番号が無く product_id を作れない = 構造的に入らない。
#   差分に数えると永久に赤のままになるので、別枠で数える (隠さない)。
_OUT_OF_SCOPE = re.compile(r"^基本.*エネルギー$")


def _is_out_of_scope(name: str) -> bool:
    return bool(_OUT_OF_SCOPE.match((name or "").strip()))


def catalog_rows(conn, pg: str) -> list[sqlite3.Row]:
    """その弾の行。**画像フォルダが一致する行**も拾う (product_id の頭と一致しないため)."""
    rows = conn.execute(
        "SELECT product_id, name, name_jp, images FROM products "
        "WHERE category=? AND (product_id=? OR product_id LIKE ? OR images LIKE ?)",
        (CAT, pg, pg + "-%", f"%/large/{pg}/%")).fetchall()
    return rows


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
            elif c["name"] in names or (c.get("alt") and c["alt"] in names):
                # 同じ弾に **同じ名前の行が在る** = 別刷り (公式が絵を差し替え/再録した)。
                # catalog は 1カード1行なので「カードが無い」わけではない。別枠で数える。
                reprint.append(c)
            else:
                missing.append(c)
            continue
        got = {_clean(r["name"] or ""), _clean(r["name_jp"] or "")}
        want = {x for x in (c["name"], c.get("alt")) if x}
        if want and not (want & got):
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
    """catalog に在る弾コード。数の多い順.

    ★**画像フォルダ**を第一の根拠にする (2026-09-05)。公式 `pg` は画像フォルダ名
    (`.../large/XY7-B/...`) と同じで、product_id の頭とは限らない
    (`XY7-B-095` は頭を取ると `XY7-B` になるが、`SV3-001` は `SV3`)。
    フォルダから取れば **公式が受け付ける綴り**そのものになる。
    フォルダが無い行だけ product_id から推定する。
    """
    c = Counter()
    for (pid, images) in conn.execute(
            "SELECT product_id, images FROM products WHERE category=?", (CAT,)):
        pg = ""
        for u in json.loads(images or "[]"):
            m = re.search(r"/large/([^/]+)/", str(u))
            if m:
                pg = m.group(1)
                break
        pg = pg or pg_of(pid)
        if pg and pg != "cardID":
            c[pg] += 1
    return [k for k, _ in c.most_common()]



def known_card_ids(conn) -> set:
    """catalog が持っている公式 cardID (source_url の末尾 / `cardID-*` の product_id)."""
    ids = set()
    for (pid, url) in conn.execute(
            "SELECT product_id, IFNULL(source_url,'') FROM products WHERE category=?", (CAT,)):
        if "details.php/card/" in url:
            ids.add(url.rstrip("/").rsplit("/", 1)[-1])
        if (pid or "").startswith("cardID-"):
            ids.add(pid.split("-", 1)[1])
    return ids


def check_all(conn) -> dict:
    """★弾を使わない総当たり (2026-09-05).

    `pg=<弾コード>` は **公式が受け付けない綴りがある** (`DP` / `XY-P` / `SMSMP` 等 7弾)。
    弾ごとの突合だけだと、その7弾は永久に「取得できない」= **検査できない穴**になる。

    公式の全カード一覧を1回取り、**画像フォルダで束ねてから**弾ごとと同じ突合をする。
    `pg` の綴りを一切使わないので、**取得できない弾が無くなる**。
    数え方 (欠落 / 別刷り / 対象外) は弾ごとの突合と同じ。
    """
    sys.path.insert(0, str(ROOT / "scrapers"))
    import pokemon_tcg as P  # noqa
    raw = P.list_all_cards()
    known = known_card_ids(conn)

    groups: dict[str, list] = {}
    for c in raw:
        m = re.search(r"/large/([^/]+)/", str(c.get("cardThumbFile") or ""))
        groups.setdefault(m.group(1) if m else "(不明)", []).append(
            {"id": str(c.get("cardID") or ""),
             "name": _clean(c.get("cardNameViewText") or c.get("cardNameAltText") or ""),
             "alt": _clean(c.get("cardNameAltText") or ""),
             "img": (c.get("cardThumbFile") or "").rsplit("/", 1)[-1]})

    miss, rep, exc, per = 0, 0, 0, {}
    for pg, cards in groups.items():
        rows = catalog_rows(conn, pg)
        by_img, names = {}, set()
        for r in rows:
            for u in json.loads(r["images"] or "[]"):
                by_img[str(u).rsplit("/", 1)[-1]] = r
            names.add((r["name"] or "").strip())
            names.add((r["name_jp"] or "").strip())
        out = []
        for c in cards:
            if c["img"] in by_img or c["id"] in known:
                continue
            if _is_out_of_scope(c["name"]):
                exc += 1
            elif c["name"] in names or (c["alt"] and c["alt"] in names):
                rep += 1
            else:
                out.append(c)
        if out:
            per[pg] = out
            miss += len(out)
    return {"fetched": len(raw), "known": len(known), "groups": len(groups),
            "missing": miss, "reprint": rep, "excluded": exc, "per": per}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pg", help="弾コードを指定")
    ap.add_argument("--n", type=int, default=5, help="見る弾の数 (既定 5)")
    ap.add_argument("--all", action="store_true",
                    help="弾を使わず、公式の全カードを cardID で突き合わせる")
    a = ap.parse_args()

    if a.all:
        conn = sqlite3.connect(str(api._DB_PATH), timeout=120)
        conn.row_factory = sqlite3.Row
        res = check_all(conn)
        conn.close()
        print(f"=== 公式の全カードと突合 (pokemon) {datetime.now().isoformat(timespec='seconds')} ===")
        print(f"  公式 {res['fetched']}枚 / {res['groups']}弾 "
              f"/ 別刷り {res['reprint']}枚 / 対象外 {res['excluded']}枚")
        for pg, cs in sorted(res["per"].items(), key=lambda x: -len(x[1])):
            print(f"  ★NG pg={pg:10s} 欠落 {len(cs)}枚")
            for c in cs[:5]:
                print(f"      [欠落] {c['name']} (cardID {c['id']} / {c['img']})")
        print("")
        print(f"**欠落 {res['missing']}枚 / 差分が残っている弾 {len(res['per'])}**")
        sys.exit(0 if not res["missing"] else 1)

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    conn = sqlite3.connect(str(api._DB_PATH), timeout=120)
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
