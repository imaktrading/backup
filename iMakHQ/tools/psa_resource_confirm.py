# -*- coding: utf-8 -*-
"""PSA再仕入れ — pre-search 目視確認ゲート (v2: ②候補ピッカー)。

探す前に「仕入れたい正カードか」を目視確定し、確定分だけ Mercari/SNKRDUNK 探索に渡す。
 ① 現物 = eBay出品画像(GetItem。出品に使った実画像=必ず有る)。cert→psa_cache はフォールバック。
 ② 候補 = その card番号の catalog 変種をサムネ表示しラジオで選択(解決済KEYは既定選択)。
        ① と ②(選んだ変種)が同じカードなら ON。選んだKEYが探索対象 + 商品管理シートに書戻し。
番号一致では弾けない変種取り違え(CHR/VMAX・JP/Asia)や KEY未解決を、探索前に人手で確定する。

confirm_targets(items) はローカル http サーバを立て、確定ボタンが押されるまで待ち
 {"confirmed":[{idx,key}], "rejected":[{idx,reason}]} を返す(タイムアウト/未確定は None)。
build_confirm_html / ebay_listing_image / psa_image_for_cert 以外は I/O。
"""
import html as _html

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from viewer_zoom import ZOOM_JS, ZOOM_OVERLAY, zoom_button  # noqa: E402
import http.server
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

# 現物PSA画像フォールバック: iMakTCG/data/psa_cache.json (cert#→CardImageUrl=cloudfront)。
_PSA_CACHE = None
_PSA_CACHE_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakTCG", "data", "psa_cache.json"))


def _load_psa_cache():
    """psa_cache.json を1回だけ読む (失敗しても {} で続行)。"""
    global _PSA_CACHE
    if _PSA_CACHE is None:
        try:
            with open(_PSA_CACHE_PATH, encoding="utf-8") as f:
                _PSA_CACHE = json.load(f)
        except Exception:
            _PSA_CACHE = {}
    return _PSA_CACHE


def psa_image_for_cert(cert):
    """PSA cert# → 現物PSA画像URL(psa_cache.json の CardImageUrl)。無ければ ''。"""
    _load_psa_cache()
    if not cert:
        return ""
    rec = _PSA_CACHE.get(str(cert).strip())
    url = (rec.get("CardImageUrl", "") if isinstance(rec, dict) else "") or ""
    # ★2026-07-28: 既存キャッシュは 823件中818件が /small/(380x640) のまま。PSA CDN は同じキーで
    # /large/(1140x1920) も配信するので **表示時に上げる**(取得時の /large/ 化は新規分にしか効かない)。
    return url.replace("/small/", "/large/")


_VARIETY_WORDS = (
    "ALTERNATE ART", "ALT ART", "SPECIAL ART", "MANGA ART", "FULL ART", "PARALLEL",
    "SECRET RARE", "SPECIAL CARD SET", "CHARACTER RARE", "TRAINER GALLERY", "ART RARE",
    "SUPER RARE", "PROMO", "GOLD", "FOIL",
)


def split_subject_variety(subject):
    """PSA Subject → (キャラ名, 変種名) に割る **純関数**。

    'NAMI ALTERNATE ART' → ('NAMI', 'ALTERNATE ART')
    'GLACEON VSTAR SPECIAL CARD SET' → ('GLACEON VSTAR', 'SPECIAL CARD SET')
    既知の変種語が末尾に無ければ変種は空 (推測しない = 空欄なら人が絵柄で見る)。
    """
    s = (subject or "").strip()
    up = s.upper()
    for w in sorted(_VARIETY_WORDS, key=len, reverse=True):
        if up.endswith(w):
            return s[: len(s) - len(w)].strip(), s[len(s) - len(w):].strip()
    return s, ""


# ★2026-08-13 ユーザー指摘「このてのラベル違いがちょいちょいある」。
#   PSA は同じカードを**複数の書式**で印字する。実例 (今日 実物で確認):
#     A: 1行目 "2023 ONE PIECE OP05 JP" / 3行目 "ALTERNATE ART"
#     B: 1行目 "2023 ONE PIECE JPN."     / 3行目 "OP05-ALTERNATE ART"
#   → **同じカード**なのに書式が違うだけ。人はこれを見て「違う」と押してしまい、
#     使える仕入元を捨てていた (要調査を作ったが、見比べる材料が生のままで決着しなかった)。
#   そこで **書式を畳んでから比べる**。畳んだ結果 (作品 / セット記号 / 変種 / 番号) が
#   一致すれば同じカード、というのが判定の実体。
_SET_CODE_RE = re.compile(r"\b((?:OP|EB|ST|PRB|P)-?\d{1,2})\b", re.I)


def normalize_label(brand="", variety="", number=""):
    """PSA ラベルの書式差を畳んで比較できる形にする **純関数**。

    戻り: {"set": "OP05", "variety": "ALTERNATE ART", "number": "002"}
    ★書式に依らず**中身**だけを残す。セット記号は brand 側にも variety 側にも入りうる
      ("ONE PIECE OP05 JP" / "OP05-ALTERNATE ART") ので両方から拾う。
    """
    b, v = str(brand or "").upper(), str(variety or "").upper()
    m = _SET_CODE_RE.search(b) or _SET_CODE_RE.search(v)
    set_code = m.group(1).replace("-", "").upper() if m else ""
    # 変種名からセット記号の接頭辞を落とす ("OP05-ALTERNATE ART" → "ALTERNATE ART")
    v = re.sub(r"^\s*(?:OP|EB|ST|PRB|P)-?\d{1,2}\s*[-:/]\s*", "", v).strip()
    num = re.sub(r"^#", "", str(number or "").strip()).lstrip("0") or str(number or "").strip()
    return {"set": set_code, "variety": v, "number": num}


def same_card_by_label(a, b):
    """2つのラベル (normalize_label の戻り) が同じカードを指すか **純関数**。

    セット記号・変種・番号がすべて一致 → 同じ。どれか欠けている時は False (推測しない)。
    """
    if not a or not b:
        return False
    keys = ("set", "variety", "number")
    if any(not str(a.get(k, "")).strip() or not str(b.get(k, "")).strip() for k in keys):
        return False
    return all(str(a[k]).strip() == str(b[k]).strip() for k in keys)


def psa_label_facts(cert, card_no=""):
    """cert → 目視照合に使う {number, variety, brand} (揺れないものだけ)。

    ★2026-08-02: PSA の**印字ラベルは書式が複数ある**ため、ラベル文字列そのものは
    同一性の根拠にならない。揺れないのは **番号** と **変種名**。この2つを画面に出して
    「これが合っていれば同じカード」と示すための素材を作る。cert が cache に無ければ空。
    """
    d = (_load_psa_cache() or {}).get(str(cert or "")) or {}
    if not d:
        return {"number": card_no or "", "variety": "", "brand": ""}
    _name, variety = split_subject_variety(d.get("Subject"))
    return {"number": card_no or _s(d.get("CardNumber")),
            "variety": variety,
            "brand": _s(d.get("Brand"))}


_REF_IMG_PATH = r"C:/dev/iMak_data/dedupe/psa_ref_image_cache.json"
_REF_IMG = None


