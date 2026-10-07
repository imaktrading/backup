"""after_kagoya.py - 毎朝の値段の見直しを KAGOYA で送った後、家で受け取る (2026-10-07 移管).

KAGOYA (04:30, kagoya_run.py --live) が本番。家はこれを 05:15 に動かす:
  1. KAGOYA の今日の結果を取り寄せる (届いていなければ最大 40分待つ)
  2. 送れていれば: CSV / review.xlsx を csv_output に置き、daily_revise.log に「UP 成功 … (KAGOYA)」を書く
     (台帳 price_ledger はこの行で数える)、値動きファイル (price_moves_high.json) と結果メールを出す
  3. 送れていなければ (席が取れない / 送信失敗 / 届かない): 家で run_daily (API → だめなら Chrome) を回す
  4. 家でも同じ時刻の入力で作るだけ作って (送らない)、KAGOYA と突き合わせる (逆向きの影・数日)
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

PKG_ROOT = Path(__file__).resolve().parent.parent
if str(PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(PKG_ROOT))

from revise.run_daily import _log, _send_summary, _write_price_moves  # noqa: E402

CSV_DIR = PKG_ROOT / "csv_output"
WAIT_MAX_SEC = 40 * 60
WAIT_STEP_SEC = 60


def _pull(day: str, dst: Path) -> dict:
    """KAGOYA の out/<day> を dst に取る. status.json の中身を返す (無ければ {})."""
    sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
    import kagoya_offload as k
    from tools.kagoya_revise import REMOTE_OUT
    dst.mkdir(parents=True, exist_ok=True)
    k._scp_from(k._cfg(), f"{REMOTE_OUT}\\{day}\\*", str(dst))
    st = dst / "status.json"
    try:
        return json.loads(st.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wait_for_kagoya(day: str, dst: Path, sleep_fn=time.sleep, pull_fn=_pull) -> dict:
    waited = 0
    while True:
        st = pull_fn(day, dst)
        if st.get("mode") == "live" or waited >= WAIT_MAX_SEC:
            return st
        sleep_fn(WAIT_STEP_SEC)
        waited += WAIT_STEP_SEC


def result_from_review(review: Path):
    """KAGOYA の review.xlsx → 結果メール / 値動きファイル用の result 相当 (送った行だけ)."""
    import openpyxl
    wb = openpyxl.load_workbook(review, read_only=True)
    rows = wb["review"].iter_rows(values_only=True)
    h = list(next(rows))
    ix = {k: h.index(k) for k in ("sheet", "ItemID", "SKU/Size", "Title", "Category", "旧USD", "新USD",
                                  "revise内容", "判定理由", "異常検出")}
    revisable, abnormal = [], []
    for r in rows:
        if not r[ix["ItemID"]]:
            continue
        c = SimpleNamespace(item_id=str(r[ix["ItemID"]]), source_sheet=r[ix["sheet"]], title=r[ix["Title"]],
                            category=r[ix["Category"]], current_usd=r[ix["旧USD"]], new_usd=r[ix["新USD"]],
                            is_variation=r[ix["SKU/Size"]] is not None, revise_content=r[ix["revise内容"]] or "",
                            decision_details=str(r[ix["判定理由"]] or ""))
        revisable.append(c)
        if r[ix["異常検出"]]:
            abnormal.append(c)
    wb.close()
    return SimpleNamespace(revisable=revisable, abnormal=abnormal, skipped=[])


def home_check(day: str) -> str:
    """逆向きの影: KAGOYA が送った後に家で作るだけ作り (送らない)、まだ直す物が残っているかを数える.
    KAGOYA と家の判断が同じなら、ほぼ0件 (為替の数分差で $1 の端数は残りうる)."""
    from revise.price_revise import run_price_revise
    r = run_price_revise(review_xlsx=False)
    dst = CSV_DIR / "kagoya" / day / "home_check"
    dst.mkdir(parents=True, exist_ok=True)
    for p in (r.csv_path, r.var_price_path, r.var_shipping_path):
        if p and Path(p).exists():
            shutil.move(str(p), dst / Path(p).name)
    for p in CSV_DIR.glob(f"revise_combined_diff_{Path(r.csv_path).stem[-15:]}.csv") if r.csv_path else []:
        shutil.move(str(p), dst / p.name)
    n_price = sum(1 for c in r.revisable if c.current_usd and c.new_usd and abs(c.new_usd - c.current_usd) >= 0.01)
    n_pol = sum(1 for c in r.revisable if getattr(c, "revise_content", "") in ("Policy のみ", "USD+Policy"))
    return f"KAGOYA 送信後に家で見直し: まだ直す物 {len(r.revisable)} 件 (値段 {n_price} / 送料 {n_pol})"


def main() -> int:
    day = datetime.now().strftime("%Y%m%d")
    pulled = CSV_DIR / "kagoya" / day
    _log(f"[daily] === KAGOYA の結果を受け取る {day} ===")
    st = wait_for_kagoya(day, pulled)

    if st.get("mode") == "live" and st.get("result") == "ok" and st.get("sent_ok"):
        uploads = []
        labels = {"revise_combined_": "single", "revise_variation_price_": "variation価格",
                  "revise_variation_shipping_": "variation送料"}
        for f in sorted(pulled.glob("revise_*.csv")) + sorted(pulled.glob("revise_review_*.xlsx")):
            shutil.copy2(f, CSV_DIR / f.name)
        for prefix, label in labels.items():
            for f in sorted(pulled.glob(f"{prefix}{day}_*.csv")):
                _log(f"[daily] UP 成功 [{label}] {f.name} (KAGOYA)")
                uploads.append({"label": label + " (KAGOYA API)", "csv": f.name, "success": True,
                                "attempts": 1, "error": None})
        reviews = sorted(pulled.glob("revise_review_*.xlsx"))
        result = result_from_review(reviews[-1]) if reviews else SimpleNamespace(revisable=[], abnormal=[], skipped=[])
        _write_price_moves(result, uploads)
        mail_rc = _send_summary(result, uploads, dry_run=False)
        _log(f"[daily] === 完了 (KAGOYA) revise={st.get('revise')} 急騰値上げ={st.get('abnormal')} "
             f"API呼出={st.get('api_calls')} mail_rc={mail_rc} ===")
        try:
            _log(f"[kagoya-check] {home_check(day)}")
        except Exception as e:  # noqa: BLE001 - 影の失敗で本番の結果を変えない
            _log(f"[kagoya-check] 家での見直し失敗 (本番には影響なし): {type(e).__name__}: {e}")
        return 0 if mail_rc == 0 else 1

    _log(f"[daily] KAGOYA で送れていない (status={st.get('result') or '届かず'} {st.get('reason', '')}) → 家で送る")
    from revise.run_daily import run_daily
    return run_daily(dry_run=False)


if __name__ == "__main__":
    sys.exit(main())
