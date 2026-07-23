import requests, json
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
   "Accept":"application/json","Accept-Language":"ja-JP,ja;q=0.9"}
import urllib.parse
def raw(u):
    r=requests.get(u,headers=H,timeout=12)
    try: j=r.json(); ap=j.get("apparels"); n=len(ap) if isinstance(ap,list) else j
    except: n=r.text[:80]
    print(f"[{r.status_code}] n={n if isinstance(n,int) else str(n)[:60]}  {u[:90]}")
    return r
# brandId only
raw("https://snkrdunk.com/v1/apparels?brandId=onepiece&page=1")
raw("https://snkrdunk.com/v1/apparels?brandId=onepiece&page=1&perPage=30")
# unencoded slash
raw("https://snkrdunk.com/v1/apparels?brandId=onepiece&searchCategoryIds=6%2F33&page=1&perPage=30")
raw("https://snkrdunk.com/v1/apparels?searchCategoryIds=6/33&page=1&perPage=30")
# maybe needs categoryId not searchCategoryIds
raw("https://snkrdunk.com/v1/apparels?brandId=onepiece&categoryId=6&page=1")
r=raw("https://snkrdunk.com/v1/apparels?brandId=onepiece&page=1&perPage=5")
try:
    ap=r.json().get("apparels",[])
    if ap: print("  sample:",json.dumps({k:ap[0].get(k) for k in ['id','productNumber','name']},ensure_ascii=False))
    print("  resp keys:",list(r.json().keys()))
except Exception as e: print(e)
