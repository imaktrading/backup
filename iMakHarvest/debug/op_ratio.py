import requests, json, re, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36","Accept":"application/json"}
S=requests.Session(); S.headers.update(H)
ids=json.load(open(ROOT/"debug"/"op_model_count.json",encoding="utf-8"))["ids"]
OP=re.compile(r"^(OP|ST|EB)\d{2}-\d{3}$|^P-\d{3}$",re.I)
import random
samp=ids[:50]
op=0; pk=0; other=0; op_with_psa10=0
for mid in samp:
    try:
        d=S.get(f"https://snkrdunk.com/v1/apparels/{mid}",timeout=12).json()
        pn=(d.get("productNumber") or "")
        if OP.match(pn):
            op+=1
            u=S.get(f"https://snkrdunk.com/v1/apparels/{mid}/used",params={"page":1,"perPage":50},timeout=12).json().get("apparelUsedItems",[])
            p10=[x for x in u if (x.get("displayShortConditionTitle") or"")=="PSA10" and x.get("status")==0 and (x.get("price") or 0)<100000]
            if p10: op_with_psa10+=1
        elif pn.startswith("pkmn"): pk+=1
        else: other+=1
    except Exception as e: other+=1
    time.sleep(0.2)
print(f"sample={len(samp)} ワンピ={op} Pokemon={pk} other={other}")
print(f"ワンピのうちPSA10<10万あり={op_with_psa10}/{op}")
