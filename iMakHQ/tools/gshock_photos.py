# -*- coding: utf-8 -*-
"""G-SHOCK の出品写真を、候補を並べて人が選ぶ (2026-10-11 ユーザー確定)。

なぜ要るか:
    eBay から「G-SHOCK は写真が少ない」と指摘を受けている。これまでは新規を 999.png (仮) で出し、
    出品後に手で差し替えていた。Amazon の写真は枚数が少ない。
    ユーザー「Tシャツみたいに使える画像を並べて選ぶ形にしたい」「公式が1番いい」「ローカルに落とせばいい」。

流れ:
    1. prepare: 写真の待ち (gshock_to_csv が写真の無い型番を足す) の型番ごとに候補を集める
         - 公式: casio.com の商品ページ (普通の取り方は弾かれるので Edge を裏で開いて読む) の写真を
           この PC に落とす (正面・角度違い・着用で 4〜13枚)。PNG は白地の JPG にする
         - 前に出した eBay の写真: Seller Hub のレポートで同じ型番の出品を探し、その写真 (i.ebayimg)
    2. review: 候補を並べた画面。押した順に使う写真が決まる (1枚目がギャラリー画像)
    3. 選んだ公式の写真を eBay の写真置き場に上げる (UploadSiteHostedPictures)
       → 全部 eBay の置き場にそろうので、置き場の混在で弾かれない (2026-09-15 Tシャツ 0件の原因)
    4. 型番ごとの URL を CHOICE に残す。gshock_to_csv は urls_for(型番) を PicURL に使う

答えは型番ごとに残すので、同じ型番は二度並べない。

使い方:
    python gshock_photos.py prepare            # 待ちの型番の候補を集める
    python gshock_photos.py review             # 選ぶ画面を出す (選んだ公式写真は eBay に上げる)
    python gshock_photos.py add GA-2100-1A1    # 型番を手で待ちに足す
    python gshock_photos.py status
"""
from __future__ import annotations

import csv
import datetime as dt
import glob
import html as _html
import json
import os
import re
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

PHOTO_DIR = r"C:/dev/iMak_data/gshock_photos"
PENDING = r"C:/dev/iMak_data/hq/gshock_photo_pending.json"
CANDIDATES = r"C:/dev/iMak_data/hq/gshock_photo_candidates.json"
CHOICE = r"C:/dev/iMak_data/hq/gshock_photo_choice.json"
REPORT_DIR = r"C:/dev/iMak_data/seller_hub/reports"
EDGE = r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
OFFICIAL_URL = "https://www.casio.com/jp/watches/gshock/product.{model}/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/141.0 Safari/537.36 Edg/141.0")
EP = "https://api.ebay.com/ws/api.dll"
MAX_PICS = 24          # eBay の上限
SERVER_PORT = 8789


# ── 記録 ────────────────────────────────────────────────────────
def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                           # noqa: BLE001
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def norm_model(m):
    """型番を揃える (純関数)。JF / JR は公式のフォルダ名に無いので外す。"""
    m = (m or "").strip().upper()
    return re.sub(r"(?:JF|JR)$", "", m)


def urls_for(model, choice=None):
    """出品に使う写真の URL (eBay の置き場)。選んでいなければ [] (純関数に近い・記録を読むだけ)。"""
    c = (choice if choice is not None else _load(CHOICE, {})).get(norm_model(model)) or {}
    return list(c.get("eps") or [])[:MAX_PICS]


def add_pending(model, reason=""):
    """写真の待ちに型番を足す (gshock_to_csv から呼ぶ)。選び済みなら足さない。戻り: 足したか。"""
    m = norm_model(model)
    if not m or urls_for(m):
        return False
    p = _load(PENDING, {})
    if m in p:
        return False
    p[m] = {"at": dt.datetime.now().isoformat(timespec="seconds"), "reason": reason}
    _save(PENDING, p)
    return True


