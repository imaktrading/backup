"""公式サイトを**今その場で**取り直して、catalog の値とズレていないか見る (2026-09-02 新設).

## なぜ要るか

catalog は取り込んだ時点で終わりで、**後から公式が直しても気づけない**。
取り込み時の parse ミスも、以後だれも見ない。2026-09-02 にユーザー指摘:
「カタログの精度大丈夫？」— 大丈夫だと言うには、**公式と突き合わせた証跡**が要る。

1丁目1番地の判定基準どおり、**保存値 (dump / DB) を根拠にしない**。毎回 live を叩く。

## やり方 (One Piece)

公式カードリストは弾 (series) 単位のページなので、1回の fetch で ~150枚を突合できる。
弾を **最後に見た順** に回すので、全 62 弾が順に検査される (state は共有領域に置く)。

    公式の1枚 = (券面番号, レアリティ, 種別, カード名, 収録商品名)
    catalog 側 = source に opcg_official を含み、set_name_official が一致し、
                 product_id の頭が券面番号の行

見るのは3つ:
    A. 公式に在るのに catalog に無い   → 取り込み漏れ (新弾/追加収録)
    B. カード名が違う                  → parse ミス or 公式の訂正
    C. レアリティが違う                → 同上

★変種 (`_p1` 等) は catalog 都合の枝番なので、**番号+商品名の組**で照合する。
★fail-closed: ページが取れなければ「異常0」ではなく **取得失敗** として報告する
  (取れなかったのを正常と書かない)。

使い方:
    python tools/official_drift_check.py                 # 最後に見た順に 3弾
    python tools/official_drift_check.py --series 550112 # 弾を指定
    python tools/official_drift_check.py --n 10          # 弾数を変える
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import sys
import unicodedata
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import api  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LIST_URL = "https://www.onepiece-cardgame.com/cardlist/?series={sid}"
STATE = Path("C:/dev/iMak_data/catalog/_official_drift_state.json")
UA = {"User-Agent": "Mozilla/5.0"}
CATEGORY = "one_piece_tcg"


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def series_ids(html: str) -> list[str]:
    return [v for v, _ in re.findall(r'<option[^>]*value="(\d+)"[^>]*>\s*([^<]+?)\s*</option>', html)]


def _norm(t: str) -> str:
    """比べる前に **書き方の違い**だけ畳む (中身は変えない).

    2026-09-03: 初回の全弾走査で「差分」に出た 4件は catalog の誤りではなく、
    こちらの読み取りの粗さだった:
      `キッド&amp;キラー` … HTML 実体参照を戻していなかった
      `ホーディ＆ヒョウゾウ` … 全角 ＆ と半角 & の違い
    数字を出すツールが誤検出を出すと、直す側が振り回される。ここで畳む。
    """
    # ★2026-09-05: 公式が **互換漢字**を使っている字がある
    #   (`蓮` ではなく `蓮`。画面では同じ「蓮」に見える)。
    #   NFC に寄せると同じ字になる。これで `EB04-049 指銃 黄蓮` の誤検出が消える。
    t = unicodedata.normalize("NFC", html.unescape(t or ""))
    for a, b in (("＆", "&"), ("’", "'"), ("！", "!"), ("　", " "),
                 # 2026-09-03: 全角/波ダッシュ/引用符の違いだけで「名前が違う」と出ていた
                 #   (`モンキー・Ｄ・ルフィ` ↔ `モンキー・D・ルフィ` / `〜` ↔ `～` 等)。
                 #   表記ゆれ自体は監査 §name_propagate が別に見張るので、ここでは畳む。
                 ("Ｄ", "D"), ("〜", "～"), ("”", '"'), ("“", '"'), ("‟", '"')):
        t = t.replace(a, b)
    return t.strip()


def parse_cards(page: str) -> list[dict]:
    """公式ページ → [{no, rarity, type, name, get_info}]  (重複は畳む)."""
    out, seen = [], set()
    for b in re.split(r'(?=<dl class="modalCol")', page)[1:]:
        m_info = re.search(r'class="infoCol">(.*?)</div>', b, re.S)
        m_name = re.search(r'class="cardName">([^<]+)<', b)
        m_get = re.search(r'class="getInfo"><h3>[^<]*</h3>(.*?)</div>', b, re.S)
        if not (m_info and m_name):
            continue
        cells = [re.sub(r"<[^>]+>", "", x).strip()
                 for x in re.findall(r"<span>(.*?)</span>", m_info.group(1))]
        if not cells:
            continue
        card = {
            "no": cells[0],
            "rarity": cells[1] if len(cells) > 1 else "",
            "type": cells[2] if len(cells) > 2 else "",
            "name": _norm(m_name.group(1)),
            "get_info": _norm(re.sub(r"<[^>]+>", " ", m_get.group(1))) if m_get else "",
        }
        key = (card["no"], card["name"], card["rarity"], card["get_info"])
        if key in seen:
            continue
        seen.add(key)
        out.append(card)
    return out


def check_series(conn, sid: str) -> dict:
    html = _get(LIST_URL.format(sid=sid))
    cards = parse_cards(html)
    if not cards:
        return {"sid": sid, "fetched": 0, "error": "カードを1枚も読めなかった (ページ構造が変わった?)"}

    # ★収録商品名の照合は「まとめページ」だけで行う。
    #   弾のページ (師弟の絆【OP-12】等) は全カードが同じ商品で、catalog 側は英語の弾名
    #   ('BOOSTER PACK -LEGACY OF THE MASTER- [OP-12]') で持つ = 表記が違うだけ。
    #   一方 限定商品収録カード / プロモーションカード のページは1枚ごとに商品が違うので、
    #   そこは商品ごとに行が要る (3rd ANNIVERSARY SET の欠落はこの形で出る)。
    check_set = len({c["get_info"] for c in cards if c["get_info"]}) > 1

    missing, name_ng, rarity_ng, set_ng = [], [], [], []
    for c in cards:
        # 券面番号で引く。★set_name_official は catalog 側が英語の弾名で持つことがあるので
        #   照合キーにしない (2026-09-02: 一致条件にして 126枚全部を「欠落」と誤検出した)
        rows = conn.execute(
            # ★source で絞らない (2026-09-03)。どの scraper が入れたかは「在るか」と関係ない。
            #   絞っていたせいで OP-17 の 122枚を「欠落」と誤検出した (実際は在った)。
            "SELECT product_id, name, name_jp, set_name_official, specs FROM products "
            "WHERE category=? AND (product_id=? OR product_id LIKE ?)",
            (CATEGORY, c["no"], c["no"] + "_%")).fetchall()
        if not rows:
            missing.append(c)
            continue
        names = {_norm(r["name"] or "") for r in rows} | {_norm(r["name_jp"] or "") for r in rows}
        if _norm(c["name"]) not in names:
            name_ng.append((c, sorted(x for x in names if x)[:3]))
        if c["rarity"]:
            rar = {str((json.loads(r["specs"] or "{}") or {}).get("rarity") or "").strip() for r in rows}
            # ★複合コードを1つとみなす (2026-09-05)。
            #   公式の一覧ページはレアリティを1つしか出さないが、カードに印が2つ在るものが
            #   あり、catalog は空白区切りの複合で持っている (`SP P` = SP と P)。
            #   HQ 裁定 (2026-08-18 / tests/test_rarity_sp_composite_20260818.py) で
            #   **複合のまま持つ**と決めてあるので、こちらが合わせる。
            #   `SPカード` は `SP` と同じ (公式が同じ印を2通りに書く)。
            want = {c["rarity"], c["rarity"].replace("カード", "")}
            toks = {t for v in rar for t in v.split()} | rar
            if not (want & toks):
                rarity_ng.append((c, sorted(x for x in rar if x)[:3]))
        # 収録商品名: プロモ/限定は商品ごとに行が要る (3rd ANNIVERSARY SET の欠落はこの形)
        if check_set and c["get_info"] and not any(
                _norm(r["set_name_official"] or "") == c["get_info"] for r in rows):
            set_ng.append((c, sorted({(r["set_name_official"] or "")[:34] for r in rows})[:3]))
    return {"sid": sid, "fetched": len(cards), "missing": missing,
            "name_ng": name_ng, "rarity_ng": rarity_ng, "set_ng": set_ng}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", help="弾 id を指定 (省略時は最後に見た順)")
    ap.add_argument("--n", type=int, default=3, help="見る弾の数 (既定 3)")
    args = ap.parse_args()

    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    # state は {sid: {"at": 日時, "ng": 差分件数}}。旧形式 (文字列) も読める。
    def _at(v):
        return v.get("at", "") if isinstance(v, dict) else (v or "")

    def _ng(v):
        return int(v.get("ng", 0)) if isinstance(v, dict) else 0

    if args.series:
        targets = [args.series]
    else:
        ids = series_ids(_get(LIST_URL.format(sid="550101")))
        # ★差分が残っている弾を **必ず先に**見る。
        #   これが無いと、NG の弾が順番から外れて「全部 PASS」に見える
        #   (2026-09-03: 検収を作った初日に、14件 NG の弾を飛ばして緑になりかけた)。
        pending = [s for s in ids if _ng(state.get(s))]
        rest = sorted([s for s in ids if s not in pending], key=lambda s: _at(state.get(s)))
        targets = (pending + rest)[:max(args.n, len(pending))]

    conn = sqlite3.connect(str(api._DB_PATH), timeout=120)
    conn.row_factory = sqlite3.Row
    now = datetime.now().isoformat(timespec="seconds")
    total = ng = fail = 0
    print(f"=== 公式との突合 (one_piece / {len(targets)}弾) {now} ===")
    for sid in targets:
        try:
            res = check_series(conn, sid)
        except Exception as e:                       # fail-closed: 取れないのを正常と書かない
            fail += 1
            print(f"  ✗ series={sid} 取得失敗: {e}")
            continue
        if res.get("error"):
            fail += 1
            print(f"  ✗ series={sid} {res['error']}")
            continue
        n = (len(res["missing"]) + len(res["name_ng"]) + len(res["rarity_ng"])
             + len(res["set_ng"]))
        total += res["fetched"]
        ng += n
        mark = "OK " if n == 0 else "★NG"
        print(f"  {mark} series={sid} 公式 {res['fetched']}枚 / 差分 {n}")
        for c in res["missing"][:5]:
            print(f"      [欠落] {c['no']} {c['name']} ({c['rarity']}) / {c['get_info'][:40]}")
        for c, got in res["name_ng"][:5]:
            print(f"      [名前] {c['no']} 公式={c['name']!r} catalog={got}")
        for c, got in res["rarity_ng"][:5]:
            print(f"      [レア] {c['no']} 公式={c['rarity']!r} catalog={got}")
        for c, got in res["set_ng"][:5]:
            print(f"      [収録] {c['no']} 公式={c['get_info'][:34]!r} catalog={got}")
        state[sid] = {"at": now, "ng": n}
        time.sleep(1.0)
    conn.close()

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print("")
    if fail:
        print(f"⚠️ 取得できなかった弾 {fail} 件 (= 検査できていない。正常ではない)")
    left = [s for s, v in state.items() if (v.get("ng", 0) if isinstance(v, dict) else 0)]
    print(f"突合 {total}枚 / 差分 {ng}件 / **差分が残っている弾 {len(left)}** {left[:6]}")


if __name__ == "__main__":
    main()
