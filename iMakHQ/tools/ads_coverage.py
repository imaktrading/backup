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


def ads_of(campaign_id: str, marketplace: str) -> dict[str, str]:
    """キャンペーンの {listingId: 広告率} (ページング込み)。

    ★2026-08-14: 率は **広告1件ごと** に付いている。キャンペーンの
      `fundingStrategy.bidPercentage` は「新しく追加した時の既定値」でしかなく、
      **実際に課金される率ではない**。既定値だけ見て「9%が1,433件 / 5%が448件」と
      報告したが、実測は 8% が 1,441件で、残りが 2〜10% に9種類バラけていた。
      キャンペーンの既定値を書き換えても **既存の広告の率は変わらない**。
    """
    out: dict[str, str] = {}
    offset = 0
    while True:
        d = _get(f"ad_campaign/{campaign_id}/ad", marketplace,
                 {"limit": PAGE, "offset": offset})
        got = d.get("ads") or []
        for a in got:
            lid = a.get("listingId")
            if lid:
                out[str(lid)] = str(a.get("bidPercentage"))
        offset += len(got)
        total = int(d.get("total") or 0)
        if len(got) < PAGE or offset >= total:
            break
    return out


def live_listings() -> tuple[dict, float]:
    """出品中の itemID → 情報。**キャッシュのみ**。無ければ落とす (API を焼かない)."""
    if not LIVE_CACHE.exists():
        raise SystemExit(
            f"live キャッシュが無い: {LIVE_CACHE}\n"
            "  先に `python iMakHQ/tools/itemid_writeback_audit.py` を1回走らせること "
            "(GetMyeBaySelling の上限を焼かないため、ここでは取りに行かない)")
    age_h = (time.time() - LIVE_CACHE.stat().st_mtime) / 3600
    return json.loads(LIVE_CACHE.read_text(encoding="utf-8")), age_h


# ★2026-08-14: **サイトを揃えずに突合しない**。
#   初回に US のキャンペーンだけ集めて live 全件 (US + eBaymag ミラー GB/AU/CA) と
#   引き算し、「2,500件が未広告」と誤報告した。実際はミラー分がそれぞれ自分のサイトの
#   キャンペーンに入っており、未広告は 11件だった。母数と分子のサイトを必ず合わせる。
CCY_TO_MARKETPLACE = {
    "USD": "EBAY_US", "GBP": "EBAY_GB", "AUD": "EBAY_AU",
    "CAD": "EBAY_CA", "EUR": "EBAY_DE",
}
MARKETPLACES = ["EBAY_US", "EBAY_GB", "EBAY_AU", "EBAY_CA", "EBAY_DE"]


def split_live_by_marketplace(live: dict) -> dict[str, set[str]]:
    """live 出品を通貨からサイト別に分ける (純関数)。未知通貨は '?' に落とす."""
    out: dict[str, set[str]] = {}
    for iid, v in live.items():
        mkt = CCY_TO_MARKETPLACE.get((v or {}).get("cur") or "", "?")
        out.setdefault(mkt, set()).add(str(iid))
    return out


def coverage(live_ids: set[str], promoted: set[str]) -> dict:
    """純関数。**同じサイトの** live と 広告入り の差分を出す."""
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
    ap.add_argument("--marketplace", default=None,
                    help="1サイトだけ見る (既定は US + ミラー全部)")
    ap.add_argument("--list", action="store_true", help="広告に入っていない itemID を列挙")
    a = ap.parse_args()

    live, age_h = live_listings()
    by_mkt = split_live_by_marketplace(live)
    targets = [a.marketplace] if a.marketplace else MARKETPLACES

    print(f"# 広告カバレッジ  (live {len(live)}件 / キャッシュ {age_h:.0f}時間前)\n")
    if age_h > 24:
        print("⚠️ キャッシュが古い。数字は目安。更新は itemid_writeback_audit を走らせる\n")

    total_live = total_cov = 0
    uncovered_all: list[str] = []
    for mkt in targets:
        cs = campaigns(mkt)
        rate_of: dict[str, str] = {}
        for c in cs:
            rate_of.update(ads_of(c["campaignId"], mkt))
        promoted = set(rate_of)
        mine = by_mkt.get(mkt, set())
        r = coverage(mine, promoted)
        pct = r["covered"] / r["live"] * 100 if r["live"] else 0
        # ★率は広告1件ごと。キャンペーンの既定値ではなく、実際に課金される値を数える
        rates: dict[str, int] = {}
        for lid in mine & promoted:
            rates[rate_of[lid]] = rates.get(rate_of[lid], 0) + 1
        rate_txt = " / ".join(f"{k}%={v}件" for k, v in
                              sorted(rates.items(), key=lambda kv: -kv[1]))
        print(f"## {mkt}   キャンペーン {len(cs)}本")
        print(f"   広告率(生きてる分): {rate_txt}")
        if len(rates) > 1:
            top = max(rates, key=lambda k: rates[k])
            print(f"   ⚠️ 率が {len(rates)}種類に散っています "
                  f"({top}% 以外が {sum(rates.values()) - rates[top]}件)")
        print(f"   live {r['live']:>5} / 広告に入っている {r['covered']:>5} ({pct:.0f}%) / "
              f"入っていない {len(r['uncovered']):>4} / 終了済が残留 "
              f"{len(r['stale_in_campaign']):>4}")
        total_live += r["live"]
        total_cov += r["covered"]
        uncovered_all += r["uncovered"]
        if a.list and r["uncovered"]:
            for iid in r["uncovered"]:
                print(f"     {iid}  {(live.get(iid) or {}).get('title', '')[:66]}")

    unknown = by_mkt.get("?", set())
    print(f"\n合計: live {total_live} / 広告に入っている {total_cov} / "
          f"入っていない {len(uncovered_all)}")
    if unknown:
        print(f"⚠️ 通貨からサイトを判定できない出品が {len(unknown)}件 "
              f"(集計から漏れている。CCY_TO_MARKETPLACE に足すこと)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