def _ref_img_cache():
    """itemID → 現物画像URL のディスクキャッシュ。出品画像は変わらないので永続でよい。

    ★これが無いと「押したら何件目視できるか」を数えるだけで GetItem を対象数ぶん叩くことになり、
      ボタンのラベルに正確な件数を出せない (2026-08-09)。
    """
    global _REF_IMG
    if _REF_IMG is None:
        try:
            with open(_REF_IMG_PATH, encoding="utf-8") as f:
                _REF_IMG = json.load(f)
        except Exception:
            _REF_IMG = {}
    return _REF_IMG


def _ref_img_save():
    try:
        os.makedirs(os.path.dirname(_REF_IMG_PATH), exist_ok=True)
        tmp = _REF_IMG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_ref_img_cache(), f, ensure_ascii=False)
        os.replace(tmp, _REF_IMG_PATH)
    except Exception:
        pass


def ebay_listing_image(item_id, allow_fetch=True):
    """eBay GetItem の出品画像1枚目(i.ebayimg.com)。自分の出品=必ず有る(ended後~90日も可)。失敗 ''。

    allow_fetch=False = **ディスクキャッシュにある分だけ**返す (API を叩かない)。
    件数を数えるだけの用途 (ボタンのラベル / status_now) で使う。
    """
    if not item_id:
        return ""
    key = str(item_id).strip()
    hit = _ref_img_cache().get(key)
    if hit and hit != "-":
        return hit
    if not allow_fetch:
        return ""          # "-"(取得済だが画像なし) も "" = 呼出側は cert 画像に落ちる
    try:
        p = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI"))
        if p not in sys.path:
            sys.path.insert(0, p)
        from ebay_getitem_images import fetch_listing_images
        pics = fetch_listing_images(item_id)
        url = pics[0] if pics else ""
        # 成功は URL、「取得できたが画像なし」は "-" を焼く。例外(通信失敗)は焼かない。
        _ref_img_cache()[key] = url or "-"
        _ref_img_save()
        return url
    except Exception:
        return ""


def ref_image_known(item_id):
    """現物画像を **一度でも取りに行ったか**。件数計算が「未知」と「画像なし」を区別するため。"""
    return str(item_id).strip() in _ref_img_cache()


def _s(v):
    """list/tuple は ' / ' 連結、None は空、それ以外 str に正規化(catalog hint が list のため)。"""
    if isinstance(v, (list, tuple)):
        return " / ".join(str(x) for x in v if x not in (None, ""))
    return "" if v is None else str(v)


def _proxied(url):
    """画像URLをローカルプロキシ経由に。ブラウザのreferer由来ホットリンク制限(onepiece-cardgame等)
    や DNS/CORS を回避(サーバ側で取得して渡す)。空は空。"""
    u = _s(url)
    return ("/img?u=" + urllib.parse.quote(u, safe="")) if u else ""


_IMG_CACHE = {}
_OG_CACHE = {}


def _fetch_og_image(url):
    """商品ページ(SNKRDUNK等)の og:image を取得(キャッシュ)。失敗 ''。"""
    if not url:
        return ""
    if url in _OG_CACHE:
        return _OG_CACHE[url]
    img = ""
    for a in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            h = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', h)
            img = m.group(1) if m else ""
            break
        except Exception as e:
            if "getaddrinfo" in str(e) and a < 2:
                time.sleep(2)
                continue
            break
    _OG_CACHE[url] = img
    return img


def _resolve_image_url(u):
    """仕入候補のURL(出品ページ)→ 実画像URL。catalog/eBay画像はそのまま。
    - mercari item (m<id>) → 静的CDN画像(ページ取得不要)
    - mercari shops(/shops/product/ 等 m<id>無)→ og:image
    - snkrdunk 商品ページ → og:image
    """
    u = u or ""
    # メルカリ Shops の画像は size セグメントを large に上げる(サムネのままだと変種を見分けられない)。
    try:
        from psa_resource_html import shops_image_large
        u = shops_image_large(u)
    except Exception:
        pass
    # 既に直画像URL(CDN host / 画像拡張子)なら解決不要でそのまま(SNKRDUNK thumbnailUrl 等)。
    if "cdn.snkrdunk.com" in u or u.lower().split("?", 1)[0].endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return u
    if "mercari" in u and "/images/" not in u and "mercdn.net" not in u:
        m = re.search(r"\b(m\d{9,})\b", u)
        if m:
            return f"https://static.mercdn.net/item/detail/orig/photos/{m.group(1)}_1.jpg"
        return _fetch_og_image(u)          # mercari shops 等は og:image
    if "snkrdunk.com" in u and "/images/" not in u:
        return _fetch_og_image(u)          # snkrdunk の商品ページURL(画像でない)→ og:image
    return u


def _fix_url(u):
    """catalog の既知の壊れURLパターンを補正。
    dbs-cardgame.com の画像が /fw/jp/images/ で 404(正: /fw/images/。余分な jp/)= DBS多数。"""
    return (u or "").replace("dbs-cardgame.com/fw/jp/images/", "dbs-cardgame.com/fw/images/")


def _fetch_image(url, retries=4):
    """画像を取得して (bytes, content-type) を返す。成功のみキャッシュ(失敗は次回再試行)。失敗 (None,None)。"""
    if not url:
        return None, None
    url = _fix_url(url)
    # URLにスペース等が含まれると urllib が弾く(catalog の "Other Product Card" 等は実在するが
    # 生スペース)。既存の %xx を壊さず空白等だけエンコード。
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    if url in _IMG_CACHE:
        return _IMG_CACHE[url]
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            r = urllib.request.urlopen(req, timeout=15)
            data = r.read()
            ctype = r.headers.get("Content-Type") or "image/jpeg"
            _IMG_CACHE[url] = (data, ctype)
            return data, ctype
        except Exception as e:
            if "getaddrinfo" in str(e) and a < retries - 1:
                time.sleep(2)
                continue
            break
    return None, None


