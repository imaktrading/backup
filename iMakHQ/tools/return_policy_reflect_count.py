# 返品ポリシー (UK 266277100017 / AU 265455553017 / CA 266277269017) の出品への反映を数える。GetSellerList 約20回。2026-10-10 ADV
# python iMakHQ/tools/return_policy_reflect_count.py
import sys, re, time, datetime, collections
sys.path[:0] = [r'C:\dev\iMak\iMakHQ\tools', r'C:\dev\iMak\iMakeBayAPI']
import fix_de_speedpak_shipping as fx
import mirror_promo_bestoffer as M
fx.refresh(); tr = M.TradingToken(fx)
now = datetime.datetime.utcnow()
lo = now.strftime("%Y-%m-%dT%H:%M:%S"); hi = (now + datetime.timedelta(days=119)).strftime("%Y-%m-%dT%H:%M:%S")
def page(p, detail):
    inner = (detail + "<EndTimeFrom>%sZ</EndTimeFrom><EndTimeTo>%sZ</EndTimeTo>"
             "<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>%d</PageNumber></Pagination>" % (lo, hi, p))
    for _ in range(3):
        x = fx.post("GetSellerList", inner, tr.get(), site="0") or ""
        if "<ItemArray>" in x: return x
        time.sleep(2)
    return ""
DET = "<DetailLevel>ReturnAll</DetailLevel>"
first = page(1, DET)
pages = int(re.search(r"<TotalNumberOfPages>(\d+)", first).group(1))
c = collections.Counter(); n = 0; miss = 0
WATCH = {"266277100017": "UK", "265455553017": "AU", "266277269017": "CA"}
for p in range(1, pages + 1):
    x = first if p == 1 else page(p, DET)
    if not x: miss += 1; continue
    for it in re.findall(r"<Item>(.*?)</Item>", x, re.S):
        n += 1
        site = (re.search(r"<Site>(.*?)</Site>", it) or [None, ""])[1]
        pid = (re.search(r"<ReturnProfileID>(\d+)</ReturnProfileID>", it) or [None, ""])[1]
        acc = (re.search(r"<ReturnsAcceptedOption>(.*?)</ReturnsAcceptedOption>", it) or [None, ""])[1]
        payer = (re.search(r"<ShippingCostPaidByOption>(.*?)</ShippingCostPaidByOption>", it) or [None, ""])[1]
        within = (re.search(r"<ReturnsWithinOption>(.*?)</ReturnsWithinOption>", it) or [None, ""])[1]
        if site in ("UK", "Australia", "Canada"):
            c[(site, WATCH.get(pid, pid or "?"), acc, within, payer)] += 1
print("全", n, "件 / 取れないページ", miss)
for k, v in sorted(c.items(), key=lambda kv: -kv[1]): print(v, k)
