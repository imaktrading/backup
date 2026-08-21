#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kuji_hoju_fill.py — 一番くじの補URL補充 (2026-08-20)。

PSA と同じ「出品後に代わりの仕入元を足しておく」流れを一番くじにも通す。
無在庫なので、仕入元が1本しかない出品はその1本が切れた時点で取下げになる。

★PSA と違うところ: **KEY(カタログ品番)は使わない**。
  一番くじにカタログは無く、`item:m6168…` のような仕入元URL由来のKEYしか無い
  (実測: live 37件中25件がこの形、12件は空)。品番を作って埋める作業を増やす意味がない。
  代わりに **仕入元タイトルをそのまま検索語にする**。一番くじのタイトルは
  「一番くじ + キャラ + ○賞」で他人の出品もほぼ同じ書き方をするので文字列で足りる。
  同じ物かの担保は検索ではなく **目視** (下の画面) が持つ。

流れ:
    ① 対象を選ぶ   R列=一番くじ / 補が足りない / 出品中 / 新規優先
    ② 検索語を作る  一番くじ + キャラ + ○賞 (賞が無ければキャラまで)
    ③ メルカリ検索  安い順に候補を取る
    ④ HTMLで目視   写真・価格・タイトルを見て「同じ物」を選ぶ (別のくじ・付属品だけ が混ざる)
    ⑤ AC-AG に書く  PSA と同じ書込口。他出品が使用中のURLは弾く (dup_guard)

使い方:
    python kuji_hoju_fill.py --list        # 対象と検索語を見るだけ
    python kuji_hoju_fill.py               # 検索 → 目視 → 書込
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, r"C:\dev\iMak\iMakeBayAPI"):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import psa_hoju_fill as P                                       # noqa: E402

CATEGORY = "一番くじ"
AUX_MAX = P.AUXN                       # 5本 (AC-AG)。user 確定 2026-08-20
CACHE_PATH = os.path.join(HERE, "kuji_research_cache.json")
SERVER_PORT = 8789
_UA = {"User-Agent": "Mozilla/5.0"}

_STATE: dict = {"items": [], "result": None}
_EVENT = threading.Event()

# 「A賞」「ラストワン賞」= 賞。「角巻わため賞」= キャラ名が賞名なので賞として扱わない。
# 「A賞」。日本語に直付け (「ドラゴンボールA賞」) も拾う。
_LETTER = re.compile(r"(?:^|[\s　]|(?<=[ぁ-んァ-ヶ一-龥]))([A-Za-zＡ-Ｚａ-ｚ]{1,2})\s*賞")
_SPECIAL = re.compile(r"(ラストワン|ダブルチャンス)\s*賞")
_NAMED = re.compile(r"([一-龥ぁ-んァ-ヶー・]{2,12})\s*賞")
_NOISE = ("一番くじ", "未開封", "新品", "併売品", "【", "】", "☆", "未使用品",
          "おまけつき", "など", "非売品", "限定", "フィギュア")
# 作品名は検索語から外す (キャラ名の方が効く)。全部消えたら戻す。
# 造形ライン名・商品形態名。キャラ名ではないので検索語の主語にしない。
_NOT_CHARA = ("MASTERLISE", "EXPIECE", "BUSTISAN", "CHRONICLE", "MACHINE",
              "ver", "VER", "vol", "VOL", "ッッ")
_WORK = ("ワンピース", "ドラゴンボール", "呪術廻戦", "幽遊白書", "幽☆遊☆白書",
         "ジョジョの奇妙な冒険", "NARUTO", "僕のヒーローアカデミア", "推しの子",
         "メカゴジラ", "ハズビンホテル", "ガンダム", "ブルーロック", "刃牙",
         "ホロライブ", "鬼滅の刃", "チェンソーマン")


# ── 純関数 (test 可) ────────────────────────────────────────────────


