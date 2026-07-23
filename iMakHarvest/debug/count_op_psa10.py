import requests, json, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
   "Accept":"application/json","Accept-Language":"ja-JP,ja;q=0.9"}
S=requests.Session(); S.headers.update(H)
# Phase1: enumerate One Piece singles models
models=[]; 
for page in range(1,60):
    r=S.get("https://snkrdunk.com/v1/apparels",params={"brandId":"onepiece","searchCategoryIds":"6/33","page":page,"perPage":60},timeout=15)
    if r.status_code!=200: print("enum stop",r.status_code); break
    ap=r.json().get("apparels",[])
    if not ap: break
    for a in ap: models.append({"id":a.get("id"),"pn":a.get("productNumber"),"name":(a.get("name") or "")[:40]})
    print(f"enum page{page}: +{len(ap)} total={len(models)}",flush=True)
    if len(ap)<60: break
    time.sleep(0.3)
print(f"\n[Phase1] One Piece singles models = {len(models)}",flush=True)
Path(ROOT/"debug"/"op_models_http.json").write_text(json.dumps(models,ensure_ascii=False,indent=2),encoding="utf-8")
