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


def build_html(items: list) -> str:
    """目視画面 (純関数)。候補の写真・価格・タイトルを並べて選ばせる。

    検索だけでは **別のくじ / 別の賞 / 付属品だけ** が混ざる (実測: 「一番くじ
    シャンクス A賞」で 大海賊 と 新四皇 と 専用台座 が同時に出た)。だから人が見る。
    """
    cards = []
    for i, it in enumerate(items):
        cands = it.get("candidates") or []
        thumbs = "\n".join(
            f'<label class="p"><input type="checkbox" name="c{i}" value="{_html.escape(c.get("href",""))}">'
            f'<img src="/img/{urllib.parse.quote(c.get("img") or "", safe="")}" loading="lazy">'
            f'<span class="cap">¥{c.get("price", 0):,}<br>{_html.escape((c.get("name") or "")[:46])}</span>'
            f'</label>' for c in cands) or '<span class="no">候補が見つかりませんでした</span>'
        cards.append(f"""
<div class="card" id="c{i}" data-row="{it.get('row')}">
  <h2>{i+1}. {_html.escape(it.get('title',''))}</h2>
  <div class="meta">補 {it.get('n_backups',0)}/{AUX_MAX}本
    &nbsp;|&nbsp; 検索語: <b>{_html.escape(it.get('query',''))}</b>
    &nbsp;|&nbsp; <a href="{_html.escape(it.get('supply_url',''))}" target="_blank">今の仕入元</a>
    &nbsp;|&nbsp; <a href="https://jp.mercari.com/search?keyword={urllib.parse.quote(it.get('query',''))}"
       target="_blank">メルカリで開く</a></div>
  <div class="lbl">同じ物にチェック ({len(cands)}件・安い順)。別のくじ・別の賞・付属品だけ が混ざります</div>
  <div class="pics">{thumbs}</div>
  <div class="btns"><button onclick="done({i})">この行は決めた</button>
    <span class="state" id="s{i}"></span></div>
</div>""")
    return """<!doctype html><meta charset="utf-8"><title>一番くじ 補URL 目視</title>
<style>
body{font-family:system-ui,sans-serif;margin:16px;background:#f6f6f6}
.card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px;margin:0 0 16px}
h2{font-size:15px;margin:0 0 4px}
.meta{font-size:12px;color:#555;margin-bottom:6px}
.lbl{font-size:12px;font-weight:700;margin:6px 0 4px}
.no{color:#a00;font-size:13px}
.pics{display:flex;flex-wrap:wrap;gap:8px}
.p{position:relative;display:inline-block;width:160px}
.p img{width:160px;height:160px;object-fit:contain;background:#fff;border:2px solid #ccc;border-radius:4px}
.p input{position:absolute;top:4px;left:4px;transform:scale(1.6);z-index:2}
.p input:checked+img{border-color:#0a0;border-width:3px}
.cap{display:block;font-size:11px;line-height:1.3;color:#333}
button{font-size:14px;padding:6px 12px;border-radius:5px;border:1px solid #999;background:#dfd;cursor:pointer}
.state{font-weight:700;margin-left:8px}
#bar{position:sticky;top:0;background:#222;color:#fff;padding:10px;border-radius:6px;margin-bottom:12px;z-index:9}
#send{background:#fff;color:#000;font-weight:700}
</style>
<div id="bar"><span id="cnt">0</span> / __N__ 行 決定
  <button id="send" onclick="send()">✉️ HQ に送信</button><span id="msg"></span></div>
__CARDS__
<script>
const D={};
function done(i){
  const c=document.getElementById('c'+i);
  const n=c.querySelectorAll('input:checked').length;
  D[i]=1; document.getElementById('s'+i).textContent=n+'件を補URLに';
  document.getElementById('cnt').textContent=Object.keys(D).length;
  const nx=document.getElementById('c'+(i+1)); if(nx) nx.scrollIntoView({behavior:'smooth'});
}
function send(){
  const out=[];
  document.querySelectorAll('.card').forEach((c,i)=>{
    if(!(i in D)) return;
    out.push({row:+c.dataset.row,
      urls:[...c.querySelectorAll('input:checked')].map(x=>x.value)});
  });
  if(!out.length){document.getElementById('msg').textContent=' 1行も決めていません';return;}
  fetch('/submit',{method:'POST',body:JSON.stringify(out)})
    .then(r=>r.text()).then(t=>document.getElementById('msg').textContent=' '+t);
}
</script>""".replace("__CARDS__", "\n".join(cards)).replace("__N__", str(len(items)))