def parse_title(title: str) -> tuple[str, str]:
    """仕入元タイトル → (キャラ/景品名, 賞)。純関数。

    ★賞の **後ろ** を優先して拾う。実データ37件では景品名が賞の後に来る方が多く、
      前優先だと「一番くじ カードゲーム A賞」のように作品名の一部を拾ってしまう。
    """
    s = re.sub(r"^\d+[\.\s]*", "", title or "")
    for n in _NOISE:
        s = s.replace(n, " ")
    prize, head, tail = "", s, ""
    m = _SPECIAL.search(s) or _LETTER.search(s)
    if m:
        prize = re.sub(r"\s+", "", m.group(0))
        head, tail = s[:m.start()], s[m.end():]
    else:
        m2 = _NAMED.search(s)
        if m2:                          # 「角巻わため賞」= キャラ名が賞名
            return _clean(m2.group(1)), ""

    def pick(text):
        def words_of(t):
            for w in _NOT_CHARA:
                t = t.replace(w, " ")
            ws = [w for w in _clean(t).split() if len(w) >= 2 and not w.isdigit()]
            # 日本語を含む語を優先 (「1993」「MACHINE」より「メカゴジラ」)
            jp = [w for w in ws if re.search(r"[ぁ-んァ-ヶ一-龥]", w)]
            return jp or ws
        t = text
        for w in _WORK:
            t = t.replace(w, " ")
        ws = words_of(t) or words_of(text)          # 消しすぎたら作品名も候補に戻す
        return ws[0] if ws else ""

    return (pick(tail) or pick(head)), prize


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\wぁ-んァ-ヶ一-龥ー&・]+", " ", s or "")).strip()


def build_query(title: str) -> str:
    """検索語。キャラが取れなければ空 = 探索不能 (推測で検索しない)。"""
    chara, prize = parse_title(title)
    if not chara:
        return ""
    return " ".join(x for x in ("一番くじ", chara, prize) if x)


# シートG列に入っている「写真ではない物」。サイトの OGP 画像が入っている行がある
# (実測 2026-08-22: 36件中15件だけ値が在り、その多くが `1kuji.com/ogp.jpg`)。
_NOT_A_PHOTO = ("ogp.jpg", "ogp.png", "noimage", "no_image", "placeholder")


def own_photo(cell: str) -> str:
    """シートG列 → 今出している物の写真1枚 (純関数)。無ければ空。

    ★サイト共通の OGP 画像は **写真ではない**。出すと全部同じ絵になって、
      人が「同じ物か」を判断できない (ユーザー指摘で発覚)。
    """
    for u in (cell or "").split("|"):
        u = u.strip()
        if u and not any(k in u.lower() for k in _NOT_A_PHOTO):
            return u
    return ""


def ebay_photo(item_id: str, post, tok) -> str:
    """eBay に出している写真の1枚目。取れなければ空 (推測しない)。

    シートG列は半分以上が空か OGP なので、**買い手が実際に見ている写真**を使う。
    """
    try:
        xml = post("GetItem", "<ItemID>%s</ItemID>" % item_id, tok, site="0")
        m = re.search(r"<PictureURL>(.*?)</PictureURL>", xml or "")
        return _html.unescape(m.group(1)) if m else ""
    except Exception:                                          # noqa: BLE001
        return ""


def select_targets(rows2d: list, max_backups: int = AUX_MAX) -> list:
    """R列=一番くじ の live 行のうち、補が max_backups 未満の物 (新規優先)。純関数。"""
    out = []
    for i, r in enumerate(rows2d[1:], start=2):
        iid = P._cell(r, P.B)
        if not iid or P._cell(r, P.D):          # 未出品 / 売切(取下げ済) は対象外
            continue
        if P._cell(r, P.CATEGORY) != CATEGORY:
            continue
        nb = P._backup_count(r)
        if nb >= max_backups:
            continue
        title = P._cell(r, 2)
        out.append({"row": i, "itemID": iid, "title": title,
                    # ★2026-08-22: 目視画面に **今出している物の写真** を出す。
                    #   候補だけ並べても「同じ物か」を判断できない (ユーザー指摘)。
                    "own_img": own_photo(P._cell(r, 6)),
                    "supply_url": P._cell(r, P.A), "n_backups": nb,
                    "query": build_query(title),
                    "listed_at": P._listed_sort_key(r)})
    out.sort(key=lambda t: (t["listed_at"], -t["row"]), reverse=True)
    return out


def drop_own_urls(cands: list, own: str, existing: list) -> list:
    """自分自身と既に持っている補URLを候補から外す (純関数)。"""
    def norm(u):
        return (u or "").split("?")[0].rstrip("/")
    have = {norm(own)} | {norm(u) for u in (existing or []) if u}
    out, seen = [], set()
    for c in cands:
        n = norm(c.get("href"))
        if not n or n in have or n in seen:
            continue
        seen.add(n)
        out.append(c)
    return out

