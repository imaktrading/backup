import sys, json, glob, os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scrapers.amazon_search_http import is_ladies_only

DUMP_DIR = r"C:\dev\iMak_data\catalog\_amazon_jp_dumps"
files = sorted(glob.glob(os.path.join(DUMP_DIR, "amazon_gshock_*.json")))
ladies = {}  # asin -> {key,title,files}
def title_of(it): return it.get("title") or it.get("name") or ""
def asin_of(it):
    a = it.get("asin")
    if a: return a
    url = it.get("url","")
    import re; m=re.search(r"/dp/([A-Z0-9]{10})", url); return m.group(1) if m else None
for f in files:
    items = json.load(open(f,encoding="utf-8"))
    if isinstance(items, dict): items = items.get("items", items.get("data", []))
    for it in items:
        if not isinstance(it, dict): continue
        t = title_of(it)
        if is_ladies_only(t):
            a = asin_of(it)
            if not a: continue
            e = ladies.setdefault(a, {"key": it.get("model_number") or it.get("product_id_estimated") or "", "title": t[:60], "files": []})
            fn = os.path.basename(f).replace("amazon_gshock_","").replace(".json","")
            if fn not in e["files"]: e["files"].append(fn)
print("ladies ASINs in dumps:", len(ladies))
Path(ROOT/"debug"/"dump_ladies_asins.json").write_text(json.dumps(ladies,ensure_ascii=False,indent=2),encoding="utf-8")
for a,e in list(ladies.items())[:5]: print(" ",a,e["key"],e["files"])