_CSS = """
body{font-family:'Segoe UI',Meiryo,sans-serif;margin:0;background:#f4f4f4;font-size:15px}
h1{background:#2a7;color:#fff;margin:0;padding:12px 16px;font-size:17px}
/* ★2026-08-02: bar を sticky top:0 にする。以前は h1 が sticky top:0 / bar が top:46px 固定で、
   h1 の文言が2〜3行に折り返すと実高さが 46px を超え、**スクロール時に bar が h1 の下に潜って
   「全部ON」が押せなくなっていた** (ユーザー報告)。h1 は説明文なので流して、操作ボタンだけ常駐させる。 */
.bar{position:sticky;top:0;background:#fff;padding:8px 16px;border-bottom:1px solid #ccc;z-index:6;
     box-shadow:0 2px 4px rgba(0,0,0,.15)}
.note{background:#fffbe6;border:1px solid #e0c000;border-left:6px solid #e0c000;margin:8px 12px;
      padding:8px 12px;font-size:13px;line-height:1.6;border-radius:4px}
.note .ex{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0}
.note .ex span{background:#fff;border:1px solid #ddd;border-radius:3px;padding:2px 6px;
      font-family:Consolas,monospace;font-size:11px}
.idf{display:flex;flex-wrap:wrap;gap:5px;margin:3px 0}
.idf b{background:#036;color:#fff;border-radius:3px;padding:2px 7px;font-size:12px;font-weight:normal}
.idf b i{font-style:normal;opacity:.7;margin-right:4px}
.bar button{font-size:14px;padding:6px 14px;margin-right:8px;cursor:pointer}
.go{background:#2a7;color:#fff;border:none;border-radius:4px;font-weight:bold;padding:8px 20px}
.grid{display:flex;flex-wrap:wrap;gap:10px;padding:12px}
/* ★2026-08-22 ユーザー要望「価格とか評価とかが見づらいから、横に枠を広げて。今の横幅の1.5倍くらい」。900 → 1350px。列が3つ (現物 / 今の仕入元 / 候補) に増えたぶん、候補のテキストが潰れていた。 */
.card{width:1350px;border:1px solid #ccc;border-radius:6px;background:#fff;padding:8px}
.card.noimg{border-color:#c33;border-width:2px}
.card.off{opacity:.55;background:#fff4f4}
.rsn{display:none;margin:4px 0;font-size:12px;width:100%}
.card.off .rsn{display:block}
.pair{display:flex;gap:6px;margin:4px 0}
.col{flex:1;min-width:0}
.col .cap{font-size:11px;color:#666;text-align:center}
.col.psa .cap{color:#06c;font-weight:bold}
.col.cat .cap{color:#2a7;font-weight:bold}
.col.psa img{width:200px;height:270px;object-fit:contain;display:block;margin:2px auto;border:1px solid #eee;background:#fafafa}
.ph{min-height:120px;display:flex;align-items:center;justify-content:center;color:#c33;
    font-size:12px;border:1px dashed #c33;margin:2px;text-align:center;padding:4px}
.cands{display:flex;flex-direction:column;gap:5px;height:290px;overflow-y:auto;overflow-x:hidden}
.cand{display:flex;align-items:flex-start;gap:8px;border:1px solid #eee;border-radius:4px;padding:3px 4px;cursor:pointer}
.cand img{width:200px;height:270px;object-fit:contain;border:1px solid #eee;margin:0;background:#fafafa}
.cand .cph{width:200px;height:270px;display:flex;align-items:center;justify-content:center;font-size:10px;color:#999;border:1px dashed #ccc}
.cand:has(input:checked){border-color:#2a7;background:#eafaf1}
.clbl{flex:1;min-width:220px;font-size:13px;word-break:break-word;line-height:1.45}
.rsn{display:none;margin-top:3px;font-size:10px;color:#888;align-items:center;gap:3px}
.cand:has(.ck:not(:checked)) .rsn{display:inline-flex}
/* ★2026-09-05: 事前ゲート(①現物 vs ②catalog候補)の理由 select は `.cand` の中ではなく
   `.card` の直下にある。上の行は候補ピッカー用なので、こちらは **一度も表示されていなかった**。
   人が選べないまま既定の `catalog` が送られ、9/5 に「カード番号すら空」の29件を含む
   39件の修正依頼が catalog に飛んだ (取り下げ済)。外した行では必ず出す。 */
.card.off > .rsn{display:block;font-size:13px;color:#333;margin-top:6px;padding:3px;
                 border:2px solid #c33;border-radius:4px;background:#fff5f5}
.card.off > .rsn.unset{background:#ffe0e0}
.rb{font-size:10px;padding:1px 5px;border:1px solid #bbb;border-radius:3px;background:#fff;cursor:pointer}
/* 要調査 = 判断を保留して残す印。捨てる系(違う/見送り)と色で区別する */
.rb.probe{border-color:#0a7;color:#076}
.rb.probe.sel{background:#0a7;color:#fff}
.vok{font-size:10px;padding:1px 5px;border-radius:3px;background:#2a7;color:#fff;font-weight:bold}
.vng{font-size:10px;padding:1px 5px;border-radius:3px;background:#e80;color:#fff;font-weight:bold}
.nng{font-size:10px;padding:1px 5px;border-radius:3px;background:#c00;color:#fff;font-weight:bold}
.aok{font-size:10px;padding:1px 5px;border-radius:3px;background:#06c;color:#fff;font-weight:bold}
.aun{font-size:10px;padding:1px 5px;border-radius:3px;background:#999;color:#fff}
.arsn{font-size:11px;color:#036;background:#eef4ff;border-radius:3px;padding:1px 5px;
      display:inline-block;margin-top:2px;line-height:1.4}
.vuni{background:#666;color:#fff;padding:3px 8px;border-radius:4px;margin:3px 0;font-size:12px}
.axs,.axd,.axu{font-size:10px;padding:1px 5px;border-radius:3px;color:#fff;margin-right:4px}
.axs{background:#2a7}
.axd{background:#c00;font-weight:bold}
.axu{background:#aaa}
.axr{font-size:11px;color:#444}
.zm{font-size:13px;padding:0 6px;border:1px solid #bbb;border-radius:3px;background:#fff;cursor:zoom-in;line-height:1.6}
#zov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:99;align-items:center;justify-content:center;cursor:zoom-out}
#zov img{max-width:46vw;max-height:88vh;object-fit:contain;background:#fff;display:block}
#zov.on{display:flex;gap:16px}
#zref,#zcand{text-align:center}
#zov .zc{color:#fff;font-size:15px;font-weight:bold;margin-bottom:6px}
#zov .zn{color:#ffd;background:rgba(0,0,0,.5);font-size:12px;margin-bottom:6px;padding:3px 8px;
      border-radius:3px;max-width:46vw}
.rb.sel{background:#c33;color:#fff;border-color:#c33;font-weight:bold}
.t{font-size:13px;word-break:break-word;margin:4px 0}
.no{font-size:12px;color:#555}
label.sel{display:flex;align-items:center;gap:6px;font-weight:bold;margin-bottom:4px}
a{font-size:12px;color:#06c}
#done{display:none;padding:40px;font-size:20px;color:#2a7;text-align:center}
"""

_JS = """
function imgFail(el,big){
  var d=document.createElement('div'); d.className=big?'ph':'cph'; d.textContent='画像なし';
  if(el.parentNode) el.parentNode.replaceChild(d,el);
}
function tog(i){var c=document.getElementById('c'+i);
  c.classList.toggle('off', !c.querySelector('input[type=checkbox]').checked);}
function setAll(v){document.querySelectorAll('.card input[type=checkbox]').forEach(function(b){
  b.checked=v; tog(b.closest('.card').dataset.idx);});}
function go(){
  var conf=[], rej=[], unset=0, first=null;
  document.querySelectorAll('.card').forEach(function(c){
    var i=parseInt(c.dataset.idx);
    var pick=c.querySelector('input[type=radio]:checked');
    if(c.querySelector('input[type=checkbox]').checked && pick){
      conf.push({idx:i, key:pick.value});
    } else {
      var r=c.querySelector('.rsn').value;
      /* ★2026-09-05: 理由が空のまま送らせない。既定で catalog が入っていたせいで
         「番号すら読めていない」行までカタログの誤りとして依頼書になっていた。 */
      if(!r){ unset++; if(!first) first=c; }
      rej.push({idx:i, reason:r});
    }
  });
  if(unset){
    alert('外した理由が未選択の行が '+unset+'件あります。理由を選ばないと、どこを直すか決められません (勝手にカタログのせいにしません)。');
    if(first){ first.scrollIntoView({block:'center'}); first.querySelector('.rsn').focus(); }
    return;
  }
  fetch('/confirm',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({confirmed:conf, rejected:rej})}).then(function(){
    document.getElementById('main').style.display='none';
    var d=document.getElementById('done'); d.style.display='block';
    d.textContent='✅ 確定'+conf.length+'件 / 不一致'+rej.length+'件。ターミナルに戻って探索完了を待ってください。';
  });
}
"""