def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                           # noqa: BLE001
        return {}


def save_cache(c):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    except Exception:                                           # noqa: BLE001
        pass


def search_candidates(targets: list, limit_each: int = 20, restart_every: int = 10) -> dict:
    """検索語ごとにメルカリを引く → {itemID: [candidate]}。取れなければ空リスト。"""
    import tempfile
    import mercari_psa_resource as mp
    import undetected_chromedriver as uc

    def _driver():
        mp._quiet_chromedriver()
        o = uc.ChromeOptions()
        for a in ("--headless=new", "--no-sandbox", "--lang=ja-JP", "--window-size=1280,1400"):
            o.add_argument(a)
        o.add_argument("--user-data-dir=" + tempfile.mkdtemp(prefix="kuji_hoju_"))
        maj = mp._chrome_major()
        d = uc.Chrome(options=o, version_main=maj) if maj else uc.Chrome(options=o)
        d.set_page_load_timeout(50)
        return d

    out, drv = {}, None
    try:
        for i, t in enumerate(targets):
            kw = t.get("query") or ""
            if not kw:
                out[t["itemID"]] = []
                print(f"  [{i+1}/{len(targets)}] 検索語なし → skip: {t['title'][:40]}")
                continue
            if drv is None or (i and i % restart_every == 0):
                if drv:
                    try:
                        drv.quit()
                    except Exception:                           # noqa: BLE001
                        pass
                drv = _driver()
            url = ("https://jp.mercari.com/search?keyword=" + urllib.parse.quote(kw)
                   + "&status=on_sale&order=asc&sort=price")
            try:
                drv.get(url)
                time.sleep(8)
                items = mp.parse_mercari_items(drv.page_source)[:limit_each]
            except Exception as e:                              # noqa: BLE001
                print(f"  ⚠️ 検索できず ({type(e).__name__}): {kw}")
                items = []
            imgs = _image_map(drv.page_source if items else "")
            out[t["itemID"]] = [
                {"href": it.get("href"), "name": it.get("name"), "price": it.get("price") or 0,
                 "img": imgs.get(it.get("href"), "")} for it in items]
            print(f"  [{i+1}/{len(targets)}] {kw} → {len(items)}件")
    finally:
        if drv:
            try:
                drv.quit()
            except Exception:                                   # noqa: BLE001
                pass
    return out


def _image_map(src: str) -> dict:
    """検索結果HTML → {商品URL: 画像URL} (取れなければ空)。"""
    out = {}
    for m in re.finditer(r'href="(/(?:item|shops/product)/[^"]+)"(.{0,600}?)<img[^>]+src="([^"]+)"',
                         src or "", re.S):
        out["https://jp.mercari.com" + m.group(1)] = m.group(3)
    return out

# ── slice3: 昼の確認 (PSA と同じ画面・同じ操作) ──────────────────────
#
# ★2026-08-22 ユーザー指示「同じにしてといっている。HTMLの見た目も全て。
#   やりやすくて機能的なPSAに合わせてくれ」。
#   自前の HTML を捨てて、PSA の確証UI (`psa_resource_confirm.restock_confirm`) を
#   そのまま呼ぶ。画面・操作・「違う/見送り」の受け皿まで PSA と同一になる。
def build_items(targets: list, cache: dict) -> tuple:
    """キャッシュ済の候補から、PSA の確証UI に渡す items を作る。

    items の形は PSA と同じ:
      {idx, title, card_no, ebay_url, ref_image, candidates:[{channel,url,price}]}
    `card_no` は一番くじに品番が無いので **賞名** を入れる (画面では同じ位置に出る)。
    """
    import psa_resource_confirm as prc
    items, item_targets = [], []
    for t in targets:
        entry = cache.get(t["itemID"])
        # ★旧形式 (list をそのまま入れていた) のキャッシュが残っている。壊さず読む
        cands = entry if isinstance(entry, list) else ((entry or {}).get("candidates") or [])
        cands = drop_own_urls(cands, t.get("supply_url", ""), t.get("existing", []))
        if not cands:
            continue
        ref = t.get("own_img") or prc.ebay_listing_image(t["itemID"])
        if not ref:
            continue                       # 現物が見えない = 目視できない (推測で通さない)
        idx = len(items)
        items.append({
            "idx": idx, "title": (t.get("title") or "")[:90],
            "card_no": parse_title(t.get("title", ""))[1] or "",
            "ebay_url": "https://www.ebay.com/itm/%s" % t["itemID"],
            "ref_image": ref,
            "candidates": [{"channel": "mercari", "url": c.get("href", ""),
                            "price": c.get("price", 0)} for c in cands],
        })
        item_targets.append(t)
    return items, item_targets


