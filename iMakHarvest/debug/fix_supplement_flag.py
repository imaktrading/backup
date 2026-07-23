import sys, time
sys.path.insert(0,'.')
from scrapers import snkrdunk_official as SO
from sheet_writer import COL_TITLE, HIGH_SHEET_ID, LISTINGS_GID
from sheet_writer_mercari_seller import open_seller_staging_sheet, _col_to_letter
from sheet_writer_snkrdunk_aux import get_listings_worksheet, open_sheet_by_id

def retry(fn, n=5):
    for i in range(n):
        try: return fn()
        except Exception as e:
            print(f"  retry {i+1}/{n}: {e!r}"[:120]); time.sleep(3)
    raise RuntimeError("retry exhausted")

# HIGH card_ids
def load_high():
    sh=open_sheet_by_id(HIGH_SHEET_ID); ws=get_listings_worksheet(sh,LISTINGS_GID)
    ids=set()
    for row in ws.get_all_values()[1:]:
        t=row[COL_TITLE-1] if len(row)>=COL_TITLE else ""
        cid=SO.extract_tcg_card_id(t)
        if cid: ids.add(cid.upper())
    return ids
high=retry(load_high)
print("HIGH card_ids:",len(high))

ws=retry(lambda: open_seller_staging_sheet().worksheet('snkrdunk_op_psa10'))
v=retry(ws.get_all_values)
C_FLG=17; C_KEY=35
updates=[]  # (row_idx, value)
sup=0
for i,r in enumerate(v[1:],start=2):
    key=(r[C_KEY-1].strip().upper() if len(r)>=C_KEY else "")
    if not key: continue
    is_sup = key in high
    cur=(r[C_FLG-1].strip() if len(r)>=C_FLG else "")
    want="補" if is_sup else ""
    if cur!=want:
        updates.append((i,want))
    if is_sup: sup+=1
print(f"補仕入該当={sup} / 更新行={len(updates)}")
for ri,val in updates:
    retry(lambda ri=ri,val=val: ws.update_cell(ri,C_FLG,val)); time.sleep(0.4)
print("done. updated",len(updates))