def build_confirm_html(items):
    """items: [{idx, title, card_no, psa_image, candidates:[{key,image,label}], resolved_key,
               ebay_url, no_image}] → 確認HTML。

    ① 現物(出品PSA画像) と ② 候補(catalog変種ラジオ) を並べる。候補ありは既定ON+解決済KEYを
    既定選択、候補なしは既定OFF(catalog未収録→要追加)。
    """
    rows = []
    for it in items:
        idx = it.get("idx")
        cands = it.get("candidates") or []
        off_default = not cands
        cls = "card noimg" if it.get("no_image") else "card"
        if off_default:
            cls += " off"
        cardno = _html.escape(_s(it.get("card_no")))

        psa_img = it.get("psa_image") or ""
        psa_tag = (f"<img src='{_proxied(psa_img)}' loading='lazy' onerror='imgFail(this,1)'>" if psa_img
                   else "<div class='ph'>現物PSA画像なし<br>eBayで確認</div>")
        psa_zoom = zoom_button(_proxied(psa_img), "", label="🔍 拡大") if psa_img else ""
        psa_col = (f"<div class='col psa'><div class='cap'>① 現物(出品PSA) {psa_zoom}</div>{psa_tag}</div>")

        if cands:
            keys = [c.get("key") for c in cands]
            resolved = it.get("resolved_key")
            default = resolved if resolved in keys else (keys[0] if len(keys) == 1 else None)
            opts = []
            for c in cands:
                ck = c.get("key", "")
                chk = " checked" if ck == default else ""
                cimg = c.get("image") or ""
                ctag = (f"<img src='{_proxied(cimg)}' loading='lazy' onerror='imgFail(this,0)'>" if cimg
                        else "<div class='cph'>画像なし</div>")
                # ★2026-09-01 ユーザー要望「虫眼鏡つけて」: 目視の目的は絵柄の見比べなので、
                #   ①現物 と 候補 を **並べて**拡大する (viewer_zoom = 他の目視画面と同じ物)。
                #   単独で全画面にすると見比べられない、は初版で踏んだ失敗。
                zbtn = zoom_button(_proxied(cimg), _proxied(psa_img)) if cimg else ""
                opts.append(
                    f"<label class='cand'><input type='radio' name='pick{idx}' value='{_html.escape(_s(ck))}'{chk}>"
                    f"{ctag}<span class='clbl'>{_html.escape(_s(c.get('label')))} {zbtn}</span></label>")
            cat_inner = "<div class='cands'>" + "".join(opts) + "</div>"
        else:
            # ★2026-09-01: 「未収録→要追加」と一律に出していたため、**番号が読めていないだけ**の時も
            #   カタログのせいに見えていた (実測: 目視13件とも番号が空 = catalog を引いてすらいない)。
            #   この表示を信じると カタログへ嘘の追加依頼を出すことになる。原因で言い分ける。
            cat_inner = ("<div class='ph'>catalog候補なし<br>(未収録の可能性)</div>" if it.get("card_no")
                         else "<div class='ph'>番号が読み取れない<br>(カタログは未確認)</div>")
        cat_col = f"<div class='col cat'><div class='cap'>② 候補(正しい変種を選択)</div>{cat_inner}</div>"

        # ★2026-09-05: 先頭を **空**にする。従来は先頭が `catalog` で既定選択されていたため、
        #   理由を触らずに外すと **全部カタログのせい**として送られていた。
        #   ここは 1丁目1番地「カタログが誤りと安易に判断して依頼を出すな」に直接抵触する。
        #   探索後の画面では 2026-07-30 に同じ理由で既定を外している (こちらが漏れていた)。
        rsn = ("<select class='rsn unset' onchange=\"this.classList.toggle('unset',!this.value)\">"
               "<option value=''>▼ 外した理由を選んでください</option>"
               "<option value='catalog'>②候補が無い/合わない(catalog誤・未収録)</option>"
               "<option value='cert'>①現物が違う(商品管理シートcert#誤)</option>"
               "<option value='listing'>①②一致だが売った物と違う(出品誤)</option>"
               "<option value='unknown'>判断できない/その他</option>"
               "</select>")
        chk_cb = "" if off_default else " checked"
        rows.append(
            f"<div class='{cls}' id='c{idx}' data-idx='{idx}'>"
            f"<label class='sel'><input type='checkbox'{chk_cb} onchange=\"tog({idx})\"> 仕入れる(①=選択②)</label>"
            f"<div class='no'>{cardno}</div>"
            f"<div class='pair'>{psa_col}{cat_col}</div>"
            f"<div class='t'>{_html.escape(_s(it.get('title')))}</div>"
            f"<a href='{_html.escape(_s(it.get('ebay_url')))}' target='_blank'>元eBay出品を見る</a>"
            f"{rsn}"
            "</div>")

    head = (f"<h1>PSA再仕入れ 目視確認 — {len(items)}件。① 現物 と ② 候補(正しい変種を選択)が"
            "同じカードなら 仕入れるON → 確定。(確定した変種だけ探索＋KEYをスプシ書戻し)</h1>")
    bar = ("<div class='bar'><button class='go' onclick='go()'>✅ 確定して探索開始</button>"
           "<button onclick='setAll(true)'>全部ON</button>"
           "<button onclick='setAll(false)'>全部OFF</button>"
           "<span style='color:#c33;font-size:13px'>※候補複数なら現物と同じ変種を選択。"
           "「候補なし」=カタログ未収録の可能性 / 「番号が読み取れない」=こちら側の不具合(カタログ依頼にしない)</span></div>")
    return (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>PSA再仕入れ 確認</title>"
            f"<style>{_CSS}</style></head><body>"
            # bar を先頭 = sticky top:0 (h1 の折返しでボタンが隠れないように・2026-08-02)
            f"<div id='main'>{bar}{head}<div class='grid'>{''.join(rows)}</div></div>"
            f"<div id='done'></div>{ZOOM_OVERLAY}<script>{_JS}{ZOOM_JS}</script></body></html>")


