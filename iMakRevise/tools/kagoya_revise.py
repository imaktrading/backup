"""kagoya_revise.py - 家から KAGOYA のリバイスくんを扱う (配置 / 予約 / 取り寄せ / 突き合わせ).

接続は HQ の kagoya_offload (_ssh / _scp_to / _scp_from・offload.json) をそのまま使う。

  python -X utf8 tools/kagoya_revise.py deploy    # コードと設定を KAGOYA に送る + 予約 (毎日 04:30・影)
  python -X utf8 tools/kagoya_revise.py run       # 今すぐ KAGOYA で1回 (影)
  python -X utf8 tools/kagoya_revise.py compare [YYYYMMDD]   # 取り寄せて家の CSV と突き合わせる
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
WT_ROOT = PKG_ROOT.parent
sys.path.insert(0, str(PKG_ROOT))
sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import kagoya_offload as k  # noqa: E402

REMOTE_PKG = r"C:\dev\iMak_revise\iMakRevise"
REMOTE_OUT = r"C:\setup\REVISE_offload\out"
REMOTE_PY = k.REMOTE_PY
TASK_NAME = "iMakRevise_KagoyaShadow"
LOCAL_PULL = PKG_ROOT / "csv_output" / "kagoya"
LOG_PATH = PKG_ROOT / "decision_log" / "kagoya_shadow.log"
MATCH_OK_PCT = 95.0

DEPLOY_FILES = (
    [(p, REMOTE_PKG + "\\revise\\" + p.name) for p in sorted((PKG_ROOT / "revise").glob("*.py"))]
    + [(PKG_ROOT / "config" / "revise_params.json", REMOTE_PKG + r"\config\revise_params.json"),
       (WT_ROOT / "iMakeBayAPI" / "credentials.py", r"C:\dev\iMak_revise\iMakeBayAPI\credentials.py"),
       (Path(r"C:/dev/iMak_data/revise/pack_items.json"), r"C:\dev\iMak_data\revise\pack_items.json")]
)


def _ps(cfg, script: str, timeout=120):
    rc, out = k._ssh(cfg, f'powershell -NoProfile -Command "{script}"', timeout=timeout)
    return rc, out


def deploy() -> int:
    cfg = k._cfg()
    dirs = sorted({str(Path(r).parent) for _, r in DEPLOY_FILES} | {REMOTE_OUT, REMOTE_PKG + r"\csv_output"})
    rc, out = _ps(cfg, "; ".join(f"New-Item -ItemType Directory -Force '{d}' | Out-Null" for d in dirs))
    if rc:
        print("mkdir 失敗", out)
        return 1
    bad = [str(l) for l, r in DEPLOY_FILES if k._scp_to(cfg, str(l), r)]
    if bad:
        print("送れなかった:", bad)
        return 1
    ps1 = PKG_ROOT / "tools" / "_kagoya_register_task.ps1"
    run_py = REMOTE_PKG + r"\revise\kagoya_run.py"
    ps1.write_text("\n".join([
        f"$a = New-ScheduledTaskAction -Execute '{REMOTE_PY}' "
        f"-Argument '-X utf8 \"{run_py}\"' -WorkingDirectory '{REMOTE_PKG}'",
        "$t = New-ScheduledTaskTrigger -Daily -At 04:30",
        f"Register-ScheduledTask -TaskName {TASK_NAME} -Action $a -Trigger $t -User SYSTEM -RunLevel Highest -Force | Out-Null",
        f"(Get-ScheduledTaskInfo -TaskName {TASK_NAME}).NextRunTime",
    ]) + "\n", encoding="utf-8")
    remote_ps1 = r"C:\setup\REVISE_offload\register_task.ps1"
    if k._scp_to(cfg, str(ps1), remote_ps1):
        print("予約スクリプトを送れなかった")
        return 1
    rc, out = k._ssh(cfg, f'powershell -NoProfile -ExecutionPolicy Bypass -File "{remote_ps1}"')
    print(f"送った {len(DEPLOY_FILES)} 本 / 予約 {TASK_NAME} rc={rc} {out.strip()}")
    return rc


def run_now() -> int:
    cfg = k._cfg()
    """予約タスクを今すぐ起動 (本番と同じ SYSTEM で動く)。結果は compare / status.json で見る."""
    rc, out = k._ssh(cfg, f"Start-ScheduledTask -TaskName {TASK_NAME}")
    print(f"起動 rc={rc} {out.strip()}")
    return rc


def _prices_from_csvs(folder: Path) -> tuple:
    from revise.api_revise import _norm_specifics, _read_csv
    prices, ships = {}, {}
    for f in folder.glob("revise_combined_*.csv"):
        for r in _read_csv(f):
            if r.get("*StartPrice"):
                prices[(r["ItemID"], None)] = r["*StartPrice"]
            if r.get("ShippingProfileName"):
                ships[r["ItemID"]] = r["ShippingProfileName"]
    for f in folder.glob("revise_variation_price_*.csv"):
        parent = None
        for r in _read_csv(f):
            if r.get("ItemID"):
                parent = r["ItemID"]
            elif r.get("Relationship") == "Variation" and r.get("*StartPrice"):
                prices[(parent, _norm_specifics(r["RelationshipDetails"]))] = r["*StartPrice"]
    for f in folder.glob("revise_variation_shipping_*.csv"):
        for r in _read_csv(f):
            if r.get("ShippingProfileName"):
                ships[r["ItemID"]] = r["ShippingProfileName"]
    return prices, ships


def _snapshot_state(snap: Path) -> tuple:
    from revise.api_revise import _specifics_key
    cur, prof = {}, {}
    with open(snap, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("Listing site") or "").strip() == "US":
                try:
                    cur[r["Item number"]] = float(r["Current price"])
                except (TypeError, ValueError):
                    pass
                prof[r["Item number"]] = r.get("Shipping profile name") or ""
    vj = snap.with_name(snap.stem + ".variations.json")
    vcur = {}
    if vj.exists():
        for i, vs in json.loads(vj.read_text(encoding="utf-8")).items():
            for v in vs:
                vcur[(i, _specifics_key(v.get("specifics") or {}))] = v.get("start_price")
    return cur, prof, vcur


def _effective(prices: dict, ships: dict, cur: dict, prof: dict, vcur: dict) -> tuple:
    def changed(key, v):
        now = cur.get(key[0]) if key[1] is None else vcur.get(key)
        return now is None or abs(float(v) - float(now)) > 0.001
    return ({k: v for k, v in prices.items() if changed(k, v)},
            {k: v for k, v in ships.items() if prof.get(k) != v})


def compare(day: str | None = None) -> int:
    cfg = k._cfg()
    day = day or datetime.now().strftime("%Y%m%d")
    dst = LOCAL_PULL / day
    dst.mkdir(parents=True, exist_ok=True)
    rc = k._scp_from(cfg, f"{REMOTE_OUT}\\{day}\\*", str(dst))
    status = json.loads((dst / "status.json").read_text(encoding="utf-8")) if (dst / "status.json").exists() else {}
    if rc or status.get("result") != "ok":
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} [kagoya] {day} 取り寄せ rc={rc} status={status.get('result')} {status.get('error', '')}"
        _log(line)
        return 1

    home = PKG_ROOT / "csv_output"
    home_day = Path(dst.parent / f"_home_{day}")
    home_day.mkdir(exist_ok=True)
    import shutil
    for pat in ("revise_combined_", "revise_variation_price_", "revise_variation_shipping_"):
        cands = sorted(p for p in home.glob(f"{pat}{day}_*.csv") if "_diff" not in p.name)
        if cands:
            shutil.copy2(cands[0], home_day / cands[0].name)
    # 比べるのは「eBay の今と違う物 = 実際に変わる物」だけ。
    # 家の CSV は送料の控えが古く、値段も送料も変わらない行を毎朝書いている (API 版は送る前に落とす) ので、生の行数は合わない
    snaps = sorted(Path(r"C:/dev/iMak_data/snapshots").glob(f"ebay_active_{day[:4]}-{day[4:6]}-{day[6:]}_0*.csv"))
    cur, prof, vcur = _snapshot_state(snaps[0]) if snaps else ({}, {}, {})
    hp, hs = _effective(*_prices_from_csvs(home_day), cur, prof, vcur)
    kp, ks = _effective(*_prices_from_csvs(dst), cur, prof, vcur)
    p_same = sum(1 for key, v in hp.items() if kp.get(key) == v)
    s_same = sum(1 for key, v in hs.items() if ks.get(key) == v)
    only_k = len(set(kp) - set(hp)) + len(set(ks) - set(hs))
    total = len(hp) + len(hs)
    pct = round(100 * (p_same + s_same) / total, 2) if total else 0.0
    line = (f"{datetime.now():%Y-%m-%d %H:%M:%S} [kagoya] {day} 実際に変わる物で家と一致 {pct}% "
            f"値段 {p_same}/{len(hp)} 送料 {s_same}/{len(hs)} KAGOYAだけ {only_k} | "
            f"API呼出 {status.get('api_calls')} 組めない {status.get('problems')}")
    _log(line)
    diffs = ([("家だけ/値違い", key, hp[key], kp.get(key)) for key in hp if kp.get(key) != hp[key]]
             + [("KAGOYAだけ", key, None, kp[key]) for key in kp if key not in hp])[:20]
    for d in diffs:
        _log(f"   - {d}")
    # 毎朝 1〜3% は「為替を数分違いで取った $1 の端数」「送料ポリシーの控えの古さ」で必ずずれる (10/3〜10/7 実測)。
    # それで毎日「失敗」にすると本当の異常が埋もれるので、95% 未満だけ失敗にする
    return 0 if pct >= MATCH_OK_PCT else 1


def _log(line: str) -> None:
    print(line)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "deploy":
        sys.exit(deploy())
    if cmd == "run":
        sys.exit(run_now())
    if cmd == "compare":
        sys.exit(compare(sys.argv[2] if len(sys.argv) > 2 else None))
    print(__doc__)
    sys.exit(2)