# ── 候補: 公式 ──────────────────────────────────────────────────
def official_assets(page_html, model):
    """公式の商品ページ → その型番のフォルダの写真 URL (純関数)。

    並び: 正面 (型番.png) → 角度違い (_SeqNN) → 着用 (_modelNN)。ほかの型番の写真は拾わない
    (ページには関連商品の写真も載っている)。
    """
    low = norm_model(model).lower()
    pat = re.compile(r"(/content/dam/casio/product-info/[^\"' ]+/" + re.escape(low)
                     + r"/assets/[^\"' ]+?\.(?:png|jpg))", re.I)
    found = []
    for m in pat.finditer(page_html or ""):
        u = re.sub(r"\.transform.*$", "", m.group(1))
        if u not in found:
            found.append(u)

    def key(u):
        name = u.rsplit("/", 1)[-1].lower()
        if re.search(r"_seq0*1\.", name):
            return (0, 1)                      # Seq1 は正面と同じことが多い → 正面の直後
        if "_seq" in name:
            n = re.search(r"_seq0*(\d+)", name)
            return (1, int(n.group(1)) if n else 99)
        if "_model" in name:
            n = re.search(r"_model0*(\d+)", name)
            return (2, int(n.group(1)) if n else 99)
        return (0, 0)                          # 型番.png = 正面
    return ["https://www.casio.com" + u for u in sorted(found, key=key)]


def fetch_official_page(model, timeout=75):
    """Edge を裏で開いて公式ページの HTML を取る (I/O)。取れなければ ""。"""
    try:
        r = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--virtual-time-budget=15000",
                            f"--user-agent={UA}", "--dump-dom", OFFICIAL_URL.format(model=norm_model(model))],
                           capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace")
    except Exception:                                           # noqa: BLE001
        return ""


def download(url, dest):
    """写真を落とす。PNG は白地の JPG にする (透過は eBay で黒くなることがある)。戻り: 保存先 or ""。"""
    try:
        from PIL import Image
        import io
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=40).read()
        im = Image.open(io.BytesIO(raw))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        im.save(dest, "JPEG", quality=92)
        return dest
    except Exception:                                           # noqa: BLE001
        return ""


# ── 候補: 前に出した eBay の写真 ───────────────────────────────
def past_item_ids(rows, model):
    """レポートの行 → その型番を出したことのある itemID (純関数)。US の親だけ。"""
    m = norm_model(model)
    pat = re.compile(r"(?<![A-Z0-9-])" + re.escape(m) + r"(?:JF|JR)?(?![A-Z0-9])", re.I)
    out = []
    for r in rows:
        if (r.get("Listing site") or "US") != "US":
            continue
        if pat.search(r.get("Title") or "") and r.get("Item number") not in out:
            out.append(r.get("Item number"))
    return out


def _report_rows():
    rows = []
    for pat in ("eBay-all-active-listings-report-*.csv", "eBay-inactive-listings-report-*.csv"):
        c = [p for p in glob.glob(os.path.join(REPORT_DIR, "*", pat)) if "(1)" not in p]
        if c:
            rows += list(csv.DictReader(open(max(c), encoding="utf-8-sig", errors="replace")))
    return rows


# ── 集める ──────────────────────────────────────────────────────
def prepare(models=None, log=print):
    """待ちの型番の候補を集める。戻り: {型番: 候補の数}。"""
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))
    pend = _load(PENDING, {})
    models = [norm_model(m) for m in (models or list(pend))]
    cands = _load(CANDIDATES, {})
    rows = _report_rows()
    done = {}
    for m in models:
        if urls_for(m):
            continue
        local = []
        page = fetch_official_page(m)
        for i, u in enumerate(official_assets(page, m), 1):
            dest = os.path.join(PHOTO_DIR, m, f"official_{i:02d}.jpg")
            if os.path.exists(dest) or download(u, dest):
                local.append({"kind": "official", "src": u, "local": dest})
        ebay = []
        try:
            from ebay_getitem_images import fetch_listing_images
            for iid in past_item_ids(rows, m)[:3]:
                for u in fetch_listing_images(iid):
                    if u not in [x["src"] for x in ebay]:
                        ebay.append({"kind": "ebay", "src": u, "item": iid})
        except Exception as e:                                  # noqa: BLE001
            log(f"  ⚠️ {m}: 前の eBay の写真を読めず ({type(e).__name__})")
        cands[m] = {"official": local, "ebay": ebay, "page_ok": bool(page and len(page) > 5000),
                    "at": dt.datetime.now().isoformat(timespec="seconds")}
        done[m] = len(local) + len(ebay)
        log(f"  {m}: 公式 {len(local)}枚 / 前の eBay {len(ebay)}枚")
    _save(CANDIDATES, cands)
    # ★走行ログで「動いた」が分かる1行 (0件でも出す)
    log(f"📷 G-SHOCK 写真の候補を集めた: {len(done)}型番 / 待ち {len(models)}型番")
    return done