def _serve_confirm(page_bytes, extract, timeout):
    """page を /img プロキシ付きで配信し、POST(JSON)を extract(data)->result で受けて返す。

    画像は多数並行のため ThreadingHTTPServer + サーバ側取得(ホットリンク/DNS/CORS回避)。
    確定ボタンが押される(POST)まで待ち、extract の戻りを返す。タイムアウト/未確定は None。
    """
    state = {"done": False, "result": None}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/img?"):
                u = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("u") or [""])[0]
                # 出品ページURL(mercari/snkrdunk)→実画像URLに解決してから取得。
                # これが無いとRESTOCK仕入候補のページURLをそのままHTMLとして掴み画像が出ない
                # (_resolve_image_url が定義only・未配線だった。2026-06-19 真因)。
                u = _resolve_image_url(u)
                data, ctype = _fetch_image(u)
                if data:
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "max-age=3600")
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self.send_response(404)
                    self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page_bytes)

        def do_POST(self):
            ln = int(self.headers.get("Content-Length", 0) or 0)
            try:
                data = json.loads(self.rfile.read(ln) or b"{}")
            except Exception:
                data = {}
            state["result"] = extract(data)
            state["done"] = True
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"  ブラウザで確認してください → {url}", flush=True)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    deadline = time.time() + timeout
    while not state["done"] and time.time() < deadline:
        time.sleep(0.3)
    httpd.shutdown()
    httpd.server_close()
    return state["result"] if state["done"] else None


def confirm_targets(items, timeout=10800):   # 2026-07-24 ユーザー要望で 30分→3時間に延長
    """探索前 目視確認 → {"confirmed":[{idx,key}], "rejected":[{idx,reason}]}。未確定は None。"""
    def _ex(data):
        return {"confirmed": [{"idx": int(d["idx"]), "key": d.get("key") or ""}
                              for d in (data.get("confirmed") or []) if d.get("idx") is not None],
                "rejected": [{"idx": int(d["idx"]), "reason": d.get("reason") or "unknown"}
                             for d in (data.get("rejected") or []) if d.get("idx") is not None]}
    return _serve_confirm(build_confirm_html(items).encode("utf-8"), _ex, timeout)


_JS_RESTOCK = """
function zoom(ev,btn){ev.preventDefault(); ev.stopPropagation();
  var card=btn.closest('.card'); var ref=(card&&card.dataset.ref)||'';
  var o=document.getElementById('zov');
  var L=o.querySelector('#zref'), R=o.querySelector('#zcand');
  if(ref){L.querySelector('img').src=ref; L.style.display='block';} else {L.style.display='none';}
  R.querySelector('img').src=btn.dataset.img;
  o.classList.add('on');}
function zclose(ev){ev.preventDefault(); document.getElementById('zov').classList.remove('on');}
document.addEventListener('keydown',function(e){if(e.key==='Escape')document.getElementById('zov').classList.remove('on');});
function imgFail(el,big){var d=document.createElement('div'); d.className=big?'ph':'cph';
  d.textContent='画像なし'; if(el.parentNode) el.parentNode.replaceChild(d,el);}
function upd(i){var c=document.getElementById('c'+i);
  var n=c.querySelectorAll('.ck:checked').length;
  c.classList.toggle('off', n===0);
  var b=document.getElementById('cnt'+i);
  if(b) b.textContent = n? ('RESTOCK ✓ 買う候補 '+n+'件') : 'RESTOCKしない(全候補 仕入見送り)';}
function setAll(v){document.querySelectorAll('.ck').forEach(function(b){b.checked=v;});
  document.querySelectorAll('.card').forEach(function(c){upd(c.dataset.idx);});}
function setRsn(btn){var cand=btn.closest('.cand'); var ck=cand.querySelector('.ck');
  ck.dataset.rsn=btn.dataset.r;
  cand.querySelectorAll('.rb').forEach(function(b){b.classList.toggle('sel', b.dataset.r===btn.dataset.r);});}
function go(){
  var conf=[]; var diffs=[]; var probes=[]; var skip=0; var unset=0;
  document.querySelectorAll('.card').forEach(function(c){
    var idx=parseInt(c.dataset.idx); var urls=[];
    c.querySelectorAll('.ck').forEach(function(ck){
      if(ck.checked){urls.push(ck.dataset.url);}
      else if(ck.dataset.rsn==='diff'){diffs.push({idx:idx, url:ck.dataset.url});}
      /* ★要調査は「見送り」に混ぜない。混ぜると後で拾えず、印を付けた意味が消える */
      else if(ck.dataset.rsn==='probe'){probes.push({idx:idx, url:ck.dataset.url});}
      else{skip++; if(!ck.dataset.rsn) unset++;}});
    if(urls.length) conf.push({idx:idx, urls:urls});
  });
  /* ★理由の既定選択を外したので、未選択が「黙って見送り」になる。件数を必ず見せる
     (惰性で見送りが積まれると『違う』が defect 指標として機能しなくなる)。 */
  var msg=[];
  if(diffs.length) msg.push('違う(別商品)が'+diffs.length+'件 — 検索の精度事故=即対応対象です。');
  if(probes.length) msg.push('要調査(同じかも)が'+probes.length+'件 — 台帳に記録します。補URLには書きません。');
  if(unset) msg.push('理由未選択が'+unset+'件 — 見送りとして記録します。別商品なら「違う」を押してください。');
  /* ★2026-08-01: ここは Python の**非 raw** 文字列なので \n と書くと本物の改行が埋まり、
     JS の文字列リテラルが行途中で切れて SyntaxError → この script ブロックの関数が
     **全部未定義**になる (zoom/upd/setAll/setRsn/go/imgFail が丸ごと死ぬ)。必ず \\n と書く。 */
  if(msg.length && !confirm(msg.join('\\n')+'\\n\\n確定しますか?')) return;
  fetch('/confirm',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({confirmed:conf, diffs:diffs, probes:probes, skip:skip})}).then(function(){
    document.getElementById('main').style.display='none';
    var d=document.getElementById('done'); d.style.display='block';
    d.textContent='✅ RESTOCK確定 '+conf.length+'件。ターミナルに戻ってください。';});
}
"""