def run_search(targets: list) -> int:
    """slice2: 夜間検索 (無人)。候補をキャッシュに貯めるだけ。**補URLは書かない**。"""
    import datetime
    found = search_candidates(targets)
    cache = load_cache()
    today = datetime.date.today().isoformat()
    n = 0
    for t in targets:
        cands = found.get(t["itemID"]) or []
        cache[t["itemID"]] = {"date": today, "query": t.get("query", ""),
                              "candidates": cands}
        n += 1 if cands else 0
    save_cache(cache)
    print("  💾 キャッシュに保存: %d件 (候補あり %d件)" % (len(targets), n))
    print("     → 翌日 `--confirm` で目視して補URLに書きます")
    return 0


def run_confirm(targets: list, dry_run: bool = False) -> int:
    """slice3: 昼の確認。PSA と同じ画面で目視 → 選ばれた分だけ補URLへ書く。"""
    import psa_resource_confirm as prc
    cache = load_cache()
    items, item_targets = build_items(targets, cache)
    if not items:
        print("  目視できる行がありません (夜間検索がまだ / 候補が全部除外)")
        return 0
    print("  🌐 目視 %d件: ブラウザで確認 → 送信" % len(items))
    if dry_run:
        return 0
    res = prc.restock_confirm(items)
    if res is None:
        print("  ⏹ 未確定のまま閉じられました。何も書いていません")
        return 0
    confirmed = res.get("confirmed") or []
    if not confirmed:
        print("  選ばれた候補が0件でした。何も書いていません")
        return 0
    plan = {}
    for c in confirmed:
        t = item_targets[c["idx"]]
        plan[t["row"]] = P.compute_backurl_additions(t.get("existing", []), c["urls"])
    import sheet_io as S
    S.write_aux_urls(plan)
    print("  ✏️ 補URLを書きました: %d行" % len(plan))
    if res.get("diffs"):
        print("  ⚠️ 「違う」と判定された候補 %d件 (検索が別の物を拾っている)"
              % len(res["diffs"]))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="一番くじの補URL補充。PSA と同じ 2段 (夜に検索 → 昼に目視)")
    ap.add_argument("--list", action="store_true", help="対象と検索語を見るだけ")
    ap.add_argument("--search", action="store_true",
                    help="slice2: 夜間検索 (無人・キャッシュに貯めるだけ)")
    ap.add_argument("--confirm", action="store_true",
                    help="slice3: 昼の確認 (PSA と同じ画面。選んだ分を補URLへ書く)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="件数だけ見る (書かない)")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                           # noqa: BLE001
        pass

    vals = P._read_high()
    targets = select_targets(vals)
    for t in targets:
        row = vals[t["row"] - 1] if 0 < t["row"] <= len(vals) else []
        t["existing"] = [P._cell(row, P.AUX0 + k) for k in range(P.AUXN)]
        t["existing"] = [u for u in t["existing"] if u]
    print("一番くじ: 補<%d本 の live 出品 %d件 (うち補0本 %d件)"
          % (AUX_MAX, len(targets), sum(1 for t in targets if t["n_backups"] == 0)))
    if a.limit:
        targets = targets[:a.limit]
    if a.list:
        for t in targets:
            print("  補%d本 %-34s ← %s" % (t["n_backups"], (t["query"] or "(検索語なし)")[:34],
                                          t["title"][:40]))
        return 0
    if not targets:
        return 0
    if a.search:
        return run_search(targets)
    if a.confirm:
        return run_confirm(targets, dry_run=a.dry_run)
    print("  --search (夜間検索) か --confirm (昼の目視) を指定してください")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