# ── 選ぶ画面 ────────────────────────────────────────────────────
def build_html(models, cands):
    """選ぶ画面 (純関数)。押した順に番号が付き、1番がギャラリー画像。"""
    cards = []
    for i, m in enumerate(models):
        c = cands.get(m) or {}
        pics = [("official", x["local"]) for x in c.get("official") or []] + \
               [("ebay", x["src"]) for x in c.get("ebay") or []]
        thumbs = "".join(
            f'<div class="p" data-v="{_html.escape(v)}" onclick="pick({i},this)">'
            f'<img src="{("/local/" if k == "official" else "/img/") + urllib.parse.quote(v, safe="")}" loading="lazy">'
            f'<span class="tag {k}">{"公式" if k == "official" else "前の eBay"}</span><span class="no"></span></div>'
            for k, v in pics) or '<span class="none">候補がありません (公式にページが無い・前に出したことも無い)</span>'
        cards.append(f'<div class="card" id="c{i}" data-m="{_html.escape(m)}"><h2>{i + 1}. {_html.escape(m)}'
                     f' <small>公式 {len(c.get("official") or [])}枚 ・ 前の eBay {len(c.get("ebay") or [])}枚</small>'
                     f' <a href="{OFFICIAL_URL.format(model=m)}" target="_blank">公式を開く</a></h2>'
                     f'<div class="pics">{thumbs}</div>'
                     f'<div class="btns"><button onclick="clr({i})">選び直す</button>'
                     f'<button class="ng" onclick="skip({i})">写真が無いので出さない</button>'
                     f'<span class="cnt" id="n{i}">0枚</span></div></div>')
    return """<!doctype html><meta charset="utf-8"><title>G-SHOCK 写真を選ぶ</title><style>
body{font-family:system-ui,sans-serif;margin:16px;background:#f3f5f7;color:#1d2a33}
#bar{position:sticky;top:0;z-index:9;background:#17324a;color:#fff;padding:10px 14px;margin-bottom:12px;display:flex;gap:12px;align-items:center}
#bar button{background:#fff;color:#17324a;border:0;padding:6px 14px;font-weight:700;cursor:pointer}
.card{background:#fff;border:1px solid #dbe2e7;padding:12px;margin:0 0 14px}
h2{font-size:16px;margin:0 0 8px}h2 small{font-weight:400;color:#5d6b75;font-size:12px;margin-left:8px}h2 a{font-size:12px;margin-left:8px}
.pics{display:flex;flex-wrap:wrap;gap:8px}
.p{position:relative;cursor:pointer;border:3px solid transparent}
.p img{width:220px;height:220px;object-fit:contain;background:#fff;display:block;border:1px solid #dbe2e7}
.p.on{border-color:#1f7a4d}
.tag{position:absolute;left:4px;bottom:4px;font-size:10px;padding:1px 6px;color:#fff}
.tag.official{background:#17324a}.tag.ebay{background:#b07a10}
.no{position:absolute;top:4px;left:4px;background:#1f7a4d;color:#fff;font-weight:700;border-radius:12px;min-width:24px;text-align:center;font-size:13px;line-height:24px;display:none}
.p.on .no{display:block}
.btns{margin-top:8px;display:flex;gap:8px;align-items:center}
button{padding:5px 12px;border:1px solid #9aa7b1;background:#fff;cursor:pointer}.ng{color:#b4442f}
.cnt{font-size:13px;color:#5d6b75}.none{color:#b4442f;font-size:13px}
.card.skip{opacity:.45}
</style>
<div id="bar"><span>押した順に使う写真が決まります (1番 = ギャラリー画像)。多めに選んでください</span>
<button onclick="send()">✉️ 決定して送る</button><span id="msg"></span></div>
__CARDS__
<script>
const S={}, K={};
function upd(i){const c=document.getElementById('c'+i);const a=S[i]||[];
 c.querySelectorAll('.p').forEach(p=>{const k=a.indexOf(p.dataset.v);p.classList.toggle('on',k>=0);p.querySelector('.no').textContent=k>=0?k+1:'';});
 document.getElementById('n'+i).textContent=a.length+'枚';}
function pick(i,el){S[i]=S[i]||[];const v=el.dataset.v,k=S[i].indexOf(v);if(k>=0)S[i].splice(k,1);else S[i].push(v);delete K[i];
 document.getElementById('c'+i).classList.remove('skip');upd(i);}
function clr(i){S[i]=[];upd(i);}
function skip(i){K[i]=1;S[i]=[];upd(i);document.getElementById('c'+i).classList.add('skip');}
function send(){const out=[];document.querySelectorAll('.card').forEach((c,i)=>{
 if(K[i])out.push({model:c.dataset.m,skip:true});else if((S[i]||[]).length)out.push({model:c.dataset.m,picks:S[i]});});
 if(!out.length){document.getElementById('msg').textContent=' まだ1つも選んでいません';return;}
 document.getElementById('msg').textContent=' 送信中… (選んだ公式の写真を eBay に上げています)';
 fetch('/submit',{method:'POST',body:JSON.stringify(out)}).then(r=>r.text()).then(t=>document.getElementById('msg').textContent=' '+t);}
</script>""".replace("__CARDS__", "".join(cards))