# ── I/O ────────────────────────────────────────────────────────────


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


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                                  # noqa: D102
        pass

    def do_GET(self):                                           # noqa: N802
        if self.path.startswith("/img/"):
            u = urllib.parse.unquote(self.path[5:])
            try:
                data = urllib.request.urlopen(
                    urllib.request.Request(u, headers=_UA), timeout=20).read()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(data)
            except Exception:                                   # noqa: BLE001
                self.send_response(404)
                self.end_headers()
            return
        body = build_html(_STATE["items"]).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):                                          # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        try:
            _STATE["result"] = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:                                       # noqa: BLE001
            _STATE["result"] = []
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("受け取りました。閉じてOK".encode("utf-8"))
        _EVENT.set()


def run_review(items: list, open_browser: bool = True, timeout_sec: int = 10800):
    _STATE["items"], _STATE["result"] = items, None
    _EVENT.clear()
    server = None
    for p in range(SERVER_PORT, SERVER_PORT + 10):
        try:
            server = HTTPServer(("127.0.0.1", p), _Handler)
            break
        except OSError:
            continue
    if not server:
        print("  ⚠️ 画面を出せませんでした → 書込なし")
        return []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"  🌐 目視画面: {url}  ({len(items)}行)")
    if open_browser:
        try:
            import subprocess
            subprocess.run(["cmd", "/c", "start", "", url], check=False)
        except Exception:                                       # noqa: BLE001
            pass
    got = _EVENT.wait(timeout=timeout_sec)
    try:
        server.shutdown()
    except Exception:                                           # noqa: BLE001
        pass
    if not got or not _STATE["result"]:
        print("  ⚠️ 回答が来ませんでした → 書込なし")
        return []
    return _STATE["result"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="対象と検索語を見るだけ")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                           # noqa: BLE001
        pass

    vals = P._read_high()
    targets = select_targets(vals)
    print(f"一番くじ: 補<{AUX_MAX}本 の live 出品 {len(targets)}件 "
          f"(うち補0本 {sum(1 for t in targets if t['n_backups'] == 0)}件)")
    if a.limit:
        targets = targets[:a.limit]
    if a.list:
        for t in targets:
            print("  補%d本 %-34s ← %s" % (t["n_backups"], (t["query"] or "(検索語なし)")[:34],
                                          t["title"][:40]))
        return 0
    if not targets:
        return 0

    found = search_candidates(targets)
    items = []
    for t in targets:
        r = vals[t["row"] - 1] if 0 < t["row"] <= len(vals) else []
        existing = [P._cell(r, P.AUX0 + k) for k in range(AUX_MAX)]
        cands = drop_own_urls(found.get(t["itemID"]) or [], t["supply_url"], existing)
        items.append(dict(t, candidates=cands))
    save_cache({t["itemID"]: t.get("candidates") for t in items})

    res = run_review(items, open_browser=not a.no_browser)
    if not res:
        return 0

    confirmed = {}
    item_targets = {}
    by_row = {it["row"]: k for k, it in enumerate(items)}
    for r in res:
        k = by_row.get(r.get("row"))
        if k is None or not r.get("urls"):
            continue
        confirmed[k] = r["urls"]
        item_targets[k] = items[k]
    if not confirmed:
        print("  選ばれた候補が0件 → 書込なし")
        return 0

    # 他の出品が使っているURLは掴まない (両方売れたら片方が履行不能 = Defect)
    guard_ok, owner = True, {}
    try:
        import dup_guard as _dg
        for _r in vals[1:]:
            if not (P._cell(_r, P.B) and not P._cell(_r, P.D)):
                continue
            for _u in [P._cell(_r, P.A)] + [P._cell(_r, P.AUX0 + k) for k in range(P.AUXN)]:
                n = _dg.norm_url(_u)
                if n:
                    owner.setdefault(n, set()).add(P._cell(_r, P.B))
        owner = {k: sorted(v) for k, v in owner.items()}
    except Exception as e:                                      # noqa: BLE001
        print(f"⚠️要対応 URL共有ガードを組めず **書込を中止**: {type(e).__name__}: {e}")
        guard_ok = False

    plan, added, dropped = P.plan_aux_writeback(
        confirmed, item_targets, vals, owner, guard_ok, aux_max=AUX_MAX)
    for u, own in dropped:
        print(f"  ⛔ 補URL除外(他出品が使用中 {own}): {u[:70]}")
    if not plan:
        print("  書込対象なし (全て既存収載 or 満杯 or ガード不成立)")
        return 0
    from sheet_io import write_aux_urls
    n = write_aux_urls(plan)
    print(f"🔗 補URL(AC-AG) 書込: {n}行 / 追加 {added}本 (既存保持・空き枠のみ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
