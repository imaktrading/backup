"""price_ledger.py - 出品ごとの「値段を変えた回数・下げた回数・最後に変えた日」の台帳.

2026-10-01 HQ 依頼 (2026-10-01_price_change_counts_ledger.md):
  HQ の棚② が「一度も値下げしていない出品は落とさず値下げ候補へ」の判定に使う。
  出力: C:/dev/iMak_data/revise/price_change_counts.json (一時ファイル → 置き換え)

数え方 (毎回、残っている記録から全部数え直す = 決定的):
  - 入力 = 日次 revise の review.xlsx (旧USD = その朝の eBay 実値 / 新USD = 送った値)
  - eBay に届いたと確かめられた走行だけ数える: daily_revise.log に「UP 成功」がある CSV
    (single → 単品行 / variation価格 → variation 行)。失敗・dry-run・7/10 以前の手動分は数えない
    → 数え漏れは「値下げしていない」側に倒れる (= 落とさない側。安全側)
  - 1走行1回: revise内容に USD を含み 新USD≠旧USD の行がある出品を changes+1
    variation は SKU ごとの差を見て、全部下げ → downs+1 / 全部上げ → ups+1 (混在は changes のみ)
  - first_price = 最初に見えた旧USD / now_price = 最新 snapshot の US 価格 (snapshot 後に送った分は新USD)
    variation の値段は SKU の最安
  - 出品の母集団 = 最新 snapshot の US 行 (ミラーは入れない) + 記録にある出品
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
CSV_DIR = PKG_ROOT / "csv_output"
DAILY_LOG = PKG_ROOT / "decision_log" / "daily_revise.log"
SNAPSHOT_DIR = Path(r"C:/dev/iMak_data/snapshots")
OUT_PATH = Path(r"C:/dev/iMak_data/revise/price_change_counts.json")

_UP_OK = re.compile(r"UP 成功 \[(single|variation価格)\] revise_(?:combined|variation_price)_(\d{8}_\d{6})\.csv")


def confirmed_runs(log_path: Path = DAILY_LOG) -> dict:
    """{ts: {"single", "variation"}} — eBay に届いた CSV の走行."""
    runs: dict = {}
    if not log_path.exists():
        return runs
    for line in log_path.read_text(encoding="utf-8").splitlines():
        m = _UP_OK.search(line)
        if m:
            runs.setdefault(m.group(2), set()).add("single" if m.group(1) == "single" else "variation")
    return runs


def _review_path(ts: str) -> Path | None:
    p = CSV_DIR / f"revise_review_{ts}.xlsx"
    if p.exists():
        return p
    base = datetime.strptime(ts, "%Y%m%d_%H%M%S")
    for q in CSV_DIR.glob(f"revise_review_{ts[:8]}_*.xlsx"):
        if abs((datetime.strptime(q.stem[-15:], "%Y%m%d_%H%M%S") - base).total_seconds()) <= 5:
            return q
    return None


def read_review(path: Path) -> list:
    """review シート → [(item_id, is_variation, old_usd, new_usd, content)]."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["review"]
    rows = ws.iter_rows(values_only=True)
    hdr = list(next(rows))
    ix = {k: hdr.index(k) for k in ("ItemID", "SKU/Size", "旧USD", "新USD", "revise内容")}
    out = []
    for r in rows:
        item = r[ix["ItemID"]]
        if not item:
            continue
        out.append((str(item).strip(), r[ix["SKU/Size"]] is not None,
                    r[ix["旧USD"]], r[ix["新USD"]], str(r[ix["revise内容"]] or "")))
    wb.close()
    return out


def _latest_snapshot() -> tuple:
    files = sorted(SNAPSHOT_DIR.glob("ebay_active_*.csv"))
    if not files:
        return None, {}
    p = files[-1]
    prices = {}
    with open(p, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("Listing site") or "").strip() == "US" and r.get("Item number"):
                try:
                    prices[r["Item number"].strip()] = float(r["Current price"])
                except (TypeError, ValueError):
                    pass
    ts = datetime.strptime(p.stem[len("ebay_active_"):], "%Y-%m-%d_%H%M%S").strftime("%Y%m%d_%H%M%S")
    return ts, prices


def build_ledger(runs: dict, review_reader=read_review, snapshot=None) -> dict:
    snap_ts, snap_prices = snapshot if snapshot is not None else _latest_snapshot()
    items: dict = {}
    covered = []
    for ts in sorted(runs):
        path = _review_path(ts)
        if not path:
            continue
        covered.append(ts)
        per_item: dict = {}
        for item_id, is_var, old, new, content in review_reader(path):
            if ("variation" if is_var else "single") not in runs[ts]:
                continue
            if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
                continue
            d = per_item.setdefault(item_id, {"diffs": [], "old_min": old, "new_min": new})
            d["old_min"] = min(d["old_min"], old)
            d["new_min"] = min(d["new_min"], new)
            if "USD" in content and round(new - old, 2) != 0:
                d["diffs"].append(new - old)
        day = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        for item_id, d in per_item.items():
            e = items.setdefault(item_id, {"changes": 0, "downs": 0, "ups": 0,
                                           "first_price": d["old_min"], "now_price": d["new_min"],
                                           "last_change": None})
            if d["diffs"]:
                e["changes"] += 1
                if all(x < 0 for x in d["diffs"]):
                    e["downs"] += 1
                elif all(x > 0 for x in d["diffs"]):
                    e["ups"] += 1
                e["last_change"] = day
            e["_last_ts"] = ts
            e["now_price"] = d["new_min"]

    for item_id, price in snap_prices.items():
        e = items.setdefault(item_id, {"changes": 0, "downs": 0, "ups": 0, "first_price": price,
                                       "now_price": price, "last_change": None})
        if not snap_ts or e.get("_last_ts", "") < snap_ts:
            e["now_price"] = price
    for e in items.values():
        e.pop("_last_ts", None)
    return {"updated": datetime.now().astimezone().isoformat(timespec="seconds"),
            "coverage": {"from": covered[0] if covered else None, "to": covered[-1] if covered else None,
                         "runs": len(covered), "snapshot": snap_ts},
            "items": items}


def write_atomic(data: dict, out: Path = OUT_PATH) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, out)


def main() -> int:
    data = build_ledger(confirmed_runs())
    write_atomic(data)
    it = data["items"].values()
    print(f"[ledger] {OUT_PATH} items={len(data['items'])} coverage={data['coverage']} "
          f"changed={sum(1 for e in it if e['changes'])} "
          f"downed={sum(1 for e in data['items'].values() if e['downs'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
