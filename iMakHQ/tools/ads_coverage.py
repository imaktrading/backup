"""広告 (Promoted Listings) に入っていない出品を出す.

なぜ必要か (2026-08-14):
    Seller Hub の画面では「キャンペーンごとの商品数」しか見えず、**どの出品が
    どこにも入っていないか**が分からない。US の General 型が7本あり、合計は
    1,700件ほど。出品総数はそれより多いので、差分は広告が一切当たっていない。
    画面で 1件ずつ照合するのは不可能なので API で突合する。

読むだけ。書込・停止・作成は一切しない。

前提:
    - `ebay_oauth_token_sell.json` に `sell.marketing.readonly` が入っていること
      (2026-08-14 に scope 追加 + 再同意済)。失効時は
      `cd iMakeBayAPI && python oauth_sell_setup.py refresh`
    - live 出品一覧は `itemid_writeback_audit` のキャッシュを**使い回す**。
      GetMyeBaySelling は日次上限があり、調べるだけの道具で使い切ると
      **監視くんの巡回を巻き添えにする** (2026-08-08 に実際に起こした)。

使い方:
    python ads_coverage.py                 # 要約だけ
    python ads_coverage.py --list          # 広告に入っていない itemID も出す
    python ads_coverage.py --marketplace EBAY_GB
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                "iMakeBayAPI"))
import requests  # noqa: E402

TOKEN_FILE = Path(r"C:\dev\iMak\iMakeBayAPI\ebay_oauth_token_sell.json")
LIVE_CACHE = Path(r"C:\dev\iMak_data\hq\itemid_audit_live_cache.json")
API = "https://api.ebay.com/sell/marketing/v1"
PAGE = 500


def _token() -> str:
    tok = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    return tok["access_token"]


def _get(path: str, marketplace: str, params: dict | None = None) -> dict:
    r = requests.get(
        f"{API}/{path}",
        headers={"Authorization": f"Bearer {_token()}",
                 "X-EBAY-C-MARKETPLACE-ID": marketplace},
        params=params or {},
        timeout=60,
    )
    if r.status_code == 401:
        raise SystemExit("token が失効しています → "
                         "cd iMakeBayAPI && python oauth_sell_setup.py refresh")
    if r.status_code >= 400:
        raise SystemExit(f"HTTP {r.status_code}: {r.text[:400]}")
    return r.json()


def campaigns(marketplace: str) -> list[dict]:
    """RUNNING のキャンペーンを全部返す (ページング込み)."""
    out, offset = [], 0
    while True:
        d = _get("ad_campaign", marketplace,
                 {"limit": 100, "offset": offset, "campaign_status": "RUNNING"})
        got = d.get("campaigns") or []
        out += [c for c in got if c.get("marketplaceId") == marketplace]
        offset += len(got)
        if len(got) < 100 or offset >= int(d.get("total") or 0):
            break
    return out


def ads_of(campaign_id: str, marketplace: str) -> set[str]:
    """キャンペーンに入っている listingId 集合 (ページング込み)."""
    ids: set[str] = set()
    offset = 0
    while True:
        d = _get(f"ad_campaign/{campaign_id}/ad", marketplace,
                 {"limit": PAGE, "offset": offset})
        got = d.get("ads") or []
        for a in got:
            lid = a.get("listingId")
            if lid:
                ids.add(str(lid))
        offset += len(got)
        total = int(d.get("total") or 0)
        if len(got) < PAGE or offset >= total:
            break
    return ids


def live_listings() -> tuple[dict, float]:
    """出品中の itemID → 情報。**キャッシュのみ**。無ければ落とす (API を焼かない)."""
    if not LIVE_CACHE.exists():
        raise SystemExit(
            f"live キャッシュが無い: {LIVE_CACHE}\n"
            "  先に `python iMakHQ/tools/itemid_writeback_audit.py` を1回走らせること "
            "(GetMyeBaySelling の上限を焼かないため、ここでは取りに行かない)")
    age_h = (time.time() - LIVE_CACHE.stat().st_mtime) / 3600
    return json.loads(LIVE_CACHE.read_text(encoding="utf-8")), age_h


def coverage(live_ids: set[str], promoted: set[str]) -> dict:
    """純関数。live と 広告入り の差分を出す."""
    covered = live_ids & promoted
    return {
        "live": len(live_ids),
        "promoted_total": len(promoted),
        "covered": len(covered),
        "uncovered": sorted(live_ids - promoted),
        # 広告には居るが live に居ない = 終了済 listing が残っている (掃除候補)
        "stale_in_campaign": sorted(promoted - live_ids),
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--marketplace", default="EBAY_US")
    ap.add_argument("--list", action="store_true", help="広告に入っていない itemID を列挙")
    a = ap.parse_args()

    cs = campaigns(a.marketplace)
    print(f"# 広告カバレッジ ({a.marketplace})\n")
    print(f"RUNNING キャンペーン: {len(cs)}本")
    promoted: set[str] = set()
    for c in cs:
        ids = ads_of(c["campaignId"], a.marketplace)
        fs = c.get("fundingStrategy") or {}
        print(f"  - {c['campaignName'][:44]:<44} {len(ids):>5}件  "
              f"{fs.get('bidPercentage', '?')}% / {fs.get('fundingModel', '?')}")
        promoted |= ids

    live, age_h = live_listings()
    print(f"\nlive 出品: {len(live)}件 (キャッシュ {age_h:.0f}時間前)")
    if age_h > 24:
        print("  ⚠️ キャッシュが古い。数字は目安。更新は itemid_writeback_audit を走らせる")

    r = coverage(set(live), promoted)
    pct = r["covered"] / r["live"] * 100 if r["live"] else 0
    print(f"\n広告に入っている : {r['covered']:>6} / {r['live']} 件 ({pct:.0f}%)")
    print(f"入っていない     : {len(r['uncovered']):>6} 件  ← 広告が一切当たっていない")
    print(f"終了済なのに残留 : {len(r['stale_in_campaign']):>6} 件  ← キャンペーン側の掃除候補")

    if a.list:
        print("\n## 広告に入っていない itemID")
        for iid in r["uncovered"]:
            t = (live.get(iid) or {}).get("title", "")
            print(f"  {iid}  {t[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
