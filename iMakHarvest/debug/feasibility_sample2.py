import sys, re, time, random, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from scrapers import amazon_search_http as H
from urllib.parse import quote
def price_of(html):
    m=re.search(r'"a-price-whole"[^>]*>([\d,]+)',html); return int(m.group(1).replace(',','')) if m else None
cats={
  "Shimanoリール":"シマノ スピニングリール",
  "Daiwaリール":  "ダイワ リール",
  "BOSSペダル":   "BOSS エフェクター ギター",
  "ねんどろいど":  "ねんどろいど フィギュア",
  "SonyXM":       "ソニー ヘッドホン WH-1000XM",
}
session=H.create_session(); SAMPLE=12; out={}
for name,q in cats.items():
    html,cap=H.fetch_search_page(session,f"https://www.amazon.co.jp/s?k={quote(q)}")
    if cap or not html: out[name]={"error":"fail"}; print(name,"FAIL"); continue
    asins=H.parse_search_asins(html)[:SAMPLE]; direct=0; prices=[]; checked=0
    for a in asins:
        t,c=H.fetch_detail_page(session,a)
        if c: print(name,"captcha"); break
        if not t: continue
        checked+=1
        if H.SELLER_AMAZON_PRIMARY_MARKER in t: direct+=1
        p=price_of(t);
        if p: prices.append(p)
        time.sleep(random.uniform(1.5,2.5))
    out[name]={"q":q,"checked":checked,"direct":direct,
               "direct_pct":round(100*direct/checked) if checked else 0,
               "price_min":min(prices) if prices else None,"price_max":max(prices) if prices else None}
    print(f"{name}: checked={checked} direct={direct} ({out[name]['direct_pct']}%) price={out[name]['price_min']}-{out[name]['price_max']}")
    time.sleep(random.uniform(2,3))
Path(ROOT/"debug"/"feasibility_sample2.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print("DONE")
