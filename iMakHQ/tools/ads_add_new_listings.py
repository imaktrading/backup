#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ads_add_new_listings.py — 入稿した新規出品を広告 (Promoted Listings) に 8% で入れる。

人が入稿のたびに手でやっていた「プロモを8%に」の自動化 (2026-08-18)。

受け皿キャンペーンを 165535464010 にした理由 (2026-08-18 実測):
    US の RUNNING キャンペーン6本のうち、**8.0% で完全に揃っているのはここだけ**
    (106件すべて 8.0%)。しかも 8/2 開始で一番新しい = 今の受け皿。
    古いキャンペーンは率が混ざっている (03/21 は 7/8/10/5% が同居、05/13 は 5% 主体)。

安全側の作り:
    - 既定は dry-run。`--write` を付けた時だけ eBay に書く
    - **既に広告に入っている出品は触らない** (率を勝手に上書きしない)
    - itemID がまだシートに無い行は「書き戻し待ち」として報告するだけ (推測で ID を作らない)

使い方:
    python ads_add_new_listings.py <入稿CSV>            # 何を追加するか出すだけ
    python ads_add_new_listings.py <入稿CSV> --write    # 実際に追加
    python ads_add_new_listings.py --itemids 1234,5678  # CSV でなく直接指定
"""
import argparse
import base64
import csv
import json
import os
import re
import sys

import requests

# ★2026-09-01: cp932 コンソール (Windows既定) で絵文字 print が UnicodeEncodeError で
#   クラッシュしていた。しかもクラッシュ位置が本体の eBay 書込 (create_ads) より**前**の
#   プレビュー表示だったため、「対象11件→追加11」と出ていたのに実際は1件も書かれて
#   いなかった (この行は計画件数の表示で、完了の証拠ではない)。他スクリプト
#   (cull_end.py 等) と同じ reconfigure で防ぐ。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API = "https://api.ebay.com/sell/marketing/v1"
MARKETPLACE = "EBAY_US"
CAMPAIGN_ID = "165535464010"     # 8.0% で揃っている受け皿 (2026-08-18 実測で選定)
BID = "8.0"
# ★2026-08-21: 鍵とトークンの場所は credentials.py が決める (共有領域が本物)。
#   2か所に置いたまま片方だけ更新されると腐るため (カタログ依頼)。
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
try:
    from credentials import keys_path as _keys_path, token_path as _token_path
    TOKEN_FILE = _token_path("sell")
    KEYS_FILE = _keys_path()
except Exception:                                             # noqa: BLE001
    TOKEN_FILE = r"C:\dev\iMak\iMakeBayAPI\ebay_oauth_token_sell.json"
    KEYS_FILE = r"C:\dev\iMak\iMakeBayAPI\ebay keys.txt"


# ── 純関数 (test 可) ────────────────────────────────────────────────
def labels_from_csv(path):
    """入稿CSV → CustomLabel の list。"""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [(r.get("CustomLabel") or "").strip() for r in rows if (r.get("CustomLabel") or "").strip()]


def itemid_index(rows2d, itemid_col=1, cert_col=8, url_col=0):
    """シート → {cert or SKU: itemID} (純関数)。空の itemID は入れない。"""
    idx = {}
    for r in rows2d[1:]:
        g = lambda i: (r[i].strip() if len(r) > i else "")
        iid = g(itemid_col)
        if not iid or not iid.isdigit():
            continue
        if g(cert_col):
            idx.setdefault(g(cert_col), iid)
        m = re.search(r"/(?:item/|shops/product/)(\w+)", g(url_col))
        if m:
            idx.setdefault(m.group(1), iid)
    return idx


def resolve_itemids(labels, idx):
    """CustomLabel → itemID を引く (純関数)。→ ([(label,itemid)], [引けなかった label])。"""
    found, missing = [], []
    for lb in labels:
        m = re.match(r"^PSA10-(\d+)$", lb)
        iid = idx.get(m.group(1)) if m else idx.get(lb)
        (found.append((lb, iid)) if iid else missing.append(lb))
    return found, missing


def plan(found, existing_by_listing):
    """(pure) → (追加する [(label,itemid)], 既に広告に入っている [(label,itemid,率)])。"""
    to_add, already = [], []
    for lb, iid in found:
        rate = existing_by_listing.get(iid)
        (already.append((lb, iid, rate)) if rate else to_add.append((lb, iid)))
    return to_add, already


# ── eBay API ────────────────────────────────────────────────────────
def _token():
    d = json.load(open(TOKEN_FILE, encoding="utf-8"))
    keys = {}
    for line in open(KEYS_FILE, encoding="utf-8", errors="replace"):
        if "=" in line:
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip()
    b = base64.b64encode(f"{keys['AppID']}:{keys['AppSecret']}".encode()).decode()
    r = requests.post("https://api.ebay.com/identity/v1/oauth2/token",
                      headers={"Authorization": f"Basic {b}",
                               "Content-Type": "application/x-www-form-urlencoded"},
                      data={"grant_type": "refresh_token", "refresh_token": d["refresh_token"]},
                      timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def _headers(tok):
    return {"Authorization": f"Bearer {tok}", "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
            "Content-Type": "application/json"}


def fetch_existing_ads(tok):
    """US の RUNNING キャンペーン全部の ad を {listingId: 率} に畳む。

    1つのキャンペーンだけ見ると、別キャンペーンに入っている出品を「未広告」と誤判定して
    二重登録を試み、eBay 側で弾かれる。全体を見てから決める。
    """
    H = _headers(tok)
    camps = requests.get(f"{API}/ad_campaign", headers=H,
                         params={"campaign_status": "RUNNING", "limit": 200},
                         timeout=60).json().get("campaigns", [])
    out = {}
    for c in camps:
        if c.get("marketplaceId") != MARKETPLACE:
            continue
        for page in range(20):
            r = requests.get(f"{API}/ad_campaign/{c['campaignId']}/ad", headers=H,
                             params={"limit": 500, "offset": page * 500}, timeout=60)
            if r.status_code != 200:
                break
            ads = r.json().get("ads", [])
            for a in ads:
                if a.get("listingId"):
                    out[str(a["listingId"])] = str(a.get("bidPercentage"))
            if len(ads) < 500:
                break
    return out


def create_ads(tok, pairs):
    """listingId を 8% で受け皿キャンペーンに追加。→ [(itemid, 結果)]。"""
    body = {"requests": [{"listingId": iid, "bidPercentage": BID} for _lb, iid in pairs]}
    r = requests.post(f"{API}/ad_campaign/{CAMPAIGN_ID}/bulk_create_ads_by_listing_id",
                      headers=_headers(tok), data=json.dumps(body), timeout=120)
    if r.status_code not in (200, 201, 207):
        return [(iid, f"HTTP {r.status_code}: {r.text[:120]}") for _lb, iid in pairs]
    out = []
    for res in r.json().get("responses", []):
        iid = str(res.get("listingId"))
        if res.get("statusCode") in (200, 201):
            out.append((iid, "OK"))
        else:
            errs = "; ".join(e.get("message", "") for e in (res.get("errors") or []))
            out.append((iid, f"NG {res.get('statusCode')}: {errs[:100]}"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", help="入稿CSV")
    ap.add_argument("--itemids", default="", help="itemID をカンマ区切りで直接指定")
    ap.add_argument("--write", action="store_true", help="実際に eBay へ追加する")
    a = ap.parse_args()

    if a.itemids:
        found = [(i.strip(), i.strip()) for i in a.itemids.split(",") if i.strip()]
        missing = []
    elif a.csv:
        import sheet_io
        labels = labels_from_csv(a.csv)
        found, missing = resolve_itemids(labels, itemid_index(sheet_io._product_ws().get_all_values()))
    else:
        # ボタンから引数無しで押せるように、最新の入稿CSVを既定にする
        import glob
        cands = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              "..", "csv_output", "*_upload_*.csv")),
                       key=os.path.getmtime)
        if not cands:
            print("入稿CSV が見つかりません。csv を指定してください")
            return 2
        import sheet_io
        print(f"(最新の入稿CSV を対象にします: {os.path.basename(cands[-1])})")
        labels = labels_from_csv(cands[-1])
        found, missing = resolve_itemids(labels, itemid_index(sheet_io._product_ws().get_all_values()))

    tok = _token()
    existing = fetch_existing_ads(tok)
    to_add, already = plan(found, existing)

    print(f"=== 広告 {BID}% 追加 [{'実書込' if a.write else 'dry-run'}] キャンペーン {CAMPAIGN_ID} ===")
    print(f"  対象 {len(found) + len(missing)}件 → 追加 {len(to_add)} / 既に広告あり {len(already)} / "
          f"itemID 未取得 {len(missing)}")
    for lb, iid in to_add:
        print(f"  ➕ {lb} → {iid}")
    for lb, iid, rate in already:
        mark = "" if rate == BID else f"  ← {rate}% のまま (触らない)"
        print(f"  ✓ {lb} → {iid} 既に {rate}%{mark}")
    for lb in missing:
        print(f"  ⏳ {lb} itemID がまだシートに無い (先に『入稿後: itemID をスプシに書込』を押す)")

    if a.write and to_add:
        for iid, res in create_ads(tok, to_add):
            print(f"  {'✅' if res == 'OK' else '❌'} {iid}: {res}")
    elif not to_add:
        print("  追加するものはありません")
    return 0


if __name__ == "__main__":
    sys.exit(main())
