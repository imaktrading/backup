"""build_yodobashi_snapshot - G-shock LOW の ヨドバシ補URL 型番の (在庫,価格) snapshot を生成.

2026-07-26 本実装 (HQ `..._impl_go_WRITE_GO.md`)。監視くん(Inventory)が
`C:/dev/iMak_data/harvest/yodobashi_stock_snapshot.json` を **型番キーで lookup** して
M=min(在庫あり 主+補) に効かせる。監視くんに Selenium/HTTP を叩かせない設計。

- 対象型番 = G-shock LOW(1jF9vggb)で **ヨドバシ URL を持つ行**(A or AC-AG)の型番集合。
- 取得 = `yodobashi_search_http.stock_price_by_model` (素の HTTP、word=型番 検索タイル)。
- fail-closed: 型番不一致/複数/fetch失敗/challenge → in_stock=null (= 監視くんは延命に使わない)。
- 形: { "<型番>": {"in_stock": bool|null, "price_jpy": int|null, "url": str|null}, ...,
        "generated_at": "<iso>" }
- cadence: LOW cycle(22:30)直前に1回 (Inventory は generated_at 12h 超で stale 扱い)。

使い方:
  python build_yodobashi_snapshot.py --dry-run   # 生成せず対象型番と取得結果を表示
  python build_yodobashi_snapshot.py             # snapshot JSON を上書き生成
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from scrapers import yodobashi_search_http as Y  # noqa: E402
from scrapers.yodobashi_search_http import extract_model_from_title  # noqa: E402
from sheet_writer_amazon import (  # noqa: E402
    LISTINGS_GID,
    LOW_SHEET_ID,
    get_listings_worksheet,
    open_sheet_by_id,
)

SNAPSHOT_PATH = Path(r"c:\dev\iMak_data\harvest\yodobashi_stock_snapshot.json")
COL_URL = 1
COL_SUPP_START = 29  # AC
COL_SUPP_END = 33    # AG
COL_KEY = 35         # AI


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def _with_retry(fn, what: str, attempts: int = 5):
    """DNS flapping / Google API 503 (2026-07 環境) 耐性の backoff リトライ.

    2026-07-28: 06:00 snapshot が Sheets API 503 で silent 失敗した事故対策。
    """
    import time  # noqa: PLC0415
    last = None
    for att in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            _log(f"  {what} retry {att}/{attempts} ({type(e).__name__}) → backoff")
            time.sleep(5 * att)
    raise last


def _cell(row, c):
    return (row[c - 1].strip() if len(row) >= c else "")


def _has_yodobashi(row) -> bool:
    cols = [COL_URL] + list(range(COL_SUPP_START, COL_SUPP_END + 1))
    return any("yodobashi.com" in _cell(row, c).lower() for c in cols)


def collect_target_models() -> list[str]:
    """LOW で ヨドバシ URL を持つ行の型番集合 (dedup、 順序保持)."""
    ws = _with_retry(
        lambda: get_listings_worksheet(open_sheet_by_id(LOW_SHEET_ID), LISTINGS_GID),
        "LOW open")
    vals = _with_retry(ws.get_all_values, "LOW get_all_values")
    out: list[str] = []
    seen: set[str] = set()
    for row in vals[1:]:
        if not _has_yodobashi(row):
            continue
        model = (_cell(row, COL_KEY) or extract_model_from_title(_cell(row, 3))).upper()
        if model and model not in seen:
            seen.add(model)
            out.append(model)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rate-min", type=float, default=1.0)
    ap.add_argument("--rate-max", type=float, default=2.5)
    args = ap.parse_args(argv)

    models = collect_target_models()
    _log(f"対象型番 (LOW でヨドバシURL保持): {len(models)}")
    if not models:
        _log("対象なし")
        return 0

    session = Y.create_session()
    snapshot: dict[str, dict] = {}
    stats = {"in_stock": 0, "out_or_unknown": 0}
    for i, model in enumerate(models, 1):
        r = Y.stock_price_by_model(session, model)
        # fail-closed: ok=False → in_stock=null
        in_stock = r["in_stock"] if r["ok"] else None
        snapshot[model] = {
            "in_stock": in_stock,
            "price_jpy": r["price_jpy"] if r["ok"] else None,
            "url": r["url"] if r["ok"] else None,
        }
        if in_stock:
            stats["in_stock"] += 1
        else:
            stats["out_or_unknown"] += 1
        if i % 10 == 0 or i == len(models):
            _log(f"  {i}/{len(models)} (在庫あり={stats['in_stock']} "
                 f"在庫なし/不能={stats['out_or_unknown']})")
        if i < len(models):
            time.sleep(random.uniform(args.rate_min, args.rate_max))

    snapshot["generated_at"] = datetime.now().astimezone().isoformat()
    _log(f"集計: 在庫あり={stats['in_stock']} 在庫なし/判定不能={stats['out_or_unknown']} "
         f"/ 型番={len(models)}")

    if args.dry_run:
        _log("dry-run: 生成なし")
        _log(json.dumps({k: snapshot[k] for k in list(snapshot)[:3]},
                        ensure_ascii=False, indent=2))
        return 0

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"生成完了: {SNAPSHOT_PATH} (型番 {len(models)} + generated_at)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