# ★2026-08-02: PSA の**印字ラベルは同じカードでも書式が複数ある**。
#   実例 (どちらも OP09-050 ナミ ALTERNATE ART・柄も完全一致):
#     現物 cert 97317368 : "2024 ONE PIECE JPN."     / 3行目 "OP09-ALTERNATE ART"
#     候補 cert 165347848: "2024 ONE PIECE OP09 JP"  / 3行目 "ALTERNATE ART"
#   API が返す Brand はさらに別書式 ("ONE PIECE JAPANESE OP09-EMPERORS IN THE NEW WORLD")。
#   = セットコードが1行目に出るか3行目に出るかまで変わる。
#   ユーザー報告(2026-08-02): 「画像は酷似していてラベルが違えば、違うカードと目視で判別してしまう」
#   → 同一カードを「違う」と押す = 使える仕入元を捨てる。ラベル書式は別カードの根拠にならないので、
#     何で判定するのかを画面に明示する。
_LABEL_NOTE_HTML = (
    "<div class='note'>"
    "<b>⚠️ ラベルの書き方が違っても、同じカードのことがあります。</b>"
    " PSA は同じカードに<b>複数の印字書式</b>を使います。下は<b>全部同じカード</b>です:"
    "<div class='ex'>"
    "<span>2024 ONE PIECE <b>JPN.</b> … <b>OP09-</b>ALTERNATE ART</span>"
    "<span>2024 ONE PIECE <b>OP09 JP</b> … ALTERNATE ART</span>"
    "<span>ONE PIECE <b>JAPANESE OP09-EMPERORS IN THE NEW WORLD</b> / NAMI ALTERNATE ART</span>"
    "</div>"
    "判定は <b>①カード番号 ②変種名(ALTERNATE ART / パラレル / プロモ等) ③絵柄</b> の3つで行ってください。"
    "<b>ラベルの1行目の書き方・セットコードの位置は根拠になりません。</b>"
    " 逆に、絵柄が同じでも<b>配布が違えば別カード</b>です(例: ブースター版 と 始めようキャンペーン版)。"
    "迷ったら 🔍 で拡大して<b>絵柄</b>を見比べてください。"
    "<div style='margin-top:4px'>"
    "🖼️ <b>事前判定</b>: 現物と候補を <b>絵柄 / 変種(パラレル等の加工) / 配布(どのセットで出たか)</b> の"
    "3軸でAIが先に突き合わせています。"
    "<b>絵柄が別</b>と判定できたものだけ表示前に省いています(件数と理由はターミナルに出ます)。"
    "<b>変種・配布の不一致では省きません</b> — 変種は写真で見誤りやすく、配布は判断材料が"
    "出品タイトル(他人が書いた自由文)なので、誤って良い仕入元を捨てないためです。"
    "<span class='axd'>不一致</span> の印を付けて残すので、<b>あなたが判断してください</b>。"
    "<span class='axu'>材料なし→目視</span> は写真に写っていない/出品タイトルに書かれていない分です。"
    "残った候補には <b>一致度(%)と判断理由</b> を出しています。"
    "出品写真は角度・光・スリーブで見え方が変わるので、<b>一致度は参考値</b>です — "
    "高くても<b>採用の根拠にはせず</b>、必ず写真を見てください。低い/理由が曖昧なものは目視で落とす前提です。"
    "</div></div>")