# ── eBay の写真置き場に上げる ──────────────────────────────────
def upload_request_xml(name):
    """UploadSiteHostedPictures の XML 部分 (純関数)。"""
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"<PictureName>{_html.escape(name)}</PictureName><PictureSet>Supersize</PictureSet>"
            "</UploadSiteHostedPicturesRequest>")


def parse_full_url(xml):
    """応答 → FullURL。失敗は "" (純関数)。"""
    if "<Ack>Success</Ack>" not in (xml or "") and "<Ack>Warning</Ack>" not in (xml or ""):
        return ""
    m = re.search(r"<FullURL>(.*?)</FullURL>", xml or "")
    return m.group(1).strip() if m else ""


def _token():
    sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
    import fix_de_speedpak_shipping as fx
    fx.refresh()
    return fx.token()


def upload(path, name, tok):
    """写真を eBay の置き場に上げて URL を返す (I/O)。失敗は ""。"""
    import requests
    hdr = {"X-EBAY-API-CALL-NAME": "UploadSiteHostedPictures", "X-EBAY-API-SITEID": "0",
           "X-EBAY-API-COMPATIBILITY-LEVEL": "1271", "X-EBAY-API-IAF-TOKEN": tok}
    try:
        with open(path, "rb") as f:
            files = {"XML Payload": (None, upload_request_xml(name), "text/xml"),
                     "image": (os.path.basename(path), f.read(), "image/jpeg")}
        return parse_full_url(requests.post(EP, headers=hdr, files=files, timeout=120).text)
    except Exception:                                           # noqa: BLE001
        return ""


