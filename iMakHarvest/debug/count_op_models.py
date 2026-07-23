import sys, time, re, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
from scrapers import snkrdunk_official as S

driver=S.create_driver(headless=True)
allids=set(); pages=0; empty_streak=0
try:
    for page in range(1,41):
        url=f"https://snkrdunk.com/search?searchCategoryIds=6/33&brandId=onepiece&page={page}"
        driver.get(url); time.sleep(5)
        for _ in range(3):
            driver.execute_script("window.scrollTo(0,document.body.scrollHeight)"); time.sleep(1.5)
        links=driver.execute_script("return Array.from(document.querySelectorAll('a[href*=\"/apparels/\"]')).map(a=>a.getAttribute('href'))")
        ids=set(re.findall(r"/apparels/(\d+)",";".join(links)))
        new=ids-allids
        allids|=ids; pages=page
        print(f"page{page}: links={len(ids)} new={len(new)} total={len(allids)}",flush=True)
        if not ids or len(new)==0:
            empty_streak+=1
            if empty_streak>=2: break
        else: empty_streak=0
finally:
    driver.quit()
Path(ROOT/"debug"/"op_model_count.json").write_text(json.dumps({"pages":pages,"total_models":len(allids),"ids":sorted(allids)},ensure_ascii=False,indent=2),encoding="utf-8")
print(f"\nTOTAL One Piece singles models: {len(allids)} (pages scanned={pages})")