def build_restock_html(items):
    """RESTOCK視覚確証 HTML。items: [{idx, title, card_no, ebay_url, ref_image,
    candidates:[{channel,url,price}], v8}]。① 現物 と 仕入候補(買う物の出品画像) を並べ目視一致。
    候補のurl(出品ページ)はプロキシが画像へ解決(mercari→CDN / snkrdunk→og:image)。"""
    rows = []
    for it in items:
        idx = it.get("idx")
        ref = it.get("ref_image") or ""
        ref_tag = (f"<img src='{_proxied(ref)}' loading='lazy' onerror='imgFail(this,1)'>" if ref
                   else "<div class='ph'>現物画像なし</div>")
        # ★2026-08-22 ユーザー要望「ebay出品の仕入元写真を追加して」。
        #   ① は eBay に出している写真。**今どこから買っているか**が見えないと、
        #   候補が「今より良いか」を判断できない。持っている呼出だけ出す (後方互換)。
        _sup = it.get("supply_image") or it.get("supply_url") or ""
        sup_col = ""
        if _sup:
            _slink = it.get("supply_url") or ""
            _simg = (f"<img src='{_proxied(_sup)}' loading='lazy' onerror='imgFail(this,1)'>")
            _simg = f"<a href='{_html.escape(_slink)}' target='_blank'>{_simg}</a>" if _slink else _simg
            sup_col = (f"<div class='col psa'><div class='cap'>② 今の仕入元</div>{_simg}</div>")
        # ★2026-08-02: 全候補が同じ variant_ok なら、そのバッジは**見分ける情報を持っていない**。
        #   実例 (itemID 358600821598 / OP09-050 ナミ): 8候補すべて「⚠️変種未確認」で、
        #   タイトルに「新たなる皇帝」と書いてある候補まで未確認だった (_variant_matches の
        #   セット名トークンが日英で噛み合わない)。全部に同じ警告が付くと警告として死ぬので、
        #   候補ごとのバッジは出さず「この出品では変種を文字で裏取りできていない」と1行で言う。
        _cds = it.get("candidates") or []
        _vset = {c.get("variant_ok") for c in _cds}
        _variant_uniform = len(_cds) > 1 and len(_vset) == 1
        cand_html = []
        for cd in _cds:
            u = cd.get("url") or ""
            # 画像は cd.image(SNKRDUNK=実カードthumbnail)優先、無ければ url を解決(mercari=CDN直画像)。
            # SNKRDUNK は listing ページの og:image がサイト既定ロゴで全候補同一になるため image を使う。
            imgsrc = cd.get("image") or u
            img = (f"<img src='{_proxied(imgsrc)}' loading='lazy' onerror='imgFail(this,0)'>" if imgsrc
                   else "<div class='cph'>画像なし</div>")
            price = cd.get("price")
            pstr = f"¥{price:,}" if isinstance(price, int) else (_s(price) if price else "")
            # 候補ごとに個別チェック(既定ON)。①と違う候補だけ外せる(1つ違っても全部NGにならない)。
            # チェック外す=買わない。理由は2択: 「見送り」(高い/出品者不安/納期長 等=business判断、
            # 記録のみ)と「違う」(検索が別商品を拾った誤検出=生成への改善信号→違う率トレンド)。
            # ★2026-07-30: 既定を skip から **未選択** に変更。既定 skip だと惰性で見送りが積まれ、
            #   「違う」が defect 指標として機能しない (実害: CGC 候補が毎日 見送りにされ続けた)。
            #   未選択のまま確定した場合は go() が件数を confirm で見せてから 見送り 扱いにする。
            _nm = _s(cd.get("name"))
            _nm_html = f"<br><span class='cnm'>{_html.escape(_nm[:48])}</span>" if _nm else ""
            # ★2026-08-01: 変種が確証できているかを候補ごとに出す。mercari の候補は既定で
            #   「同番号の全変種」なので、確証できていない物を黙って混ぜると人が毎回「違う」を
            #   押すことになる (=「候補が違うのは意味がない」)。確証済は先頭に並んでいる。
            #   variant_ok を持たない呼出 (旧 cache 等) はバッジ非表示 = 後方互換。
            _vok = cd.get("variant_ok")
            if _variant_uniform:
                _v_html = ""      # 全候補同じ = 見分けに使えない (カード上部で1行にまとめて出す)
            else:
                _v_html = ("<span class='vok'>✅変種一致</span>" if _vok is True
                           else "<span class='vng'>⚠️変種未確認</span>" if _vok is False else "")
            # ★2026-08-01: 番号未確認 (出品名に番号が無く、名前一致だけで拾った候補)。
            #   厳密一致が0件のときだけ出る枠なので、**変種以前に別カードの可能性**がある。
            #   変種バッジより強い警告として、こちらを優先表示する。
            if cd.get("number_ok") is False:
                _v_html = "<span class='nng'>🔴番号未確認 — 別カードの可能性あり</span>"
            # ★2026-08-02: 絵柄の事前判定 (psa_art_match)。明らかに別の物は表示前に省いてあるので、
            #   ここに出るのは same か unsure。unsure は「自信が無い=目視で落とす」ことを明示する。
            #   art を持たない呼出(旧cache / APIキー無し)はバッジ非表示 = 後方互換。
            #   ★2026-08-02(2): ユーザー「同じか違うかの判断材料がHTMLに出ていないと意味がない」
            #   → 一致度(%)と理由を **本文に出す**。title= のツールチップは出ていないのと同じ。
            _art = cd.get("art")
            _ar = _s(cd.get("art_reason"))
            _ap = cd.get("art_pct")
            _apct = f"{int(_ap)}%" if isinstance(_ap, (int, float)) else "—"
            if _art == "same":
                _v_html += f"<span class='aok'>🖼️絵柄 一致度 {_apct}</span>"
            elif _art == "unsure":
                _v_html += f"<span class='aun'>🖼️絵柄 一致度 {_apct}(要目視)</span>"
            _ar_html = (f"<br><span class='arsn'>🖼️ {_html.escape(_ar)}</span>"
                        if _art in ("same", "unsure") and _ar else "")
            # ★2026-08-02(3): 3軸 (絵柄 / 変種 / 配布) を1行ずつ出す。
            #   「同じか違うか」を人が判断するのに要る材料はこの3つ。unknown は
            #   「材料が写っていない/書かれていない」= そこは自分の目で見る、の意味。
            #   変種は写真で見誤りやすいので **省かず** ここで目立たせる (different でも残す)。
            _AXL = (("ax_art", "絵柄"), ("ax_variant", "変種"), ("ax_dist", "配布"))
            _ax_rows = []
            for _k, _cap in _AXL:
                _v = cd.get(_k)
                if not _v:
                    continue
                _rs = _s(cd.get(_k + "_reason"))
                _mark = {"same": ("axs", "一致"), "different": ("axd", "不一致"),
                         "unknown": ("axu", "材料なし→目視")}.get(_v)
                if not _mark:
                    continue
                _cls, _lbl = _mark
                _ax_rows.append(f"<span class='{_cls}'>{_cap}: {_lbl}</span>"
                                + (f"<span class='axr'>{_html.escape(_rs)}</span>" if _rs else ""))
            if _ax_rows:
                _ar_html += "<br>" + "<br>".join(_ax_rows)
            cand_html.append(
                f"<label class='cand'><input type='checkbox' class='ck' checked "
                f"data-idx='{idx}' data-url='{_html.escape(_s(u))}' data-rsn='' onchange='upd({idx})'>{img}"
                f"<span class='clbl'>{_html.escape(_s(cd.get('channel')))} {pstr} {_v_html}"
                f"{_ar_html}{_nm_html}"
                f"<br><a href='{_html.escape(_s(u))}' target='_blank'>開く</a>"
                f" <button type='button' class='zm' title='拡大'"
                f" data-img=\"{_html.escape(_proxied(imgsrc))}\" onclick='zoom(event,this)'>🔍</button>"
                # ★2026-07-30: 「違う」を『カードの同定が違う』と読まれて 見送り が選ばれ続けていた
                #   (ユーザー報告: CGC 候補を毎日 見送りにしていた)。原因は
                #   (a) 見送りが既定選択 (b) 説明文が「違うカード…は見送り」と書いていた矛盾。
                #   ラベルで意味を明示し、既定選択を外す。理由は defect 指標なので惰性で埋まると死ぬ。
                f"<span class='rsn'>外す理由:"
                f"<button type='button' class='rb' data-r='diff' onclick='setRsn(this)'"
                f" title='別商品。鑑定会社違い(CGC/BGS等) / 別カード / 別変種'>違う(別商品)</button>"
                f"<button type='button' class='rb' data-r='skip' onclick='setRsn(this)'"
                f" title='商品は合っているが今回は買わない。高い / 納期 / 出品者不安'>見送り(商品は合っている)</button>"
                # ★2026-08-09 ユーザー要望: 「ラベルの表記は違うが、同じカードの可能性が濃厚」を
                #   その場で決めずに残す受け皿。「違う」に倒すと使える仕入元を捨て、
                #   「仕入れる」に倒すと誤変種を掴む。**保留のまま印だけ付けて先に進む**。
                f"<button type='button' class='rb probe' data-r='probe' onclick='setRsn(this)'"
                f" title='ラベルの書き方は違うが同じカードの可能性が濃厚。今は判断せず、後で調べる印を付ける'>"
                f"🔎 要調査(同じかも)</button>"
                f"</span></span></label>")
        if not cand_html:
            cand_html = ["<div class='cph'>仕入候補なし</div>"]
        v8 = _s(it.get("v8"))
        v8_html = f"<div class='lbl'>{_html.escape(v8)}</div>" if v8 else ""
        # 多変種(同番号で別アート/色/パラレル/Gold が catalog に複数)は絵柄取り違えが起きやすい →
        # 目立つ⚠️バッジで「絵柄を要確認」を明示(単一変種は番号一致=正で流し見OK)。it.multi_variant が
        # 無い/False の呼出(RESTOCKゲート等)はバッジ非表示=後方互換。
        mv_html = ("<div style='background:#c00;color:#fff;font-weight:bold;padding:3px 8px;"
                   "border-radius:4px;margin:3px 0;font-size:13px'>⚠️ 多変種(同番号で複数絵柄)"
                   " — 現物と candidate の<u>絵柄</u>を要確認</div>") if it.get("multi_variant") else ""
        # 現在の仕入れ値(N)を表示 → 候補価格と見比べて「今の仕入れ値より安い供給か」が一目で分かる。
        # cost_now が無い呼出(RESTOCKゲート等)は非表示=後方互換。price_now(M)も併記(あれば)。
        _cn = _s(it.get("cost_now"))
        _pn = _s(it.get("price_now"))
        # ★2026-07-30: 同じカードの **別出品** が同じ回に出ると「さっきやったのと同じ」に見える。
        #   別物 (それぞれに補URLが要る) と分かるようにバッジで明示する。
        _sib = it.get("siblings") or []
        sib_html = ("<div style='background:#443;color:#ffd;padding:3px 8px;border-radius:4px;"
                    "margin:3px 0;font-size:13px'>🔁 同じカードの<b>別出品</b>が同時に出ています"
                    f" ({len(_sib)}件: {_html.escape(', '.join(map(str, _sib[:3])))})"
                    " — 絵柄が同じでも<b>別の出品</b>なので、それぞれに補URLが要ります</div>"
                    ) if _sib else ""
        # ★2026-08-02: 「何を見て同じと判断するのか」をカードごとに出す。
        #   ラベルの書式は揺れるが、**番号・変種名**は揺れない。現物の値を並べておけば、
        #   候補ラベルの書き方が違っても『この2つが合っているか』だけ見れば済む。
        #   psa_label が無い呼出(RESTOCKゲート等)は非表示=後方互換。
        _lab = it.get("psa_label") or {}
        idf = []
        for _cap, _k in (("番号", "number"), ("変種", "variety"), ("PSAセット", "brand")):
            _v = _s(_lab.get(_k))
            if _v:
                idf.append(f"<b><i>{_cap}</i>{_html.escape(_v)}</b>")
        # ★2026-08-13: 書式を畳んだ「照合ポイント」を出す。ラベルのどこに書いてあるかは
        #   書式で変わる (1行目 "OP05 JP" / 3行目 "OP05-ALTERNATE ART") ので、
        #   **探すべき3点**を先に示す。ユーザー指摘「このてのラベル違いがちょいちょいある」。
        _nl = normalize_label(_lab.get("brand"), _lab.get("variety"), _lab.get("number"))
        if _nl.get("set"):
            idf.append(f"<b style='background:#06a'><i>セット記号</i>{_html.escape(_nl['set'])}</b>")
        idf_html = ("<div class='idf'>" + "".join(idf) +
                    "<b style='background:#666'><i>照合</i>候補のラベルで <b>セット記号・変種・番号</b>"
                    "の3点だけ見る (行の位置や書き方は無関係)</b></div>") if idf else ""
        # 全候補が同じ variant_ok = 見分けに使えないので、候補ごとのバッジではなく事情を1行で書く
        vuni_html = ""
        if _variant_uniform:
            _same_val = next(iter(_vset))
            vuni_html = ("<div class='vuni'>🏷️ 変種の<b>文字</b>照合: 全候補とも" +
                         ("<b>一致</b>" if _same_val is True else "<b>裏取りできず</b>") +
                         " — 候補間の差が出ないので判断材料になりません。"
                         "<b>絵柄の一致度</b>と現物の写真で判断してください。</div>"
                         ) if _same_val is not None else ""
        cost_html = ""
        if _cn:
            _extra = f" / 現在価格 ¥{_html.escape(_pn)}" if _pn else ""
            cost_html = (f"<div style='background:#eef;color:#036;font-weight:bold;padding:3px 8px;"
                         f"border-radius:4px;margin:3px 0;font-size:13px'>💴 現在の仕入れ値 ¥{_html.escape(_cn)}"
                         f"{_extra}（候補がこれより安ければ◎）</div>")
        rows.append(
            f"<div class='card' id='c{idx}' data-idx='{idx}' data-ref=\"{_proxied(ref)}\">"
            f"<div class='cnt' id='cnt{idx}'>RESTOCK ✓(買う候補のみ残す)</div>"
            f"<div class='no'>{_html.escape(_s(it.get('card_no')))}</div>"
            f"{idf_html}{vuni_html}{mv_html}{sib_html}{cost_html}"
            # ★2026-07-28: タイトル/eBayリンクは候補リストの**上**に置く(候補が縦に長いと
            # 下端がスクロールしないと見えず、何のカードを見ているか分からなくなるため)。
            f"<div class='t'>{_html.escape(_s(it.get('title')))}</div>{v8_html}"
            f"<a href='{_html.escape(_s(it.get('ebay_url')))}' target='_blank'>元eBay出品</a>"
            f"<div class='pair'><div class='col psa'><div class='cap'>① 現物(出品)</div>{ref_tag}</div>"
            f"{sup_col}"
            f"<div class='col cat'><div class='cap'>仕入候補(チェック=買う / 外す=仕入見送り)</div>"
            f"<div class='cands'>{''.join(cand_html)}</div></div></div>"
            "</div>")
    # ★2026-07-30: 旧文は「買わない候補(**違うカード** / 高い / …)は仕入見送り」と書いており、
    #   別に「違う」ボタンがあるのと矛盾していた。これが 見送り 誤用の原因。意味を書き分ける。
    head = (f"<h1>RESTOCK 視覚確証 — {len(items)}件。① 現物 と見比べて<b>買う候補だけチェックを残す</b>。"
            "外した候補は理由を選ぶ: <b>違う(別商品)</b>=鑑定会社違い(CGC等)/別カード/別変種 "
            "→ 検索の精度事故として即対応する。 <b>見送り(商品は合っている)</b>=高い/納期/出品者不安。"
            "1つでも残ればRESTOCK確定 → 確定。</h1>")
    bar = ("<div class='bar'><button class='go' onclick='go()'>✅ RESTOCK確定</button>"
           "<button onclick='setAll(true)'>全部ON</button>"
           "<button onclick='setAll(false)'>全部OFF</button>"
           "<span style='color:#c33;font-size:13px'>※チェック=買う / 外す=買わない(理由: 見送り or 違う を選択)</span></div>")
    return (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>RESTOCK確証</title>"
            f"<style>{_CSS}</style></head><body>"
            # ★2026-08-02: bar を先頭に置く(sticky top:0)。h1 は折り返して高さが変わるので、
            #   h1 の下に bar を敷くと隠れる。操作ボタンを常に画面上端に出す。
            f"<div id='main'>{bar}{head}{_LABEL_NOTE_HTML}<div class='grid'>{''.join(rows)}</div></div>"
            f"<div id='zov' onclick='zclose(event)'>"
            f"<div id='zref'><div class='zc'>① 現物(出品)</div><img alt=''></div>"
            f"<div id='zcand'><div class='zc'>仕入候補</div>"
            f"<div class='zn'>ラベルの<b>書式違い</b>は別カードの根拠になりません — "
            f"<b>番号・変種名・絵柄</b>で判定</div><img alt=''></div></div>"
            f"<div id='done'></div><script>{_JS_RESTOCK}</script></body></html>")


