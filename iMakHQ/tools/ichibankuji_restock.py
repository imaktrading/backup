# -*- coding: utf-8 -*-
"""一番くじ 補URL再仕入れ (catalog無し・2段階・参照=自出品の公式画像)。

eBay在庫なし(監視くん取下げ=管理シート 売り切れ○)の一番くじを、mercari で同じ景品の
代替supplyに差し替えて再出品する。catalog は使わない(mercariに公式KEYが無く自動マッチ不能の
ため。2026-06-24 ユーザー判断)。自出品画像は公式(パッケージ品)で実写と画像検索マッチしない
ので参照(見比べ)専用 = 種にしない。

2段階(ユーザー設計):
  パスA「画像特定」 : python ichibankuji_restock.py identify [件数]
      OOS一番くじをキーワード検索 → 実写候補 → ブラウザで各景品の正しい1枚を選択 → 送信
  パスB「画像検索+確定」: python ichibankuji_restock.py expand
      選んだ実写で mercari画像検索 → 同景品を拡張 → 最終supplyを選択 → 送信
      → A列に昇格(死んだ旧A列を置換)+ B列クリア + 売り切れ○クリア → 通常②で再出品
      (補URL列 AC-AG には候補群を記録=監査用)

サーバは port 8766 (PSA Review=8765 と非競合)。
"""
import datetime
import html as _html
import json
import os
import re
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakeBayAPI")))

import sheet_io
from mercari_psa_resource import parse_mercari_items, parse_image_search_results, _chrome_major
from psa_resource_html import mercari_image_url
from ebay_getitem_images import fetch_listing_images

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
GID = 851100680
PORT = 8766
PICKS_FILE = r"C:/dev/iMak_data/dedupe/ichibankuji_picks.json"
CONFIRMED_FILE = r"C:/dev/iMak_data/dedupe/ichibankuji_confirmed.json"
REFRESH_FILE = r"C:/dev/iMak_data/dedupe/ichibankuji_refresh.json"   # 内容刷新の確定(scrape+Claude後)
COOLDOWN_FILE = r"C:/dev/iMak_data/dedupe/ichibankuji_candidate_wait.json"  # 候補待ち(候補0/見送り)台帳
COOLDOWN_DAYS = 5   # 候補待ち cooldown(この日数 identify に出さない→後日 supply 出たら再浮上)
COL_SOLD = 3       # D 売り切れ
COL_CAT = 17       # R カテゴリ
COL_TITLE = 2      # C 日本語タイトル
COL_KUJI_URL = 8   # I 公式くじURL(ユーザーが恒久入力。生成PLのV列は出品後クリアされるため別列)
COL_COST = 13      # N 仕入価格(円)= V8価格計算のSSOT(sheet_io.PRODUCT_COL_COST と一致)
_NOISE = ["新品", "未開封", "未使用", "送料無料", "即決", "匿名配送", "正規品", "限定", "おまけつき", "おまけ付き"]


# ---------------- 純粋ロジック ----------------
def clean_kw(title):
    """C列(日本語mercariタイトル)→ mercari検索語。

    ノイズ除去 + **「一番くじ」を必ず含める**(category=一番くじ確定なので、タイトルに
    無くても先頭に付ける。2026-06-24 ユーザー指摘: 一番くじ/賞名が検索に入ってないと弱い)。
    賞名(A賞/B賞/…/ラストワン)はタイトルに在れば残す(無い物は付けられない=タイトル依存)。
    """
    t = re.sub(r"【[^】]*】", " ", title or "")
    t = re.sub(r"[☆★()（）\[\]]", " ", t)
    for w in _NOISE:
        t = t.replace(w, " ")
    t = re.sub(r"\s+", " ", t).strip()
    if "一番くじ" not in t and "一番" not in t:
        t = "一番くじ " + t
    return t


def extract_prize(c_title, ebay_title=""):
    """賞ランク(A賞/B賞/…/ラストワン)を抽出。C列(日本語)優先→eBayタイトル(英語)補完。

    一番くじでない通常フィギュアを除外するため、賞は検索のマスト要素(2026-06-24 ユーザー)。
    取れなければ '' (=賞不明 → 検索が不正確になるので呼出側でフラグ)。
    """
    m = re.search(r"(ラストワン賞|ラストワン|ラスト賞|[A-Z]賞)", c_title or "")
    if m:
        g = m.group(0)
        return "ラストワン" if "ラストワン" in g else g
    et = ebay_title or ""
    m = re.search(r"\b([A-Z])\s*Prize\b", et, re.I)
    if m:
        return m.group(1).upper() + "賞"
    if re.search(r"last\s*one", et, re.I):
        return "ラストワン"
    return ""


def build_keyword(c_title, ebay_title=""):
    """検索語を組む。戻り: (keyword, prize)。一番くじ必須 + 賞必須(取れれば付与)。

    prize='' のときは賞不明(検索が通常フィギュアと混ざる恐れ)→ 呼出側でフラグ表示。
    """
    kw = clean_kw(c_title)
    prize = extract_prize(c_title, ebay_title)
    if prize and prize not in kw:
        kw = kw + " " + prize
    return kw, prize


def parse_pick(val):
    """submit値 → (skip:bool, oks:[{url,price}])。純関数(test可)。

    新形式: {"skip":bool, "oks":[{"url","price"}]}。旧形式(str/list)も後方互換で受ける。
    """
    if isinstance(val, dict):
        oks = [o for o in (val.get("oks") or []) if isinstance(o, dict) and o.get("url")]
        return (bool(val.get("skip")), oks)
    if isinstance(val, str):
        return (False, [{"url": val, "price": 0}] if (val and val != "NONE") else [])
    if isinstance(val, list):
        return (False, [{"url": u, "price": 0} for u in val if u and u != "NONE"])
    return (False, [])


def sort_oks_desc(oks):
    """可候補を価格『高い順』に並べ重複URL除去。戻り (urls[:6], cost=最高値)。純関数。

    A列=最高値supply / 補URL=以降(最大5)。価格は最高値で Revise(高い方しか残らなくても赤字回避)。
    """
    s = sorted(oks, key=lambda o: o.get("price", 0), reverse=True)
    seen, urls = set(), []
    for o in s:
        u = o.get("url")
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    cost = s[0].get("price", 0) if s else 0
    return urls[:6], cost


def _card(url, price, image, name, multi=False, cond="", ship=""):
    """候補カード。各候補に **可/否** を個別に付ける(どこまで調べたか分かる=未/可/否)。

    可=採用(複数=主+補URL最大6・identify=1つ) / 否=却下 / 未マーク=未調査。
    price は data-price に持たせ、submit 時に『高い順』ソート+最高値pricing に使う。
    image は検索結果の実URL(Shops含む)。cond/ship は詳細ページ由来(新品+送料込みのみ通過)。
    """
    img = image or mercari_image_url(url)   # 実src優先、無ければ /item/m から構築
    img_tag = (f"<img src='{_html.escape(img)}' loading='lazy'>" if img
               else "<div class=noimg>画像なし</div>")
    pr = f"¥{price:,}" if price else ""
    cs = ""
    if cond or ship:
        cs = f"<br><span style='color:#070;font-size:10px'>{_html.escape(cond)} {_html.escape(ship)}</span>"
    safe = _html.escape(url)
    return (f"<div class=cand data-url='{safe}' data-price='{int(price or 0)}' data-mark=''>"
            f"<div class=candbtns>"
            f"<button type=button class=okb onclick=\"mark(this,'ok')\">可</button>"
            f"<button type=button class=ngb onclick=\"mark(this,'ng')\">否</button></div>"
            f"{img_tag}<div class=meta>{pr}{cs}<br>"
            f"<a href='{safe}' target=_blank>開く</a></div></div>")


def build_identify_html(items):
    """パスA: 各OOS景品に 参照(公式)+ キーワード候補(実写・ラジオ)。戻り: HTML文字列。

    items: [{row,item_id,title,ref_image,candidates:[{url,price}]}]
    """
    return _page("画像特定 (パスA): 正しい景品を1つ選ぶ", items, stage="identify")


def build_expand_html(items):
    """パスB: 各景品に 参照(公式)+選んだ実写 + 画像検索の拡張候補(ラジオ)。戻り: HTML文字列。

    items: [{row,item_id,title,ref_image,picked_image,candidates:[{url,price}]}]
    """
    return _page("画像検索+確定 (パスB): 最終supplyを1つ選ぶ", items, stage="expand")


