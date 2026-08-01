"""ONE PIECE 公式 dump を定期取得する (退避 → 取得 → 検証 → 壊れていたら巻き戻す).

背景 (2026-08-02):
    公式 dump が **2026-05-30 から 2ヶ月止まっていた**。手 kick 専用で、誰も回していなかった。
    その間に ST-31〜36 (公式90枚) が catalog に 30枚しか無い状態が凍結していた。
    「止まったことに誰も気づかない」= fail-OPEN なので、**定期実行 + 検証 + 明示的な要対応**
    にする。→ [[failclosed_must_skip_not_destructive]]

やること (1回分):
    1. dumps dir と products.sqlite を退避
    2. Catalog の fetch script を起動 (**取得スクリプトは Catalog の持ち物**。ここでは呼ぶだけ)
    3. 取得後に検証:
       - dump JSON が **減っていない** こと (公式が落ちていた時に空 dump で上書きしない)
       - INVARIANTS の tag 件数が **1件も変わっていない** こと
    4. 1つでも壊れていたら **dumps と DB を巻き戻して exit 1**
    5. 結果を1行サマリで残す。**全部通った時だけ「正常」と書く**

使い方:
    python opcg_dump_refresh.py            # 1回実行 (検証つき)
    python opcg_dump_refresh.py --check    # 取得せず、今の状態と鮮度だけ見る
    python opcg_dump_refresh.py --install  # 月次タスクとして登録 (毎月1日 04:00)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DATA = Path("C:/dev/iMak_data/catalog")
DUMPS = DATA / "_opcg_official_dumps"
DB = DATA / "products.sqlite"
# 取得スクリプトは Catalog worktree の持ち物。**中身は触らない。呼ぶだけ。**
# (`.gitignore` の `**/_*.py` で untracked なので、こちらから import はできない)
FETCH = Path("C:/dev/iMak_catalog/iMakCatalog/scrapers/_opcg_official_local_fetch.py")
LOG_DIR = Path(__file__).resolve().parent.parent / "review_logs"

# 過去に人が焼いた tag の件数。**取得で1件でも動いたら異常**として巻き戻す。
# (2026-07-31 Ultra Prism 空欄化 / 2026-08-01 promo backfill / 2026-08-01 ST-21,22,25 restamp)
INVARIANTS = {
    "blanked_by_ultra_prism_mismap_20260731": 327,
    "filter_map_backfill_20260801": 21,
    "filter_map_restamp_20260801": 76,
}
# 取得が「まともに終わった」とみなす最低 dump 数。公式 series は 61 (2026-08-02 実測)。
MIN_DUMPS = 55
# 取得の上限時間。61 series × 約8秒 + ingest で 10分前後なので、その4倍で頭打ちにする。
TIMEOUT_SEC = 40 * 60
# この日数より古かったら「止まっている」とみなす (月次なので余裕を持たせる)。
STALE_DAYS = 45


def log(msg: str, logfile: Path | None = None) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    if logfile is not None:
        try:
            logfile.parent.mkdir(parents=True, exist_ok=True)
            with open(logfile, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def dump_count() -> int:
    try:
        return len(list(DUMPS.glob("*.json")))
    except OSError:
        return 0


def dump_age_days() -> float | None:
    """一番新しい dump の経過日数。dump が無ければ None."""
    files = list(DUMPS.glob("*.json"))
    if not files:
        return None
    newest = max(f.stat().st_mtime for f in files)
    return (time.time() - newest) / 86400


def invariant_counts() -> dict[str, int]:
    """set_name_ebay_source の tag ごとの件数 (read-only)."""
    out = {k: 0 for k in INVARIANTS}
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        for pid_specs, in con.execute("SELECT specs FROM products WHERE specs LIKE '%set_name_ebay_source%'"):
            try:
                src = (json.loads(pid_specs) or {}).get("set_name_ebay_source")
            except (ValueError, TypeError):
                continue
            if src in out:
                out[src] += 1
    except sqlite3.Error:
        # DB が壊れている / 読めない。**ここで落とすと巻き戻しにも入れない**ので 0 を返し、
        # 呼び出し側の invariant 不一致として「⚠️要対応」に倒す。
        return {k: 0 for k in INVARIANTS}
    finally:
        con.close()
    return out


def check(logfile: Path | None = None) -> int:
    """取得せず、今の鮮度と invariant だけ見る。止まっていたら 1 を返す."""
    n, age = dump_count(), dump_age_days()
    inv = invariant_counts()
    bad_inv = {k: (v, INVARIANTS[k]) for k, v in inv.items() if v != INVARIANTS[k]}
    log(f"dump {n}件 / 最終取得 {'不明' if age is None else f'{age:.1f}日前'} / invariant {inv}", logfile)
    stale = age is None or age > STALE_DAYS
    if stale:
        log(f"⚠️要対応: dump が {STALE_DAYS}日以上更新されていない (取得が止まっている)", logfile)
    if bad_inv:
        log(f"⚠️要対応: invariant がズレている {bad_inv}", logfile)
    if stale or bad_inv:
        return 1
    log("正常: dump は新しく、invariant も一致", logfile)
    return 0


def _restore(dumps_bak: Path, db_bak: Path, logfile: Path) -> None:
    log("巻き戻し中 (dumps + DB)…", logfile)
    try:
        if dumps_bak.is_dir():
            shutil.rmtree(DUMPS, ignore_errors=True)
            shutil.copytree(dumps_bak, DUMPS)
        if db_bak.is_file():
            shutil.copy2(db_bak, DB)
        log("巻き戻し完了 (退避前の状態に戻した)", logfile)
    except OSError as e:
        log(f"⚠️要対応: 巻き戻しに失敗した ({e})。退避は {dumps_bak} / {db_bak} に残っている", logfile)


def refresh() -> int:
    stamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    logfile = LOG_DIR / f"opcg_dump_refresh_{datetime.now():%Y-%m-%d}.log"
    if not FETCH.is_file():
        log(f"⚠️要対応: 取得スクリプトが無い ({FETCH})。Catalog worktree の状態を確認すること", logfile)
        return 1

    before_n = dump_count()
    before_inv = invariant_counts()
    log(f"開始: dump {before_n}件 / invariant {before_inv}", logfile)

    dumps_bak = DATA / f"_opcg_official_dumps.bak_{stamp}"
    db_bak = DATA / f"products.sqlite.bak_{stamp}"
    try:
        shutil.copytree(DUMPS, dumps_bak)
        shutil.copy2(DB, db_bak)
    except OSError as e:
        log(f"⚠️要対応: 退避に失敗したので取得しない ({e})", logfile)
        return 1
    log(f"退避: {dumps_bak.name} / {db_bak.name}", logfile)

    try:
        r = subprocess.run([sys.executable, "-X", "utf8", str(FETCH), "--no-resume"],
                           cwd=str(FETCH.parents[2]), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT_SEC)
        rc, tail = r.returncode, (r.stdout or "")[-2000:] + (r.stderr or "")[-2000:]
    except subprocess.TimeoutExpired:
        rc, tail = -1, f"(timeout {TIMEOUT_SEC}s)"
    log(f"取得終了: rc={rc}", logfile)
    for line in tail.splitlines()[-12:]:
        log(f"  | {line}", logfile)

    after_n = dump_count()
    after_inv = invariant_counts()
    problems = []
    if rc != 0:
        problems.append(f"取得が異常終了 (rc={rc})")
    if after_n < MIN_DUMPS:
        problems.append(f"dump が {after_n}件しかない (最低 {MIN_DUMPS})")
    if after_n < before_n:
        problems.append(f"dump が減った ({before_n} → {after_n})")
    for k, expect in INVARIANTS.items():
        if after_inv.get(k) != expect:
            problems.append(f"invariant {k} が {before_inv.get(k)} → {after_inv.get(k)} (期待 {expect})")

    if problems:
        for p in problems:
            log(f"⚠️要対応: {p}", logfile)
        _restore(dumps_bak, db_bak, logfile)
        return 1

    log(f"正常: dump {before_n} → {after_n}件 / invariant 不変 {after_inv}", logfile)
    log(f"退避は {dumps_bak.name} に残してある (問題なければ手で消してよい)", logfile)
    return 0


def install() -> int:
    """毎月1日 04:00 に走る schtasks を登録する (既存があれば上書き)."""
    cmd = ["schtasks", "/create", "/f", "/tn", "iMakCatalog_OpcgDumpRefresh",
           "/tr", f'"{sys.executable}" -X utf8 "{Path(__file__).resolve()}"',
           "/sc", "monthly", "/d", "1", "/st", "04:00"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or "") + (r.stderr or ""), flush=True)
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="取得せず今の鮮度と invariant だけ見る")
    ap.add_argument("--install", action="store_true", help="月次タスクとして登録する")
    a = ap.parse_args()
    if a.install:
        return install()
    if a.check:
        return check()
    return refresh()


if __name__ == "__main__":
    raise SystemExit(main())
