"""発送除外国を **全 fulfillment policy に一括追加**する (2026-07-30).

なぜ:
    除外は listing ではなく **ポリシーごと**に入っている (US本体は 87 ポリシー全部に同一セット)。
    UI で1つずつ直すのは非現実的で、抜けると「除外したつもりで発送可のまま」になる。
    それは注文が来てから履行不能 → キャンセル → Defect という、無在庫で最も避けたい失敗。

安全側の作り:
    - 実行前に **必ず現状をバックアップ** (戻せない変更をしない)
    - 追加のみ。既存の除外・他の設定は触らない
    - `--dry-run` (既定) で差分を確認してから `--apply`
    - 1件ずつ結果を出し、失敗はその場で表示 (silent drop しない)

使い方:
    python ebay_exclude_regions.py --add MT,CY                 # dry-run (既定)
    python ebay_exclude_regions.py --add MT,CY --apply         # 実行
    python ebay_exclude_regions.py --list                      # 現在の除外を一覧
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\dev\iMak")
sys.path.insert(0, str(ROOT / "iMakeBayAPI"))
try:
    import dns_cache  # noqa: F401  ★これが無いと getaddrinfo failed になる (この環境の作法)
except Exception:
    pass
import requests  # noqa: E402

# ★sell.account (書込) スコープを持つのは _sell 側。通常トークンは read 専用で 401 になる。
TOKEN_FILE = ROOT / "iMakeBayAPI" / "ebay_oauth_token_sell.json"
BACKUP_DIR = ROOT / "iMakeBayAPI"
API = "https://api.ebay.com/sell/account/v1/fulfillment_policy"


def headers(market: str) -> dict:
    tok = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))["access_token"]
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": market}


def fetch_all(market: str) -> list:
    out, offset = [], 0
    while True:
        r = requests.get(API, headers=headers(market),
                         params={"marketplace_id": market, "limit": 100, "offset": offset},
                         timeout=60)
        r.raise_for_status()
        d = r.json()
        got = d.get("fulfillmentPolicies", [])
        out += got
        if len(got) < 100:
            break
        offset += 100
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="EBAY_US")
    ap.add_argument("--add", default="", help="追加する除外コード (例: MT,CY)")
    ap.add_argument("--apply", action="store_true", help="実際に PUT する (既定は dry-run)")
    ap.add_argument("--list", action="store_true", help="現在の除外を一覧して終了")
    a = ap.parse_args()

    print(f"=== {a.market} の fulfillment policy を取得中 ===")
    pols = fetch_all(a.market)
    print(f"  {len(pols)} 件")

    if a.list or not a.add:
        from collections import Counter
        c = Counter()
        for p in pols:
            for r in ((p.get("shipToLocations") or {}).get("regionExcluded") or []):
                c[r.get("regionName", "?")] += 1
        print(f"\n現在の除外 {len(c)} 種 (件数はポリシー数):")
        for k, v in sorted(c.items()):
            print(f"   {k}: {v}")
        return 0

    add = [x.strip().upper() for x in a.add.split(",") if x.strip()]
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    bk = BACKUP_DIR / f"policy_backup_{stamp}_before_exclude_{'_'.join(add)}.json"
    bk.write_text(json.dumps({a.market: pols}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  🗄 バックアップ: {bk.name}")

    need = []
    for p in pols:
        cur = {r.get("regionName") for r in
               ((p.get("shipToLocations") or {}).get("regionExcluded") or [])}
        missing = [x for x in add if x not in cur]
        if missing:
            need.append((p, missing))
    print(f"\n追加が要るポリシー: {len(need)} / {len(pols)}")
    if not need:
        print("  ✅ 全ポリシーに既に入っている。作業なし")
        return 0
    for p, m in need[:5]:
        print(f"   例) {p.get('name')} ← {m}")
    if len(need) > 5:
        print(f"   …他 {len(need)-5} 件")

    if not a.apply:
        print("\n(dry-run) --apply を付けると実行します")
        return 0

    ok = ng = 0
    for p, missing in need:
        pid = p["fulfillmentPolicyId"]
        body = json.loads(json.dumps(p))
        body.pop("fulfillmentPolicyId", None)
        stl = body.setdefault("shipToLocations", {})
        ex = stl.setdefault("regionExcluded", [])
        for code in missing:
            ex.append({"regionName": code})
        r = requests.put(f"{API}/{pid}", headers=headers(a.market),
                         data=json.dumps(body), timeout=60)
        if r.status_code in (200, 204):
            ok += 1
            print(f"  ✅ {p.get('name')}")
        else:
            ng += 1
            print(f"  ❌ {p.get('name')} [{r.status_code}] {r.text[:200]}")
    print(f"\n結果: 成功 {ok} / 失敗 {ng}")
    if ng:
        print("  ⚠️ 失敗が残っています。**除外できていないポリシーがある** = 発送可のまま。"
              "原因を直して再実行すること")
        return 1

    print("\n=== 検証: 読み直して確認 ===")
    again = fetch_all(a.market)
    bad = [p.get("name") for p in again
           if not set(add) <= {r.get("regionName") for r in
                               ((p.get("shipToLocations") or {}).get("regionExcluded") or [])}]
    if bad:
        print(f"  ❌ 反映されていない: {len(bad)} 件 → {bad[:5]}")
        return 1
    print(f"  ✅ 全 {len(again)} ポリシーに {', '.join(add)} が入っている")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