def _page(heading, items, stage):
    parts = ["<!doctype html><meta charset=utf-8><title>", _html.escape(heading), "</title>",
             "<style>body{font-family:sans-serif;margin:0;background:#f4f4f4}"
             ".hd{position:sticky;top:0;background:#2a7;color:#fff;padding:10px;font-weight:bold;z-index:9}"
             ".item{background:#fff;margin:10px;padding:10px;border-radius:6px}"
             ".title{font-weight:bold;margin-bottom:6px}.body{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-start}"
             ".ref img,.ref .noimg{max-width:150px;max-height:150px;border:2px solid #2a7}"
             ".ref{font-size:11px;color:#666;text-align:center}"
             ".cand{display:inline-block;border:1px solid #ccc;border-radius:4px;padding:4px;margin:3px;text-align:center;background:#fafafa;vertical-align:top}"
             ".cand img{max-width:120px;max-height:120px}"
             ".cand.ok{border:3px solid #07f;background:#e8f2ff}"
             ".cand.ng{border:1px solid #ccc;background:#eee;opacity:.4}"
             # 候補ごとの 可/否 ボタン(個別に印=どこまで調べたか分かる)
             ".candbtns{margin-bottom:3px}.candbtns button{font-size:13px;padding:2px 10px;margin:0 2px;border-radius:4px;border:0;cursor:pointer;color:#fff}"
             ".okb{background:#07f}.ngb{background:#c33}"
             ".cand.ok .okb{outline:3px solid #034}.cand.ng .ngb{outline:3px solid #600}"
             ".noimg{width:120px;height:120px;display:flex;align-items:center;justify-content:center;color:#999;border:1px dashed #ccc}"
             ".meta{font-size:11px}.skip{color:#a00}"
             # 商品状態: pick=可候補あり(青) / skip=見送り(灰) / 未調査=黄帯
             ".item{border:3px solid #f0c000}"   # 既定=未調査(黄)で目立たせる
             ".item.pick{border-color:#07f;background:#eef6ff}"
             ".item.skip{border-color:#bbb;background:#f2f2f2;opacity:.55}"
             ".statebtns{margin:4px 0 8px}.statebtns button{font-size:14px;padding:5px 16px;margin-right:8px}"
             ".bskip{background:#888}.btag{font-weight:bold;margin-left:6px}"
             "button{font-size:16px;padding:8px 24px;background:#07f;color:#fff;border:0;border-radius:5px;cursor:pointer}"
             "</style>"]
    multi = (stage == "expand")
    sel_hint = "同じ景品を**複数**選べる(主supply=最安+補URL)" if multi else "正しい景品を**1つ**選ぶ"
    parts.append(f"<div class=hd>{_html.escape(heading)} — 各行で{sel_hint}、下の『送信』"
                 f"&nbsp;&nbsp;<span id=counter style='background:#fff;color:#2a7;padding:2px 10px;border-radius:10px'>判断済 0 / {len(items)}</span></div>")
    for it in items:
        nm = f"row_{it['row']}"
        parts.append(f"<div class=item data-row='{it['row']}' data-multi='{1 if multi else 0}'>")
        ebay_url = f"https://www.ebay.com/itm/{it['item_id']}"
        prize = it.get("prize", "")
        prize_tag = (f"<b style='color:#070'>[{_html.escape(prize)}]</b>" if prize
                     else "<b style='color:#a00'>[⚠️賞不明=通常フィギュア混入注意]</b>")
        parts.append(f"<div class=title>{prize_tag} {_html.escape(it['title'])} "
                     f"<small>(row {it['row']} / 旧itemID {it['item_id']}) "
                     f"<a href='{ebay_url}' target=_blank>🔗 eBay出品元を見る</a></small></div>")
        # 各候補に可/否を付ける(下のカード)。この景品ごと不要なら『見送り』。状態タグで進捗表示。
        parts.append(f"<div class=statebtns>"
                     f"<button type=button class=bskip onclick=\"decideSkip('{it['row']}')\">⊘ この景品ごと見送り</button>"
                     f"<span class=btag id='tag_{it['row']}'>— 未調査</span></div>")
        # 公式くじURL欄(expand のみ)= refresh(内容刷新)用。入れて送信すると I列 に保存される。
        if stage == "expand":
            kv = _html.escape(it.get("kuji_url", "") or "", quote=True)
            parts.append(f"<div style='margin:2px 0 8px;font-size:12px'>🎯 公式くじURL(refresh用・I列保存): "
                         f"<input type=text class=kujiurl value='{kv}' "
                         f"placeholder='https://1kuji.com/products/... (任意)' style='width:55%;padding:3px'></div>")
        parts.append("<div class=body>")
        # 参照(公式)
        rimg = it.get("ref_image") or ""
        rtag = f"<img src='{_html.escape(rimg)}'>" if rimg else "<div class=noimg>公式画像なし</div>"
        parts.append(f"<div class=ref>{rtag}<div>公式(参照)</div></div>")
        # パスBは「選んだ実写」も並べる
        if stage == "expand" and it.get("picked_image"):
            parts.append(f"<div class=ref><img src='{_html.escape(it['picked_image'])}'><div>選んだ実写</div></div>")
        # 候補
        cands = it.get("candidates") or []
        if not cands:
            parts.append("<div class=skip>候補なし</div>")
        for c in cands:
            parts.append(_card(c["url"], c.get("price", 0), c.get("image", ""), nm, multi=multi,
                               cond=c.get("cond", ""), ship=c.get("ship", "")))
        # 該当なし = どの候補にも『可』を付けず『見送り』を押す(= 候補待ち5日へ)。
        parts.append("</div>")
        # 手動rescue: 候補が弱い時、自分で見つけた mercari URL を貼る(ラジオより優先)
        parts.append(f"<div style='margin-top:6px;font-size:12px'>または手動: "
                     f"<input type=text class=manurl placeholder='候補が弱い時 mercari URL を貼る(実写の出品)' "
                     f"style='width:60%;padding:3px'></div>")
        parts.append("</div>")
    parts.append("<div style='padding:16px'><button id=sendbtn onclick='submit()'>送信</button></div>")
    parts.append("""<script>
function _cands(it){ return it.querySelectorAll('.cand'); }
function _restyle(c){ c.classList.toggle('ok', c.dataset.mark==='ok'); c.classList.toggle('ng', c.dataset.mark==='ng'); }
function mark(btn, state){
  var c=btn.closest('.cand'), it=btn.closest('.item');
  c.dataset.mark = (c.dataset.mark===state) ? '' : state;   // 同じボタン再押下=解除
  if(c.dataset.mark==='ok' && it.dataset.multi!=='1'){       // identify=可は1つだけ
    _cands(it).forEach(function(o){ if(o!==c && o.dataset.mark==='ok'){o.dataset.mark=''; _restyle(o);} });
  }
  _restyle(c);
  if(it.dataset.decision==='skip') it.dataset.decision='';   // 候補を触ったら見送り解除
  _sync(it);
}
function decideSkip(row){
  var it=document.querySelector('.item[data-row="'+row+'"]'); if(!it) return;
  var on = it.dataset.decision!=='skip';
  it.dataset.decision = on ? 'skip' : '';
  if(on){ _cands(it).forEach(function(c){ c.dataset.mark=''; _restyle(c); }); }  // 見送り=全マーク解除
  _sync(it);
}
function _okCount(it){
  var n=0; _cands(it).forEach(function(c){ if(c.dataset.mark==='ok') n++; });
  var man=it.querySelector('.manurl'); if(man && man.value.trim()) n++;
  return n;
}
function _sync(it){
  var cs=_cands(it), ok=0, ng=0;
  cs.forEach(function(c){ if(c.dataset.mark==='ok')ok++; else if(c.dataset.mark==='ng')ng++; });
  var man=it.querySelector('.manurl'); if(man && man.value.trim()) ok++;
  var skip = it.dataset.decision==='skip';
  it.classList.toggle('pick', !skip && ok>0);
  it.classList.toggle('skip', skip);
  var tag=document.getElementById('tag_'+it.dataset.row);
  if(skip) tag.textContent='⊘ 見送り';
  else if(ok>0) tag.textContent='可'+ok+' 否'+ng+' 未'+(cs.length-(ok-(man&&man.value.trim()?1:0))-ng);
  else if(cs.length===0) tag.textContent='候補なし(見送り推奨)';
  else tag.textContent='否'+ng+' / 未'+(cs.length-ng)+' (未調査)';
  _counter();
}
function _counter(){
  var items=document.querySelectorAll('.item'), done=0;
  items.forEach(function(it){ if(it.dataset.decision==='skip' || _okCount(it)>0) done++; });
  var c=document.getElementById('counter'); if(c) c.textContent='判断済 '+done+' / '+items.length;
}
document.addEventListener('input', function(e){
  if(e.target && e.target.classList && e.target.classList.contains('manurl')){
    var it=e.target.closest('.item'); if(it) _sync(it);
  }
});
window.addEventListener('DOMContentLoaded', _counter);
function submit(){
  var picks={}, chosen=0, wait=0;
  document.querySelectorAll('.item').forEach(function(it){
    var skip = it.dataset.decision==='skip', oks=[];
    if(!skip){
      it.querySelectorAll('.cand[data-mark="ok"]').forEach(function(c){
        oks.push({url:c.dataset.url, price:parseInt(c.dataset.price||'0',10)});
      });
      var man=it.querySelector('.manurl'); var mv=man?man.value.trim():'';
      if(mv) oks.push({url:mv, price:0});   // 手動URL(価格不明=0、refresh側でfetch fallback)
    }
    var ku=it.querySelector('.kujiurl'); var kuv=ku?ku.value.trim():'';
    picks[it.dataset.row]={skip:skip, oks:oks, kuji:kuv};   // kuji=公式URL(I列保存)
    if(oks.length) chosen++; else wait++;          // 可ゼロ(見送り/未調査/否のみ)=候補待ち5日へ
  });
  var msg=chosen+' 行で可を選択。'+(wait>0?('残 '+wait+' 行は可ゼロ→候補待ち(5日)に入ります。'):'')+'送信しますか?';
  if(!confirm(msg)) return;
  var btn=document.getElementById('sendbtn'); if(btn){btn.disabled=true; btn.textContent='送信中...';}
  fetch('/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(picks)})
   .then(r=>r.json())
   .then(_=>{document.body.innerHTML='<h2 style="padding:24px;color:#070">✅ 送信完了('+chosen+'件確定 / '+wait+'件 候補待ち)。タブを閉じてOK。</h2>';})
   .catch(e=>{
     if(btn){btn.disabled=false; btn.textContent='送信';}
     alert('❌ 送信できませんでした: '+e+'\\n\\nサーバ経由で開いていますか?(静的ファイル直開きは不可)');
   });
}
</script>""")
    return "".join(parts)


