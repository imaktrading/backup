import sys, io
sys.stdout=io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0,'.')
from scrapers import snkrdunk_official as SO, snkrdunk_op_catalog as OP
session=OP.create_session()
driver=SO.create_driver(headless=True)
try:
    ids=OP.enumerate_candidate_model_ids(driver, max_pages=3)  # 既定 keywords/brandIds/isSaleOnly
    print(f"candidates(3頁)={len(ids)}")
    op=0; non=0
    for mid in ids[:25]:
        d=OP.fetch_model_detail(session,mid); pn=(d or {}).get("productNumber","") or ""
        if OP.is_one_piece_pn(pn): op+=1
        else: non+=1; print("  非OneP:",pn)
    print(f"純度サンプル25中: One Piece={op} 非={non}")
finally:
    driver.quit()