def parse_restock_result(data):
    """RESTOCK確証 POST(JSON)→ {confirmed:[{idx,urls}], diffs:[{idx,url}], skip}。純関数(test可)。

    confirmed=買う候補(チェック残)。diffs=「違う(別カード)」と判定された個別候補(=検索が別カードを
    拾った精度事故)。**率を待たず1件でも即対応**するため、件数でなく個別(どのカードのどの候補が
    別物か)を返す。skip=見送り(高い/出品者不安/納期長 等=business判断)の件数のみ(action不要)。
    """
    out = []
    for d in (data.get("confirmed") or []):
        if d.get("idx") is None:
            continue
        urls = [u for u in (d.get("urls") or []) if u]
        if urls:
            out.append({"idx": int(d["idx"]), "urls": urls})
    diffs = [{"idx": int(d["idx"]), "url": d.get("url", "")}
             for d in (data.get("diffs") or []) if d.get("idx") is not None]
    # ★「ラベルの書き方は違うが同じカードの可能性が濃厚」= 後で調べる印 (2026-08-09 ユーザー要望)。
    #   その場では判断せず、目視を止めない。「違う」に倒すと使える仕入元を捨て、
    #   「仕入れる」に倒すと誤った変種を掴む。**保留のまま記録できる第3の受け皿**が要る。
    probes = [{"idx": int(d["idx"]), "url": d.get("url", "")}
              for d in (data.get("probes") or []) if d.get("idx") is not None]
    return {"confirmed": out, "diffs": diffs, "probes": probes,
            "skip": int(data.get("skip") or 0)}


def restock_confirm(items, timeout=10800):   # 2026-07-24 ユーザー要望で 30分→3時間に延長
    """RESTOCK視覚確証 → {confirmed:[{idx,urls}], diffs:[{idx,url}], skip} を返す
    (候補1つでも残ればRESTOCK)。未確定は None。"""
    return _serve_confirm(build_restock_html(items).encode("utf-8"), parse_restock_result, timeout)