# ---------------- I/O ----------------
# ---------------- 候補待ち cooldown (Q3: 候補0/見送りの溜まり込み防止・5日) ----------------
def _today():
    return datetime.date.today().isoformat()


def cooldown_active(rec, today):
    """台帳レコードが today 時点で有効(=identify に出さない)か。純関数。"""
    return bool(rec) and (rec.get("until", "") > today)


def filter_cooldown(oos_list, ledger, today):
    """OOS list から cooldown 中の item を除外。純関数。戻り (残list, 除外件数)。"""
    kept = [t for t in oos_list if not cooldown_active(ledger.get(str(t["item_id"])), today)]
    return kept, len(oos_list) - len(kept)


def _load_cooldown():
    try:
        return json.load(open(COOLDOWN_FILE, encoding="utf-8")) or {}
    except Exception:
        return {}


def _add_cooldown(item_ids, reason="候補0/見送り", days=COOLDOWN_DAYS, today=None):
    """item_ids を cooldown 台帳に登録(until=today+days)。後日 supply 出たら再浮上。"""
    ids = [str(i) for i in item_ids if i]
    if not ids:
        return 0
    today = today or _today()
    until = (datetime.date.fromisoformat(today) + datetime.timedelta(days=days)).isoformat()
    led = _load_cooldown()
    for iid in ids:
        led[iid] = {"until": until, "reason": reason, "set": today}
    os.makedirs(os.path.dirname(COOLDOWN_FILE), exist_ok=True)
    tmp = COOLDOWN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(led, f, ensure_ascii=False, indent=2)
    os.replace(tmp, COOLDOWN_FILE)
    return len(ids)


def get_oos_ichibankuji(limit):
    """管理シート: category=一番くじ + 売り切れ○ + B列itemID。戻り [{row,item_id,title}]。

    候補待ち cooldown(候補0/見送りで5日)中の item は除外(毎回出て溜まるのを防ぐ)。
    cooldown を除いた上で limit 件を返す。
    """
    ws = sheet_io._product_ws()
    cand = []
    for i, row in enumerate(ws.get_all_values(), start=1):
        if i == 1:
            continue
        cat = (row[COL_CAT] if len(row) > COL_CAT else "").strip()
        b = (row[1] if len(row) > 1 else "").strip()
        sold = (row[COL_SOLD] if len(row) > COL_SOLD else "").strip()
        title = (row[2] if len(row) > 2 else "").strip()
        if cat == "一番くじ" and b and sold:
            cand.append({"row": i, "item_id": b, "title": title})
    kept, n_cd = filter_cooldown(cand, _load_cooldown(), _today())
    if n_cd:
        print(f"  ⏳ 候補待ち cooldown 中 {n_cd}件 を除外(5日)")
    return kept[:limit]


def _retry(fn, tries=5, what=""):
    """transient(API 503 / getaddrinfo / timeout)はリトライ。最終失敗は送出。"""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  ⚠ {what}失敗({i+1}/{tries}): {type(e).__name__}: {str(e)[:50]} → リトライ", flush=True)
            time.sleep(5)
    raise last


def _col_letter(idx):
    """0-indexed 列番号 → A1 列文字(N列=13→'N')。"""
    return chr(65 + idx) if idx < 26 else "A" + chr(65 + idx - 26)


def build_restock_reqs(sheet_rows):
    """sheet_rows → batch_update の range/value list(純関数・test可)。

    A=新supply / B=itemID / D=売切解除 / N=cost(新supply実価格・あれば。V8計算のSSOT)。
    cost が無い行は N列を書かない(誤って既存cost を消さない)。
    """
    ncol = _col_letter(COL_COST)
    icol = _col_letter(COL_KUJI_URL)
    reqs = []
    for row, d in sheet_rows.items():
        reqs.append({"range": f"A{row}", "values": [[d.get("a", "")]]})
        reqs.append({"range": f"B{row}", "values": [[d.get("b", "")]]})
        reqs.append({"range": f"D{row}", "values": [[""]]})   # 売り切れ解除(在庫補充済)
        if d.get("cost"):
            reqs.append({"range": f"{ncol}{row}", "values": [[d.get("cost")]]})  # 新supply実価格→N列
        if d.get("kuji"):
            reqs.append({"range": f"{icol}{row}", "values": [[d.get("kuji")]]})  # 公式くじURL→I列(refresh用)
    return reqs


def write_restock(sheet_rows):
    """{row:int → {a, b, aux, cost}} を A=新supply / B=itemID / D=売切解除 / N=cost / 補URL=aux。

    新規出品でなく既存listing在庫補充なので **B列はitemIDを保持/更新**(空にしない)。
    cost(新supply実価格)を N列(V8計算SSOT)に焼く = refresh も profit計算もシート正値を使う。
    """
    if not sheet_rows:
        return 0
    ws = sheet_io._product_ws()
    ws.batch_update(build_restock_reqs(sheet_rows), value_input_option="RAW")
    aux = {row: d["aux"] for row, d in sheet_rows.items() if d.get("aux")}
    if aux:
        sheet_io.write_aux_urls(aux)
    return len(sheet_rows)


