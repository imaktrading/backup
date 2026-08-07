"""
ebay_update_all_policies.py - 既存 eBay Shipping Policy を PUT API で update

V8 FIX 2026-05-24 新規作成。 完成形 Phase 1-D に基づく。

仕様:
- 既存 Policy ID を維持 → 既存 listing 紐付け自動追従 (= 個別 revise 不要)
- snapshot/policy_full_export.json から既存 body 取得
- yaml.v6_pricing から hts_rate / split 取得して送料 cost を再計算
- shippingOptions[].shippingServices[].shippingCost.value を update して PUT

引数:
  --groups A,B,C   : 更新対象グループ (= default 全て、 sandbox では Porter=B not C なので注意)
  --names PATTERN  : Policy name regex で絞込 (例: "DDP-[BC]-")
  --dry-run        : 変更内容のみ表示、 PUT は実行しない

使用例:
  # sandbox (Phase 3-1): Porter (= group B) + G-SHOCK (= group A) のみ
  python ebay_update_all_policies.py --names "^DDP-[AB]-"
  # 全体 (Phase 3-4): 全 Policy
  python ebay_update_all_policies.py
  # 検証
  python ebay_update_all_policies.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
import yaml

# ------------ 設定 ------------
ROOT = Path(r"c:\dev\iMak")
YAML_PATH = ROOT / "iMakeBayAPI" / "config" / "global.yaml"
TOKEN_FILE = ROOT / "iMakeBayAPI" / "ebay_oauth_token.json"
SNAPSHOT = ROOT / "_backup" / "pre_v8_fix_20260524" / "policy_full_export.json"
JST = timezone(timedelta(hours=9))
EBAY_API = "https://api.ebay.com/sell/account/v1/fulfillment_policy"


def log(msg: str) -> None:
    ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def parse_policy_name(name: str) -> tuple[str, int] | None:
    """DDP-A-P05 → ('A', 5)"""
    m = re.match(r"^DDP-([ABC])-P(\d+)$", name)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def calc_cost(upper: int, hts_rate: float, split: float) -> float:
    """V6 cost 計算 (= ebay_create_all_policies.ps1 と同じ)"""
    return round(upper * hts_rate * 1.021 * split + 1.5, 2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", default="A,B,C", help="対象グループ (例: B,C)")
    parser.add_argument("--names", default="", help="Policy name regex 絞込")
    parser.add_argument("--dry-run", action="store_true", help="変更内容表示のみ")
    args = parser.parse_args()

    target_groups = set(g.strip() for g in args.groups.split(","))
    name_filter = re.compile(args.names) if args.names else None

    log("=== ebay_update_all_policies.py 開始 ===")
    log(f"target_groups: {target_groups}")
    log(f"name_filter: {args.names or '(none)'}")
    log(f"dry-run: {args.dry_run}")

    # 1. yaml 読込
    with YAML_PATH.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    v6 = cfg["v6_pricing"]
    yaml_groups = v6["groups"]
    bins = v6["price_tier_uppers"]
    log(f"yaml v6_pricing.groups: " + ", ".join(f"{k}={v}" for k, v in yaml_groups.items()))

    # 2. snapshot 読込
    if not SNAPSHOT.exists():
        log(f"ABORT: snapshot {SNAPSHOT} 不在、 Phase 0-4 完了を確認")
        return 1
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8-sig"))
    policies = snap.get("fulfillmentPolicies", [])
    log(f"snapshot policies: {len(policies)}")

    # 3. token
    token_data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    headers = {
        "Authorization": f"Bearer {token_data['access_token']}",
        "Content-Type": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }

    # 4. 各 Policy 処理
    targets = []
    for p in policies:
        name = p.get("name", "")
        parsed = parse_policy_name(name)
        if not parsed:
            continue
        gid, tier_n = parsed
        if gid not in target_groups:
            continue
        if name_filter and not name_filter.search(name):
            continue
        if tier_n < 1 or tier_n > len(bins):
            log(f"  skip: {name} tier {tier_n} 範囲外")
            continue
        upper = bins[tier_n - 1]
        g = yaml_groups[gid]
        new_cost = calc_cost(upper, float(g["hts_rate"]), float(g["split"]))
        targets.append((p, gid, tier_n, upper, new_cost))

    log(f"対象 Policy 数: {len(targets)}")

    success, failed, unchanged = 0, 0, 0
    for p, gid, tier_n, upper, new_cost in targets:
        pid = p["fulfillmentPolicyId"]
        name = p["name"]

        # body 更新: shippingOptions[*].shippingServices[*].shippingCost.value
        body = json.loads(json.dumps(p))  # deepcopy
        body.pop("fulfillmentPolicyId", None)
        old_costs = []
        new_count = 0
        for opt in body.get("shippingOptions", []):
            if opt.get("optionType") != "DOMESTIC":
                continue
            for svc in opt.get("shippingServices", []):
                old = svc.get("shippingCost", {}).get("value")
                old_costs.append(old)
                if old is not None:
                    svc["shippingCost"]["value"] = f"{new_cost:.2f}"
                    new_count += 1

        if new_count == 0:
            log(f"  {name} (P{tier_n:02d}): DOMESTIC service 不在、 skip")
            continue
        if all(float(c or 0) == new_cost for c in old_costs if c):
            unchanged += 1
            log(f"  {name} (upper={upper}): cost {new_cost} 変更なし")
            continue

        log(f"  {name} (upper={upper}): {old_costs} -> {new_cost}")
        if args.dry_run:
            success += 1
            continue

        # PUT
        try:
            resp = requests.put(f"{EBAY_API}/{pid}", headers=headers, json=body, timeout=30)
            if resp.status_code in (200, 204):
                success += 1
            else:
                log(f"    FAIL {resp.status_code}: {resp.text[:300]}")
                failed += 1
        except Exception as e:
            log(f"    EXCEPTION: {e}")
            failed += 1
        time.sleep(0.3)  # rate limit 緩和

    log(f"=== 結果: success={success} / failed={failed} / unchanged={unchanged} ===")
    return 0 if failed == 0 else 5


if __name__ == "__main__":
    sys.exit(main())
