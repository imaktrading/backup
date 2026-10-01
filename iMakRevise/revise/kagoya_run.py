"""kagoya_run.py - KAGOYA (サーバー) 上で毎朝の値段の見直しを作る (影: eBay には送らない).

2026-10-02 HQ 依頼 (2026-10-02_revise_move_to_kagoya_go.md):
  家の PC の作業を減らすため、API 版を KAGOYA で動かす。初日は影 (送る中身を作るだけ)。
  席 (空きメモリ) は HQ の kagoya_offload.acquire_server_seat を使う (Chrome なし = 0.2GB)。

出力: C:\\setup\\REVISE_offload\\out\\<YYYYMMDD>\\
  - revise_combined_*.csv / revise_variation_*.csv (家と同じ生成物)
  - plan.json (API で送る中身: 値段・送料・組めない行)
  - status.json (ok / no_seat / error と時刻)
家は kagoya_revise.py pull で取りに行き、家の CSV と突き合わせる。
"""
from __future__ import annotations

import json
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))
HQ_TOOLS = r"C:\dev\iMak\iMakHQ\tools"
if HQ_TOOLS not in sys.path:
    sys.path.insert(0, HQ_TOOLS)

OUT_ROOT = Path(r"C:\setup\REVISE_offload\out")
SEAT_OWNER = "REVISE"
NEED_GB = 0.2


def _write_status(out: Path, **kw) -> None:
    out.mkdir(parents=True, exist_ok=True)
    kw["at"] = datetime.now().isoformat(timespec="seconds")
    (out / "status.json").write_text(json.dumps(kw, ensure_ascii=False, indent=1), encoding="utf-8")


def run_shadow() -> int:
    from kagoya_offload import acquire_server_seat, release_server_seat

    out = OUT_ROOT / datetime.now().strftime("%Y%m%d")
    if not acquire_server_seat(SEAT_OWNER, need_gb=NEED_GB):
        _write_status(out, result="no_seat")
        return 2
    try:
        from revise.api_revise import (build_all_xml, build_plan, fetch_shipping_policy_ids,
                                       load_current_profiles)
        from revise.price_revise import SHARED_SNAPSHOT_DIR, run_price_revise

        result = run_price_revise(review_xlsx=False)
        snaps = sorted(SHARED_SNAPSHOT_DIR.glob("ebay_active_*.csv"))
        snap_csv = snaps[-1] if snaps else None
        var_json = snap_csv.with_name(snap_csv.stem + ".variations.json") if snap_csv else None
        plan = build_plan(result.csv_path, result.var_price_path, result.var_shipping_path,
                          var_json, fetch_shipping_policy_ids(),
                          current_profiles=load_current_profiles(snap_csv))
        calls = len(build_all_xml(plan))

        out.mkdir(parents=True, exist_ok=True)
        for p in (result.csv_path, result.var_price_path, result.var_shipping_path):
            if p and Path(p).exists():
                shutil.copy2(p, out / Path(p).name)
        (out / "plan.json").write_text(json.dumps({
            "prices": [vars(c) for c in plan.prices],
            "shippings": [vars(s) for s in plan.shippings],
            "problems": plan.problems, "api_calls": calls,
            "snapshot": snap_csv.name if snap_csv else None,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        _write_status(out, result="ok", mode="shadow", revise=len(result.revisable),
                      prices=len(plan.prices), shippings=len(plan.shippings),
                      problems=len(plan.problems), api_calls=calls)
        return 0
    except Exception as e:  # noqa: BLE001 - 結果は status.json で家に返す
        _write_status(out, result="error", error=f"{type(e).__name__}: {e}",
                      trace=traceback.format_exc()[-2000:])
        return 1
    finally:
        release_server_seat(SEAT_OWNER)


if __name__ == "__main__":
    _out = OUT_ROOT / datetime.now().strftime("%Y%m%d")
    _out.mkdir(parents=True, exist_ok=True)
    with open(_out / "run.log", "w", encoding="utf-8") as _f:
        sys.stdout = sys.stderr = _f  # 予約タスクの出力は残らないので、家で読めるようにファイルへ
        sys.exit(run_shadow())