def serve_and_collect(html_str):
    """HTML を port で配信 → 送信(POST /submit)を受けて {row(str): value} を返す。"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    box = {}
    done = threading.Event()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_str.encode("utf-8"))

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(n).decode("utf-8") if n else "{}"
            try:
                box["data"] = json.loads(raw)
            except Exception:
                box["data"] = {}
            try:
                _d = box.get("data") or {}
                _nz = {k: v for k, v in _d.items() if v and v != "NONE"}
                print(f"  📥 受信: {len(_d)}行 / 選択あり {len(_nz)}行 → {_nz}", flush=True)
            except Exception:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            done.set()

    srv = HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{PORT}/"
    print(f"  🌐 ブラウザで選択 → 送信: {url}")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
    done.wait(timeout=1800)
    try:
        srv.shutdown()
    except Exception:
        pass
    return box.get("data") or {}


def _ebay_title(item_id):
    """eBay出品の Title を GetItem で取得(賞=英語 Prize の補完用)。失敗は ''。"""
    import requests
    import ebay_getitem_images as g
    try:
        k = g._load_keys()
    except Exception:
        return ""
    hdr = {"X-EBAY-API-CALL-NAME": "GetItem", "X-EBAY-API-SITEID": "0",
           "X-EBAY-API-COMPATIBILITY-LEVEL": g._COMPAT, "X-EBAY-API-APP-NAME": k["AppID"],
           "X-EBAY-API-DEV-NAME": k["DevID"], "X-EBAY-API-CERT-NAME": k["AppSecret"],
           "Content-Type": "text/xml"}
    body = ('<?xml version="1.0" encoding="utf-8"?><GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"<RequesterCredentials><eBayAuthToken>{k['AuthToken']}</eBayAuthToken></RequesterCredentials>"
            f"<ItemID>{item_id}</ItemID></GetItemRequest>")
    txt = ""
    for _ in range(4):
        try:
            txt = requests.post(g._ENDPOINT, data=body.encode("utf-8"), headers=hdr, timeout=30).text
            break
        except Exception:
            time.sleep(3)
    m = re.search(r"<Title>(.*?)</Title>", txt)
    return _html.unescape(m.group(1)) if m else ""


def _ebay_status(item_id):
    """GetItem(appトークン) → (ListingStatus, Quantity:int)。失敗は ('?', -1)。"""
    import requests
    import ebay_getitem_images as g
    try:
        k = g._load_keys()
    except Exception:
        return ("?", -1)
    hdr = {"X-EBAY-API-CALL-NAME": "GetItem", "X-EBAY-API-SITEID": "0",
           "X-EBAY-API-COMPATIBILITY-LEVEL": g._COMPAT, "X-EBAY-API-APP-NAME": k["AppID"],
           "X-EBAY-API-DEV-NAME": k["DevID"], "X-EBAY-API-CERT-NAME": k["AppSecret"], "Content-Type": "text/xml"}
    body = ('<?xml version="1.0" encoding="utf-8"?><GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"<RequesterCredentials><eBayAuthToken>{k['AuthToken']}</eBayAuthToken></RequesterCredentials>"
            f"<ItemID>{item_id}</ItemID><DetailLevel>ReturnAll</DetailLevel></GetItemRequest>")
    txt = ""
    for _ in range(4):
        try:
            txt = requests.post(g._ENDPOINT, data=body.encode("utf-8"), headers=hdr, timeout=30).text
            break
        except Exception:
            time.sleep(4)
    st = re.search(r"<ListingStatus>(.*?)</ListingStatus>", txt)
    q = re.search(r"<Quantity>(\d+)</Quantity>", txt)
    return (st.group(1) if st else "?", int(q.group(1)) if q else -1)


def _sell_token():
    """売り手OAuthトークン(Trading書込用)。refresh してから返す(PSA取下げ/復活で実績)。"""
    import json as _j
    import subprocess
    import ebay_getitem_images as g
    base = os.path.dirname(os.path.abspath(g.__file__))
    try:
        subprocess.run([sys.executable, "oauth_sell_setup.py", "refresh"], cwd=base, capture_output=True, timeout=60)
    except Exception:
        pass
    return _j.load(open(os.path.join(base, "ebay_oauth_token_sell.json"), encoding="utf-8"))["access_token"]


def _trading_iaf(call, inner, tok):
    """Trading API を IAF(売り手OAuth)で叩く。transient リトライ。戻り: レスポンスXML。"""
    import requests
    import ebay_getitem_images as g
    hdr = {"X-EBAY-API-CALL-NAME": call, "X-EBAY-API-SITEID": "0",
           "X-EBAY-API-COMPATIBILITY-LEVEL": g._COMPAT, "X-EBAY-API-IAF-TOKEN": tok, "Content-Type": "text/xml"}
    body = (f'<?xml version="1.0" encoding="utf-8"?><{call}Request xmlns="urn:ebay:apis:eBLBaseComponents">'
            f"{inner}</{call}Request>")
    last = None
    for _ in range(5):
        try:
            return requests.post(g._ENDPOINT, data=body.encode("utf-8"), headers=hdr, timeout=40).text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5)
    raise last


def _ack_ok(txt):
    m = re.search(r"<Ack>(.*?)</Ack>", txt)
    return bool(m) and m.group(1) in ("Success", "Warning")


def _short_err(txt):
    m = re.findall(r"<ShortMessage>(.*?)</ShortMessage>", txt)
    return "; ".join(m[:2]) if m else txt[:80]


def ebay_restock(item_id, tok=None):
    """eBay listing を在庫補充(新規出品でなく既存を戻す)。戻り: (item_id, action)。

    - Active & qty==0 → ReviseFixedPriceItem で Quantity=1(同 itemID 復活)
    - Completed(取下げ済) → RelistFixedPriceItem(同内容・新 itemID)
    - Active & qty>0 → 既に在庫あり(no-op)
    """
    status, qty = _ebay_status(item_id)
    tok = tok or _sell_token()
    if status == "Completed":
        # Relist は元の Quantity(取下げ時=0)をコピーするので Quantity=1 を明示(在庫復活)。
        t = _trading_iaf("RelistFixedPriceItem",
                         f"<Item><ItemID>{item_id}</ItemID><Quantity>1</Quantity></Item>", tok)
        m = re.search(r"<ItemID>(\d+)</ItemID>", t)
        if _ack_ok(t) and m:
            return m.group(1), "relist(新ID・qty=1)"
        raise RuntimeError(f"Relist失敗: {_short_err(t)}")
    if status == "Active":
        if qty > 0:
            return item_id, "在庫あり(no-op)"
        t = _trading_iaf("ReviseFixedPriceItem", f"<Item><ItemID>{item_id}</ItemID><Quantity>1</Quantity></Item>", tok)
        if _ack_ok(t):
            return item_id, "revise qty=1"
        raise RuntimeError(f"Revise失敗: {_short_err(t)}")
    raise RuntimeError(f"未対応 status={status}")


# ★ログインしない専用プロファイル(アカウント無し=BANリスクなし)。仕入アカウントの
# ログインprofileで自動化すると BAN→仕入不能の本末転倒(2026-06-25 ユーザー指摘)。
# 匿名でも画像検索は動く(expand2/5実績)。毎回まっさら匿名は bot 判定されやすいので、cookie 保温
# だけのアカウント無し dir + 非headless でブラウザらしさを出す。仕入profileとは別物。
MERCARI_PROFILE_DIR = r"C:\Users\imax2\local_data\iMakHQ\ichibankuji_scrape_profile"


def _make_driver(headless=False):
    """uc.Chrome 起動。**ログインしない専用プロファイル + 既定 非headless**。

    匿名(=BANリスクなし)だが cookie 保温 + 非headless で「まっさら匿名 headless」より弾かれにくく
    する。**仕入アカウントには絶対ログインしない**(BAN→仕入不能回避)。
    DNS一時失敗(getaddrinfo)で初期化が稀にコケるのでリトライ。
    """
    import undetected_chromedriver as uc
    os.makedirs(MERCARI_PROFILE_DIR, exist_ok=True)
    maj = _chrome_major()
    last = None
    for attempt in range(3):
        try:
            opts = uc.ChromeOptions()   # uc は options を消費するので毎回生成
            opts.add_argument(f"--user-data-dir={MERCARI_PROFILE_DIR}")   # ログイン済セッション
            if headless:
                opts.add_argument("--headless=new")
            for a in ("--no-sandbox", "--lang=ja-JP", "--window-size=1280,1400"):
                opts.add_argument(a)
            return uc.Chrome(options=opts, version_main=maj) if maj else uc.Chrome(options=opts)
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  ⚠ Chrome起動失敗(attempt {attempt+1}/3): {type(e).__name__} → リトライ", flush=True)
            time.sleep(6)
    raise last


def _href_to_image(src):
    """検索結果HTMLの各item-cellから href→実画像src を作る (item=mercdn / shops=mercari-shops 両対応)。

    Shops は assets.mercari-shops-static.com の webp で mercari_image_url では構築不能なため、
    検索結果の <img src/srcset> を直接拾う(2026-06-24 候補画像が出ない件)。
    """
    out = {}
    for b in re.split(r'data-testid="item-cell"', src)[1:]:
        hr = re.search(r'href="(/(?:item/m\w+|shops/product/\w+))"', b)
        if not hr:
            continue
        im = re.search(r'(?:src|srcset)="(https://[^"\s]+?\.(?:jpg|jpeg|png|webp)[^"\s]*)"', b)
        out["https://jp.mercari.com" + hr.group(1)] = im.group(1) if im else ""
    return out


def kw_search(drv, kw, limit):
    """段階1: キーワード検索(実写候補・通常出品のみ)。

    関連度順(価格昇順にしない): 価格昇順だと「台座のみ/アクリル台座」等の安いアクセサリが
    上位に来て本体が埋もれる(2026-06-24 ユーザー指摘)。新品フィルタも外す(recall優先・
    正しい景品を見つけるのが目的。新品担保はパスBの最終確認で)。画像は実src を付与。
    """
    url = "https://jp.mercari.com/search?keyword=" + urllib.parse.quote(kw) + "&status=on_sale"
    drv.get(url)
    time.sleep(8)
    src = drv.page_source
    imgmap = _href_to_image(src)
    items = parse_mercari_items(src)[:limit]
    for it in items:
        it["image"] = imgmap.get(it["href"], "")
    return items


def _image_search_once(drv, seed_path):
    """画像検索を1回実行 → page_source を返す(失敗/結果0は '')。

    結果が揃うまでポーリング(揃えば早期return。固定sleepより速く確実)。
    """
    from selenium.webdriver.common.by import By
    try:
        drv.get("https://jp.mercari.com/search?keyword=%20")
        time.sleep(6)
        btn = drv.find_elements(By.CSS_SELECTOR, '[data-testid="image-search-button"]')
        if not btn:
            return ""
        btn[0].click()
        time.sleep(2)
        fin = drv.find_elements(By.CSS_SELECTOR, 'input[type="file"]')
        if not fin:
            return ""
        fin[0].send_keys(seed_path)
        for _ in range(8):                       # 最大~24s、結果が出たら即抜け
            time.sleep(3)
            src = drv.page_source
            if parse_image_search_results(src):
                return src
        return ""
    except Exception:
        return ""


def image_search_from_url(drv, mercari_url, limit, tries=3):
    """段階2: 選んだ実写で mercari画像検索 → 同景品候補。

    expand で3件連続検索すると burst で**間欠的に0**を返す(単独実行なら出る=2026-06-25 実機確認)。
    0件なら再検索リトライ(tries回)。待ち時間でなく間欠failが主因なので retry が効く。
    """
    import requests
    img = mercari_image_url(mercari_url)
    if not img:
        return []
    p = os.path.join(os.environ.get("TEMP", "."), "ichi_seed.jpg")
    try:
        with open(p, "wb") as f:
            f.write(requests.get(img, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).content)
    except Exception:
        return []
    src = ""
    for attempt in range(tries):
        src = _image_search_once(drv, p)
        if src:
            break
        print(f"     ↻ 画像検索0件 → リトライ {attempt + 1}/{tries}", flush=True)
        time.sleep(4)
    if not src:
        return []
    res = parse_image_search_results(src)
    # 画像検索モーダルから href→実画像src(item=mercdn / shops=mercari-shops 両対応)。
    # parse_image_search_results は画像を返さない+Shopsは mercari_image_url で構築不可のため。
    imgmap = {}
    for seg in re.split(r'data-location="image_search:similar_looks_modal:item_thumbnail"', src)[1:]:
        hr = re.search(r'href="(/(?:item/m\w+|shops/product/\w+))"', seg)
        if not hr:
            continue
        im = re.search(r'(?:src|srcset)="(https://[^"\s]+?\.(?:jpg|jpeg|png|webp)[^"\s]*)"', seg)
        imgmap["https://jp.mercari.com" + hr.group(1)] = im.group(1) if im else ""
    onsale = sorted([r for r in res if not r["sold"]], key=lambda x: x["price"])
    for r in onsale:
        r["image"] = imgmap.get(r["href"], "")
    return onsale[:limit]


_KEEP_COND = ("新品、未使用", "未使用に近い")   # 新品扱い。これ以外(目立った傷/やや傷…)は除外
_COND_VALUES = r"(新品、未使用|未使用に近い|目立った傷や汚れなし|やや傷や汚れあり|傷や汚れあり|全体的に状態が悪い)"


def _parse_cond_ship(s):
    """page_source → (状態, 送料負担)。**ラベル直後の値だけ**見る(純関数・test可)。

    mercari は1ページに送料込み/着払い・各状態語が UI/関連商品/dropshipping注記で**常に両方**
    出るため、全ページ grep は誤判定(2026-06-25 着払い混入バグ)。商品詳細の『商品の状態』
    『配送料の負担』の **直後の値**(=その商品の実値)を非貪欲マッチで取る。取れねば '' (fail-closed=除外)。
    """
    cm = re.search(r"商品の状態.{0,120}?" + _COND_VALUES, s, re.S)
    sm = re.search(r"配送料の負担.{0,120}?(送料込み|着払い)", s, re.S)
    return (cm.group(1) if cm else "", sm.group(1) if sm else "")


MIN_SELLER_REVIEWS = 100          # PSA 補URL と同値 (mercari_psa_resource の既定)


def _cond_ship(drv, url):
    """商品詳細ページから (状態, 送料負担, 評価件数) を取得。失敗は ('','',None)。

    評価件数は PSA 側と同じ parser を使う(二重実装しない)。取れない=None は個人セラーなら
    不合格側に倒す(fail-closed。呼び手の candidate_passes_filter が判定)。
    """
    try:
        drv.get(url)
        time.sleep(3)
        src = drv.page_source
        cond, ship = _parse_cond_ship(src)
        try:
            import mercari_psa_resource as mp
            reviews = mp._parse_seller_reviews(src)
        except Exception:
            reviews = None
        return (cond, ship, reviews)
    except Exception:
        return ("", "", None)


def _filter_new_freeship(drv, raw):
    """候補を **新品 かつ 送料込み かつ セラー条件** で絞る(詳細ページ訪問)。

    状態/送料/評価は検索結果に無く詳細ページにしかないため各候補を訪問(やや遅い)。
    - 状態: 新品、未使用 / 未使用に近い のみ (2026-06-24 ユーザー: 新品+送料込みのみ)
    - 送料: 送料込みのみ (着払いは実原価が過小表示になる)
    - セラー: **PSA 補URL と同じ条件**に統一 (2026-07-28 ユーザー指示)。
      = 個人セラーは評価件数≥MIN_SELLER_REVIEWS、Shops(業者)は評価不問。
      判定は mercari_psa_resource.candidate_passes_filter を直接使う(規約の二重実装を避ける)。
      import できない時は従来どおり新品+送料込みのみで通す(先読みを止めない)。
    """
    try:
        import mercari_psa_resource as mp
    except Exception:
        mp = None
    kept = []
    for c in raw:
        cond, ship, reviews = _cond_ship(drv, c["href"])
        if cond not in _KEEP_COND:
            continue
        if mp is not None:
            ok = mp.candidate_passes_filter(cond, ship, reviews,
                                            mp._is_shops_url(c["href"]),
                                            min_reviews=MIN_SELLER_REVIEWS)
        else:
            ok = (ship == "送料込み")
        if not ok:
            continue
        c["cond"], c["ship"], c["reviews"] = cond, ship, reviews
        kept.append(c)
    return kept


# ---------------- 候補の先読みキャッシュ (2026-07-28) ----------------
# 目視はユーザーのタイミングでやりたいが、検索は待ちたくない ⇒ 夜のうちに候補だけ貯める。
# PSA 側 (psa_hoju_fill の psa_research_cache) と同じ考え方。書込は一切せず候補のみ。
IDENTIFY_CACHE = r"C:/dev/iMak_data/dedupe/ichibankuji_identify_cache.json"
IDENTIFY_CACHE_DAYS = 3          # PSA の _entry_fresh と同じ鮮度窓


def _identify_cache_load():
    try:
        with open(IDENTIFY_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _identify_cache_save(cache):
    os.makedirs(os.path.dirname(IDENTIFY_CACHE), exist_ok=True)
    with open(IDENTIFY_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def _identify_cache_fresh(entry, today=None):
    """当日〜IDENTIFY_CACHE_DAYS 以内か(純関数)。日付不正/未来日は False (fail-closed)。"""
    if not isinstance(entry, dict) or not entry.get("date"):
        return False
    try:
        t = datetime.date.fromisoformat(today or datetime.date.today().isoformat())
        age = (t - datetime.date.fromisoformat(entry["date"])).days
    except Exception:
        return False
    return 0 <= age <= IDENTIFY_CACHE_DAYS


def _identify_scrape(targets, cand_n, use_cache=True):
    """OOS対象 → 候補付き items。**キャッシュが新しい対象は再検索しない**(driver も起こさない)。

    戻り値の形は従来の pass_identify 内で組んでいたものと同一 (UI 側は無改修)。
    """
    cache = _identify_cache_load() if use_cache else {}
    today = datetime.date.today().isoformat()
    todo = [t for t in targets
            if not (use_cache and _identify_cache_fresh(cache.get(str(t["item_id"])), today))]
    items, drv = [], None
    if todo:
        print(f"  検索が要る対象: {len(todo)}/{len(targets)}件 (残りはキャッシュ再利用)", flush=True)
        drv = _make_driver()
    try:
        if drv:
            drv.set_page_load_timeout(50)
        for i, t in enumerate(targets, 1):
            iid = str(t["item_id"])
            ent = cache.get(iid)
            if use_cache and _identify_cache_fresh(ent, today):
                items.append({k: ent[k] for k in
                              ("row", "item_id", "title", "prize", "ref_image", "candidates")})
                continue
            pics = fetch_listing_images(t["item_id"])
            et = _ebay_title(t["item_id"])             # 一番くじ+賞は生成済eBayタイトルが確実
            kw, prize = build_keyword(t["title"], et)  # C列(日本語作品/キャラ)+一番くじ+賞
            print(f"  [{i}/{len(targets)}] 賞={prize or '不明'} kw={kw[:32]}", flush=True)
            try:
                raw = kw_search(drv, kw, cand_n)
            except Exception as e:  # noqa: BLE001
                print(f"     ⚠ 検索失敗: {e}"); raw = []
            it = {"row": t["row"], "item_id": t["item_id"], "title": t["title"],
                  "prize": prize, "ref_image": pics[0] if pics else "",
                  "candidates": [{"url": c["href"], "price": c["price"],
                                  "image": c.get("image", "")} for c in raw]}
            items.append(it)
            cache[iid] = {**it, "date": today}
            _identify_cache_save(cache)      # 1件ごとに保存(途中死しても貯めた分は残す)
    finally:
        if drv:
            try: drv.quit()
            except Exception: pass
    return items


def pass_prefetch(n, cand_n):
    """無人の候補先読み。**目視UIを開かず・書込もしない**。夜間 cron 用 (2026-07-28)。"""
    targets = get_oos_ichibankuji(n)
    print(f"候補先読み: OOS一番くじ {len(targets)}件 (各最安{cand_n}候補)")
    if not targets:
        print("対象なし"); return
    items = _identify_scrape(targets, cand_n)
    n_cand = sum(len(it.get("candidates") or []) for it in items)
    print(f"✅ 先読み完了: {len(items)}件 / 候補 {n_cand}件 → {IDENTIFY_CACHE}")
    print("   目視は「🎯 一番くじ 補URL特定」ボタンで好きなタイミングに(再検索せず即表示)")


# ---------------- パス ----------------
def pass_identify(n, cand_n):
    targets = get_oos_ichibankuji(n)
    print(f"画像特定(パスA): OOS一番くじ {len(targets)}件 (各最安{cand_n}候補)")
    if not targets:
        print("対象なし"); return
    items = _identify_scrape(targets, cand_n)
    picks = serve_and_collect(build_identify_html(items))
    # picks: {row(str): {skip, oks:[{url,price}]}}。可1つを picked_url に。見送り/可ゼロは候補待ち。
    saved = []
    cooldown_ids = []
    by_row = {str(it["row"]): it for it in items}
    for row, val in picks.items():
        if row not in by_row:
            continue
        it = by_row[row]
        skip, oks = parse_pick(val)
        if skip or not oks:
            cooldown_ids.append(it["item_id"]); continue
        saved.append({"row": int(row), "item_id": it["item_id"], "title": it["title"],
                      "ref_image": it["ref_image"], "picked_url": oks[0]["url"]})
    if cooldown_ids:
        n = _add_cooldown(cooldown_ids, reason="identify:見送り/該当なし")
        print(f"  ⏳ 識別できず {n}件 を候補待ち({COOLDOWN_DAYS}日)に登録")
    os.makedirs(os.path.dirname(PICKS_FILE), exist_ok=True)
    with open(PICKS_FILE, "w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 画像特定 {len(saved)}件 保存: {PICKS_FILE}")
    print("   次: python ichibankuji_restock.py expand")


def pass_expand(cand_n, dry=False):
    if not os.path.exists(PICKS_FILE):
        print(f"picks がありません。先に identify を実行: {PICKS_FILE}"); return
    picks = json.load(open(PICKS_FILE, encoding="utf-8"))
    picks = [p for p in picks if p.get("picked_url")]
    print(f"画像検索+確定(パスB): {len(picks)}件 (各最安{cand_n}候補)")
    if not picks:
        print("特定済(picked_url)が無い"); return
    try:
        meta = _sheet_meta()   # 既存 I列(公式くじURL)を欄に pre-fill するため
    except Exception:
        meta = {}
    drv = _make_driver()
    items = []
    try:
        drv.set_page_load_timeout(50)
        for i, p in enumerate(picks, 1):
            print(f"  [{i}/{len(picks)}] 画像検索: {p['title'][:30]}", flush=True)
            try:
                raw = image_search_from_url(drv, p["picked_url"], cand_n)
            except Exception as e:  # noqa: BLE001
                print(f"     ⚠ 画像検索失敗: {e}"); raw = []
            if not raw:
                # 画像検索0(bot判定/timing)→ キーワード検索フォールバック(identifyで実績あり)。
                #   「候補なし」で手詰まりにしない。新品+送料込みは下の filter で担保。
                kw, _pz = build_keyword(p["title"], _ebay_title(p["item_id"]))
                print(f"     画像検索0 → キーワード検索 fallback: {kw[:32]}", flush=True)
                try:
                    raw = kw_search(drv, kw, cand_n)
                except Exception as e:  # noqa: BLE001
                    print(f"     ⚠ キーワード検索も失敗: {e}"); raw = []
            print(f"     候補 {len(raw)}件 → 状態/送料 確認中(新品+送料込みのみ)...", flush=True)
            raw = _filter_new_freeship(drv, raw)
            print(f"     新品+送料込み {len(raw)}件", flush=True)
            items.append({"row": p["row"], "item_id": p["item_id"], "title": p["title"],
                          "ref_image": p.get("ref_image", ""),
                          "picked_image": mercari_image_url(p["picked_url"]),
                          "kuji_url": (meta.get(p["row"]) or {}).get("kuji_url", ""),  # I列 pre-fill
                          "candidates": [{"url": c["href"], "price": c["price"],
                                          "image": c.get("image", "") or mercari_image_url(c["href"]),
                                          "cond": c.get("cond", ""), "ship": c.get("ship", "")}
                                         for c in raw]})
    finally:
        try: drv.quit()
        except Exception: pass
    finals = serve_and_collect(build_expand_html(items))
    by_row = {it["row"]: it for it in items}   # row → 表示item(item_id 等)
    confirmed = {}   # row → {item_id, a(主=最高値supply), aux(補・最大5), cost(最高値)}
    cooldown_ids = []
    for row, val in finals.items():
        r = int(row)
        it = by_row.get(r) or {}
        skip, oks = parse_pick(val)
        if skip or not oks:
            if it.get("item_id"):
                cooldown_ids.append(it["item_id"])   # 見送り/可ゼロ = 候補待ち
            continue
        # 高い順に並べ替え(A列=最高値supply / 補URL=以降最大5) + 最高値を cost に(赤字回避)
        urls, cost = sort_oks_desc(oks)
        kuji = (val.get("kuji") or "").strip() if isinstance(val, dict) else ""
        confirmed[r] = {"item_id": it.get("item_id", ""), "a": urls[0],
                        "aux": urls[1:6], "cost": cost, "kuji": kuji}   # kuji→I列(refresh用)
    if cooldown_ids:
        n = _add_cooldown(cooldown_ids, reason="expand:見送り/候補なし")
        print(f"  ⏳ 候補待ち {n}件 を {COOLDOWN_DAYS}日 cooldown に登録(次回identifyで除外)")
    if not confirmed:
        print("確定なし(全行 見送り/候補待ち)"); return
    # 書込前に確定を保存(API障害で落ちても再選択不要 → write で再適用)
    _save_confirmed(confirmed)
    print(f"  💾 確定を保存(失敗時は再選択不要・write で再適用): {CONFIRMED_FILE}")
    if dry:
        print(f"\n🧪 DRY-RUN: スプシ書込なし。記録予定 {len(confirmed)}件(eBayは触らない=在庫復活+刷新は refresh):")
        for r in sorted(confirmed):
            d = confirmed[r]
            print(f"   row{r} itemID={d['item_id']} cost¥{d.get('cost') or '?'}: A列← {d['a']}")
            for u in d["aux"]:
                print(f"            補URL← {u}")
        print(f"   → 本番記録: python ichibankuji_restock.py write")
        return
    try:
        n = _write_supplies(confirmed)
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ スプシ記録が最終的に失敗: {type(e).__name__}: {str(e)[:60]}")
        print(f"   選択は保存済 → 復旧: python ichibankuji_restock.py write")
        return
    print(f"\n✅ 記録完了 {n}件: A列=新supply / B列=itemID / 売切解除 / N列=cost / 補URL。"
          f"\n   eBayは未変更 → 在庫復活+内容刷新は: python ichibankuji_restock.py refresh → refresh write")


def _save_confirmed(confirmed):
    """confirmed = {row:int → {item_id, a, aux}} を保存(書込失敗時の再適用用)。"""
    payload = {"items": {str(k): v for k, v in confirmed.items()}}
    os.makedirs(os.path.dirname(CONFIRMED_FILE), exist_ok=True)
    with open(CONFIRMED_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_confirmed():
    d = json.load(open(CONFIRMED_FILE, encoding="utf-8"))
    return {int(k): v for k, v in (d.get("items") or {}).items()}


def _write_supplies(confirmed):
    """confirmed → **スプシのみ記録**(eBayは触らない)。戻り: 記録件数。

    A列=新supply / B列=既存itemID(relistしない) / D列=売切解除 / N列=cost / AC-AG=補URL / I列=kuji。
    eBay の在庫復活(qty=1)+ 内容刷新は **refresh の CSV入稿で一括**(古い中身で売れる瞬間を作らない・
    eBay更新1回・relistしないので itemID 不変=stale無し。2026-06-25 ユーザー方針)。
    """
    sheet_rows = {}
    for row in sorted(confirmed):
        d = confirmed[row]
        sheet_rows[row] = {"a": d.get("a", ""), "b": (d.get("item_id") or "").strip(),
                           "aux": d.get("aux", []), "cost": d.get("cost", 0), "kuji": d.get("kuji", "")}
        print(f"  📝 row{row}: スプシ記録(eBay未変更) itemID={sheet_rows[row]['b']} cost¥{d.get('cost') or '?'}")
    return _retry(lambda: write_restock(sheet_rows), what="スプシ書込")


def _apply_restock(confirmed):
    """[DEPRECATED 2026-06-25] eBay在庫補充(Revise/Relist)+スプシ。Option B で expand/write は
    _write_supplies(スプシのみ)に移行。在庫復活は refresh CSV入稿に一本化。未使用(参照用に残置)。

    eBay: qty0 Active→Revise qty=1(同ID) / Completed→Relist(新ID)。B列はそのitemIDを保持/更新。
    スプシ: A列=新supply / B列=補充後itemID / 売り切れ解除 / 補URL。
    """
    tok = None
    try:
        tok = _sell_token()
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ 売り手トークン取得失敗: {e}(eBay補充はskip・スプシのみ)")
    sheet_rows = {}
    for row in sorted(confirmed):
        d = confirmed[row]
        item_id = (d.get("item_id") or "").strip()
        new_id, action = item_id, "no_itemid(eBay補充skip)"
        if item_id and tok:
            try:
                new_id, action = _retry(lambda: ebay_restock(item_id, tok), what=f"row{row} eBay在庫補充")
            except Exception as e:  # noqa: BLE001
                action = f"❌FAILED:{type(e).__name__}"
                new_id = item_id
                print(f"  ❌ row{row} eBay在庫補充 最終失敗: {e}(スプシは書く)")
        print(f"  📦 row{row}: {action}  itemID={new_id}")
        sheet_rows[row] = {"a": d.get("a", ""), "b": new_id, "aux": d.get("aux", []),
                           "cost": d.get("cost", 0),   # 新supply実価格→N列(V8 SSOT)
                           "kuji": d.get("kuji", "")}  # 公式くじURL→I列(refresh用)
    n = _retry(lambda: write_restock(sheet_rows), what="スプシ書込")
    return n


def pass_write():
    """確定(保存済 or dry後)を **スプシのみ記録**(eBay触らない)。dry/失敗後の復旧に使う。"""
    if not os.path.exists(CONFIRMED_FILE):
        print(f"確定ファイルなし: {CONFIRMED_FILE}"); return
    confirmed = _load_confirmed()
    if not confirmed:
        print("確定なし"); return
    print(f"確定 {len(confirmed)}件 を スプシ記録(eBay未変更)...")
    n = _write_supplies(confirmed)
    print(f"✅ 記録完了 {n}件: A列=新supply / B列=itemID / 売切解除 / N列=cost / 補URL。"
          f"\n   eBay在庫復活+刷新は: refresh → refresh write → 出品くん入稿")


# ---------------- 内容刷新 (refresh): タイトル/itemSP/価格を新規ロジックで刷新 → FileExchange Revise CSV ----------------
def _gen():
    """新規生成器 ichibankuji_to_csv を import 流用(無改変)。戻り (module, gen_dir)。"""
    gd = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMak_ichibankuji"))
    if gd not in sys.path:
        sys.path.insert(0, gd)
    import ichibankuji_to_csv as gen
    return gen, gd


def _sheet_meta():
    """管理シートを1回読み、{row(int): {title(C), kuji_url(I), item_id(B)}} を返す。

    item_id は **現B列**(write の Relist で新IDに更新済)。confirmed.json の item_id は relist 後
    stale になるため、refresh は現B列を正とする。
    """
    ws = sheet_io._product_ws()
    out = {}
    for i, row in enumerate(ws.get_all_values(), start=1):
        if i == 1:
            continue
        title = (row[COL_TITLE] if len(row) > COL_TITLE else "").strip()
        kuji = (row[COL_KUJI_URL] if len(row) > COL_KUJI_URL else "").strip()
        item_id = (row[1] if len(row) > 1 else "").strip()
        out[i] = {"title": title, "kuji_url": kuji, "item_id": item_id}
    return out


def _match_prize(prize, prizes):
    """extract_prize の賞(A賞/ラストワン 等)を scrape の prizes[].prize に突合。無ければ None。

    scrape は 'ラストワン賞'、extract_prize は 'ラストワン' と末尾差があるので 賞 を除いて比較。
    """
    if not prize:
        return None
    key = prize.rstrip("賞")
    for p in prizes:
        pp = (p.get("prize") or "").rstrip("賞")
        if pp == key or (key and key in pp):
            return p
    return None


def _manual_prize(prizes):
    """賞マッチ失敗時の手動賞指定(CLI)。番号入力で1つ選ぶ。空/s = skip(None)。"""
    if not prizes:
        print("      賞候補なし → skip")
        return None
    print("      ⚠️ 賞マッチ失敗。手動指定してください:")
    for i, p in enumerate(prizes, 1):
        print(f"        {i}. {p.get('prize','')}: {(p.get('name') or '')[:36]}")
    try:
        ans = input("      番号 (空/s=skip): ").strip()
    except EOFError:
        ans = ""
    if ans.isdigit() and 1 <= int(ans) <= len(prizes):
        return prizes[int(ans) - 1]
    return None


def _build_refreshed_row(gen, base_desc, series_name, release_year, price_jpy, main_image,
                         kuji_url, supply_url, prize_p, cost_jpy):
    """1賞ぶんを Claude+pricing+build_row で刷新。戻り (ebay_row|None, new_title, price, note)。"""
    series_data = {
        "series_name": series_name, "release_year": release_year, "price_jpy": price_jpy,
        "main_image": main_image, "url": kuji_url, "mercari_url": supply_url, "prizes": [],
    }
    prize_data = {"prize": prize_p.get("prize", ""), "name": prize_p.get("name", ""),
                  "size_cm": prize_p.get("size_cm", "")}
    claude_result = gen.analyze_with_claude(series_data, prize_data)
    if not claude_result:
        return None, "", 0, "Claude失敗"
    if not claude_result.get("is_figure", True):
        return None, claude_result.get("title", ""), 0, "非フィギュア判定→skip"

    # pricing: cost = 新supply実価格。新発売 median 信頼性低のため gap_limit=10.0(generator 同条件)
    listing_price = gen.DEFAULT_PRICE
    ebay_median = 0.0
    price_status = "GO"
    try:
        if cost_jpy and int(cost_jpy) > 0:
            from pricing_engine import compute_listing_price
            try:
                from listing_common import PRICE_CHECK_CONFIG
                if PRICE_CHECK_CONFIG.get("ichibankuji", {}).get("enabled"):
                    from check_csv_core import fetch_ebay_market_median
                    _kw = " ".join((claude_result.get("title", "") or "").split()[:5])
                    ebay_median, _hits = fetch_ebay_market_median(
                        keywords=_kw, category_ids=str(gen.EBAY_CATEGORY),
                        condition_id=str(gen.CONDITION_ID), limit=30)
            except Exception:
                pass
            pricing = compute_listing_price(int(cost_jpy), ebay_median, gen.PROFIT_CATEGORY,
                                            gap_limit_override=10.0)
            listing_price = max(pricing.get("price", gen.DEFAULT_PRICE), 9.98)
            price_status = pricing.get("status", "GO")
    except Exception as e:  # noqa: BLE001
        print(f"      ⚠️ pricing失敗: {e}(DEFAULT_PRICE使用)")

    ebay_row = gen.build_row(series_data, prize_data, claude_result, listing_price, base_desc)

    # 物理ゲート(新規生成と同じ品質基準): error は HOLD=skip(fail-closed)
    try:
        from listing_common import gate_row_or_hold
        allowed, viol = gate_row_or_hold(ebay_row, category="ichibankuji",
                                         sku=ebay_row.get("CustomLabel", ""),
                                         price_status=price_status, median_usd=ebay_median)
        if not allowed:
            errs = [f"{f}={i}" for f, i, s in viol if s == "error"]
            return None, ebay_row.get("*Title", ""), listing_price, f"HOLD:{errs}"
    except Exception as e:  # noqa: BLE001
        print(f"      ⚠️ gate skip(非致命): {e}")

    return ebay_row, ebay_row.get("*Title", ""), listing_price, "OK"


def pass_refresh():
    """確定(confirmed.json)の各行を scrape+Claude で刷新 → プレビュー表示 + REFRESH_FILE 保存。

    dry必須(表示→明示 `refresh write`)。eBay/CSV への書込はしない。
    """
    if not os.path.exists(CONFIRMED_FILE):
        print(f"確定ファイルなし: {CONFIRMED_FILE}(先に identify→expand)"); return
    confirmed = _load_confirmed()
    if not confirmed:
        print("確定なし"); return
    gen, gd = _gen()
    base_path = os.path.join(gd, "ICHIBANKUJI.txt")
    base_desc = open(base_path, encoding="utf-8").read() if os.path.exists(base_path) else None
    meta = _sheet_meta()

    # 同一くじURLは1回 scrape(重い処理を集約)
    drv = _make_driver()
    scraped = {}
    try:
        drv.set_page_load_timeout(60)
        urls = {(meta.get(r) or {}).get("kuji_url", "") for r in confirmed}
        for u in sorted(x for x in urls if x and x != "-"):
            print(f"  🔎 scrape: {u}", flush=True)
            try:
                scraped_sd = _retry(lambda: gen.scrape_1kuji(drv, u), tries=3, what="scrape_1kuji")
            except Exception as e:  # noqa: BLE001
                print(f"     ⚠ scrape失敗: {e}"); scraped_sd = None
            scraped[u] = scraped_sd
    finally:
        try: drv.quit()
        except Exception: pass

    planned = []   # [{item_id, sku, row, old_title, new_title, price}]
    for row in sorted(confirmed):
        d = confirmed[row]
        m = meta.get(row) or {}
        # 現B列itemID優先(write の Relist で新IDに変わっても追従。confirmed の旧IDは stale)
        item_id = (m.get("item_id") or d.get("item_id") or "").strip()
        kuji_url = (m.get("kuji_url") or "").strip()
        title_jp = m.get("title") or ""
        supply = (d.get("a") or "").strip()
        print(f"\n  [row{row}] itemID={item_id} {title_jp[:30]}", flush=True)
        if not kuji_url or kuji_url == "-":
            print("     ⚠️ I列(公式くじURL)空 → skip(刷新不可)"); continue
        sd = scraped.get(kuji_url)
        if not sd or not sd.get("prizes"):
            print("     ⚠️ scrape不可/賞0 → skip"); continue
        prize = extract_prize(title_jp, _ebay_title(item_id))   # C列(日本語)+eBayタイトル(英語)から賞
        pp = _match_prize(prize, sd["prizes"])
        if not pp:
            pp = _manual_prize(sd["prizes"])
        if not pp:
            print(f"     賞={prize or '不明'} → 確定できず skip"); continue
        # cost = expand で選んだ時の主supply実価格(保存済)。無い時のみ fetch fallback。
        cost = d.get("cost") or (gen.fetch_mercari_price(supply) if supply else 0)
        if not cost:
            print(f"     ⚠️ 新supply価格 不明(保存無 + fetch不可: {supply[:40]}) → DEFAULT_PRICE", flush=True)
        ebay_row, new_title, price, note = _build_refreshed_row(
            gen, base_desc, sd.get("series_name", ""), sd.get("release_year", ""),
            sd.get("price_jpy", ""), sd.get("main_image", ""), kuji_url, supply, pp, cost)
        if not ebay_row:
            print(f"     ⏭ {note}"); continue
        old_title = _ebay_title(item_id)
        planned.append({"item_id": item_id, "sku": ebay_row.get("CustomLabel", ""),
                        "row": ebay_row, "old_title": old_title, "new_title": new_title,
                        "price": price})
        print(f"     ✅ 賞={pp.get('prize')} cost¥{cost or '?'} → ${price}")

    if not planned:
        print("\n刷新対象なし"); return
    os.makedirs(os.path.dirname(REFRESH_FILE), exist_ok=True)
    with open(REFRESH_FILE, "w", encoding="utf-8") as f:
        json.dump({"items": planned}, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*70}\n🧪 刷新プレビュー {len(planned)}件(eBay/CSV 未書込):")
    for p in planned:
        act, st, q = plan_action(p["item_id"])
        tag = {"revise": "Revise→同ID", "add": "Add→新ID(出し直し)", "skip": f"skip({st})"}[act]
        print(f"\n  itemID={p['item_id']}  ${p['price']}  [{st} qty{q} → {tag}]")
        print(f"    旧: {p['old_title']}")
        print(f"    新: {p['new_title']}")
    print(f"\n💾 保存: {REFRESH_FILE}")
    print("  → 確認OKなら本番反映: python ichibankuji_restock.py refresh write")
    print("     (Active=Revise同ID / Completed=Add新ID で振分 → 出品くんで FileExchange 入稿)")


def plan_action(item_id):
    """現状 eBay 状態から刷新の適用方法を決める。戻り: 'revise'(同ID) / 'add'(新ID) / 'skip'。

    itemID を変えずに済むなら Revise(同ID=view/watcher 温存)、終了済で無理なら Add(新ID=出し直し)。
    監視くん/原因は無関係 — 「今 eBay でどうなってるか」だけで決まる(2026-06-24 ユーザー方針)。
    """
    if not item_id:
        return ("skip", "?", -1)
    st, q = _ebay_status(item_id)
    if st == "Active":
        return ("revise", st, q)      # Revise 可 = 同ID で内容刷新 + qty=1
    if st == "Completed":
        return ("add", st, q)         # 終了済 = Revise不可 → 新規Addで出し直し(新ID)
    return ("skip", st, q)            # 状態不明 = fail-closed(推測でいじらない)


def _write_addform_csv(rows, path):
    """ebay_row dict list → Add形式CSV(generator と同形式 utf-8-sig)+ Free Shipping 後処理。"""
    import csv as _csv
    keys = list(rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    try:
        from freeshipping_postprocess import transform_csv_to_freeshipping
        transform_csv_to_freeshipping(path)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ Free Shipping 後処理 失敗(非致命): {type(e).__name__}: {e}")


def refresh_write():
    """REFRESH_FILE(刷新確定) → 現状eBay状態で振分: Active→Revise CSV(同ID) / Completed→Add CSV(新ID)。"""
    if not os.path.exists(REFRESH_FILE):
        print(f"刷新確定なし: {REFRESH_FILE}(先に refresh)"); return
    planned = (json.load(open(REFRESH_FILE, encoding="utf-8")).get("items")) or []
    if not planned:
        print("刷新確定なし"); return
    import ichibankuji_restock_revise as rv
    gen, gd = _gen()
    out_dir = os.path.dirname(gen.OUTPUT_CSV)

    # 現状 eBay 状態で Revise(同ID) / Add(新ID) に振り分け
    revise_planned, add_planned, skipped_status = [], [], []
    for p in planned:
        act, st, q = plan_action(p.get("item_id", ""))
        print(f"  itemID={p.get('item_id')}: {st} qty{q} → {act}")
        (revise_planned if act == "revise" else add_planned if act == "add" else skipped_status).append(p)
    if skipped_status:
        print(f"  ⚠️ 状態不明で除外 {len(skipped_status)}件(fail-closed): {[p.get('item_id') for p in skipped_status]}")

    outputs = []
    # Active → Revise CSV(同ID・内容刷新 + qty=1 + PicURL/ScheduleTime削除)
    if revise_planned:
        add_tmp = os.path.join(out_dir, "ichibankuji_restock_add_tmp.csv")
        revise_csv = os.path.join(out_dir, "ichibankuji_restock_revise.csv")
        _write_addform_csv([p["row"] for p in revise_planned], add_tmp)
        sku_to_itemid = {p["sku"]: p["item_id"] for p in revise_planned if p.get("sku")}
        n, sk = rv.convert_file(add_tmp, revise_csv, sku_to_itemid)
        try:
            os.remove(add_tmp)
        except Exception:
            pass
        outputs.append((revise_csv, n, "Revise(同ID=view/watcher温存)"))
        if sk:
            print(f"  ⚠️ Revise: itemID未解決で除外 {len(sk)}件: {[s[0] for s in sk]}")
    # Completed → Add CSV(新ID・新規出し直し。PicURL/ScheduleTime はそのまま=新規出品)
    if add_planned:
        add_csv = os.path.join(out_dir, "ichibankuji_restock_add.csv")
        _write_addform_csv([p["row"] for p in add_planned], add_csv)
        outputs.append((add_csv, len(add_planned), "Add(新ID=終了済の出し直し)"))

    if not outputs:
        print("出力対象なし(全件 状態不明)"); return
    print()
    for path, cnt, kind in outputs:
        print(f"✅ {kind} CSV 出力: {path}  ({cnt}件)")
    print("  → 出品くんで FileExchange 入稿(Revise=旧ID内容刷新 / Add=新ID出し直し)")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "identify":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        pass_identify(n, cand_n=10)
    elif mode == "expand":
        pass_expand(cand_n=10, dry=("--dry" in sys.argv))
    elif mode == "write":
        pass_write()
    elif mode == "refresh":
        if len(sys.argv) > 2 and sys.argv[2] == "write":
            refresh_write()
        else:
            pass_refresh()
    elif mode == "prefetch":
        # 夜間: 候補だけ貯める(目視UIを開かない・スプシに書かない)。昼の identify が即表示になる。
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        pass_prefetch(n, cand_n=10)
    elif mode == "supply":
        # ボタン①: 識別+supply確定 を1発(identify→expand)。出品くん用 combined。
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        pass_identify(n, cand_n=10)
        if os.path.exists(PICKS_FILE) and json.load(open(PICKS_FILE, encoding="utf-8")):
            pass_expand(cand_n=10, dry=False)
        else:
            print("識別0件 → expand skip")
    elif mode == "refresh-csv":
        # ボタン②: 刷新→CSV を1発(refresh→refresh write)。プレビューはログに出るが確認は出力CSVで。
        pass_refresh()
        if os.path.exists(REFRESH_FILE) and (json.load(open(REFRESH_FILE, encoding="utf-8")).get("items")):
            refresh_write()
        else:
            print("刷新対象なし → CSV出力 skip")
    else:
        print("使い方:\n  python ichibankuji_restock.py supply [件数]      # ★ボタン①: 識別+supply確定(identify→expand)\n"
              "  python ichibankuji_restock.py refresh-csv         # ★ボタン②: 刷新→Revise/Add CSV(refresh→write)\n"
              "  --- 個別(手動/デバッグ) ---\n"
              "  identify [件数] / expand [--dry] / write / refresh / refresh write")


if __name__ == "__main__":
    main()