def apply_answers(answers, cands, log=print, up=None):
    """画面の答え → CHOICE に残す (選んだ公式は eBay に上げる)。戻り: (決めた型番数, 失敗した写真数)。"""
    choice = _load(CHOICE, {})
    pend = _load(PENDING, {})
    tok = None
    ok = ng = 0
    for a in answers:
        m = norm_model(a.get("model"))
        if not m:
            continue
        if a.get("skip"):
            choice[m] = {"eps": [], "skip": True, "at": dt.datetime.now().isoformat(timespec="seconds")}
            pend.pop(m, None)
            ok += 1
            continue
        local_of = {x["local"]: x for x in (cands.get(m) or {}).get("official") or []}
        eps = []
        for n, v in enumerate(a.get("picks") or [], 1):
            if v in local_of:
                if up is None:
                    tok = tok or _token()
                    url = upload(v, f"imak_gshock_{m}_{n:02d}", tok)
                else:
                    url = up(v)
                if url:
                    eps.append(url)
                else:
                    ng += 1
            elif v.startswith("https://i.ebayimg.com/"):
                eps.append(v)
        if eps:
            choice[m] = {"eps": eps[:MAX_PICS], "at": dt.datetime.now().isoformat(timespec="seconds")}
            pend.pop(m, None)
            ok += 1
            log(f"  ✅ {m}: {len(eps)}枚")
    _save(CHOICE, choice)
    _save(PENDING, pend)
    # ★走行ログで「動いた」が分かる1行 (0件でも出す)
    log(f"📷 G-SHOCK 写真を決めた: {ok}型番 / 答え {len(answers)}件 / 上げられなかった写真 {ng}枚")
    return ok, ng


_STATE = {}
_EVENT = threading.Event()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):                                  # noqa: D102
        pass

    def do_GET(self):                                           # noqa: N802
        if self.path.startswith("/local/"):
            p = urllib.parse.unquote(self.path[7:])
            if os.path.isfile(p) and os.path.abspath(p).replace("\\", "/").startswith(PHOTO_DIR):
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(open(p, "rb").read())
                return
            self.send_response(404)
            self.end_headers()
            return
        if self.path.startswith("/img/"):
            try:
                data = urllib.request.urlopen(urllib.request.Request(
                    urllib.parse.unquote(self.path[5:]), headers={"User-Agent": UA}), timeout=20).read()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.end_headers()
                self.wfile.write(data)
            except Exception:                                   # noqa: BLE001
                self.send_response(404)
                self.end_headers()
            return
        body = build_html(_STATE["models"], _STATE["cands"]).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):                                          # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        try:
            ans = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:                                       # noqa: BLE001
            ans = []
        ok, ng = apply_answers(ans, _STATE["cands"])
        msg = f"{ok}型番を決めました" + (f" ・ 上げられなかった写真 {ng}枚" if ng else "") + "。閉じて OK"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(msg.encode("utf-8"))
        _EVENT.set()


def review(open_browser=True, timeout_sec=10800):
    cands = _load(CANDIDATES, {})
    models = [m for m in _load(PENDING, {}) if m in cands and not urls_for(m)]
    if not models:
        print("📷 G-SHOCK 写真: 選ぶ物はありません (待ち 0件 か、候補をまだ集めていない → prepare)")
        return
    _STATE.update(models=models, cands=cands)
    _EVENT.clear()
    server = None
    fixed = os.environ.get("IMAK_REVIEW_PORT")
    for p in ([int(fixed)] if fixed else range(SERVER_PORT, SERVER_PORT + 10)):
        try:
            server = HTTPServer(("127.0.0.1", p), _Handler)
            break
        except OSError:
            continue
    if not server:
        print("⚠️ 画面を出せませんでした")
        return
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"  🌐 写真を選ぶ画面: {url}  ({len(models)}型番)", flush=True)
    if open_browser and not os.environ.get("IMAK_NO_BROWSER"):
        subprocess.run(["cmd", "/c", "start", "", url], check=False)
    _EVENT.wait(timeout_sec)
    server.shutdown()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                          # noqa: BLE001
        pass
    a = sys.argv[1:]
    cmd = a[0] if a else "status"
    if cmd == "add":
        for m in a[1:]:
            print(m, "足した" if add_pending(m, "手で") else "足していない (選び済みか、もう待ちにある)")
    elif cmd == "prepare":
        prepare(a[1:] or None)
    elif cmd == "review":
        review()
    else:
        pend, ch = _load(PENDING, {}), _load(CHOICE, {})
        print(f"📷 G-SHOCK 写真: 待ち {len(pend)}型番 / 選び済み {sum(1 for v in ch.values() if v.get('eps'))}型番"
              f" / 写真が無いので出さない {sum(1 for v in ch.values() if v.get('skip'))}型番")


if __name__ == "__main__":
    main()
