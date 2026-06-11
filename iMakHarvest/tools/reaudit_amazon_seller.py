"""中間スプシ amazon_gshock タブを merchantId で再精査し Q列 FLG を是正.

2026-06-12 user 指示:
  - そもそもの抽出は「Amazon.co.jp 直販のみ」が正 (= 国内 third-party / Amazon US は除外)。
  - selenium 抽出時の FBA 誤検出で 国内 third-party 32 件が混入。
  - 旧 flag_amazon_us_in_sheet.py は非直販を一律 'AMAZON_US' と誤ラベル。
  - → 全 376 行を merchantId="AN1VRQENFRJN5" で再判定し Q列を是正する。

判定:
  - merchantId 直販 検出 → 直販 (= keep)。 古い誤 FLG があれば クリア。
  - 非直販 → 確認のため 1 回 再 fetch (= buybox rotation/transient 対策)。
    2 回とも非直販 → Q='非直販' (= 除外マーク)、 merchantId を記録。
    確認で直販に変われば 直販扱い (= rotation で今は直販)。
  - fetch 失敗/captcha → Q 変更せず record (= 後追い対象)。

buybox rotation 注意:
  Amazon の buybox 出品者は時間で入れ替わる。 本 audit は実行時点の snapshot。
  flickering (= 直販/非直販を行き来) する品は sourcing 信頼性が低い → 別途 user 目視。

実行:
  python tools/reaudit_amazon_seller.py            # 本書込
  python tools/reaudit_amazon_seller.py --dry-run  # 書込なし
  python tools/reaudit_amazon_seller.py --limit 10 # 先頭 10 行のみ
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers import amazon_search_http  # noqa: E402
from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: E402

TAB_NAME = "amazon_gshock"
COL_URL = 1     # A
COL_FLG = 17    # Q (= 既存 mercari format の FLG 列)
FLG_EXCLUDE = "非直販"   # 非直販 (= 国内 third-party / Amazon US) 除外マーク

RATE_MIN = 2.0
RATE_MAX = 3.5

OUT = ROOT / "debug" / "reaudit_amazon_seller_result.json"

_MERCHANT_RE = re.compile(r'"merchantId":"([A-Z0-9]+)"')


def _col_to_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def parse_asin_from_url(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", url, re.IGNORECASE)
    return m.group(1).upper() if m else None


def _classify(session, asin: str) -> dict:
    """1 fetch で 直販判定 + merchantId 抽出."""
    text, captcha = amazon_search_http.fetch_detail_page(session, asin)
    if captcha:
        return {"ok": False, "captcha": True, "direct": False, "merchant_ids": []}
    if not text:
        return {"ok": False, "captcha": False, "direct": False, "merchant_ids": []}
    direct = amazon_search_http.SELLER_AMAZON_PRIMARY_MARKER in text
    mids = sorted(set(_MERCHANT_RE.findall(text)))
    return {"ok": True, "captcha": False, "direct": direct, "merchant_ids": mids}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    print(f"[reaudit] open sheet '{TAB_NAME}' (dry_run={args.dry_run})", flush=True)
    sh = open_seller_staging_sheet()
    ws = sh.worksheet(TAB_NAME)
    vals = ws.get_all_values()
    print(f"[reaudit] total rows: {len(vals)}", flush=True)

    targets: list[dict] = []
    for row_idx, row in enumerate(vals[1:], start=2):
        if not row:
            continue
        url = (row[COL_URL - 1] or "").strip() if len(row) >= COL_URL else ""
        asin = parse_asin_from_url(url)
        if not asin:
            continue
        cur_q = (row[COL_FLG - 1] or "").strip() if len(row) >= COL_FLG else ""
        targets.append({"row_idx": row_idx, "url": url, "asin": asin, "cur_q": cur_q})

    if args.limit:
        targets = targets[: args.limit]
    print(f"[reaudit] ASIN targets: {len(targets)}", flush=True)

    session = amazon_search_http.create_session()
    direct_rows: list[dict] = []
    nondirect_rows: list[dict] = []
    failed_rows: list[dict] = []
    captcha_hit = False

    for i, t in enumerate(targets, start=1):
        if i % 20 == 0:
            print(
                f"[reaudit] {i}/{len(targets)} "
                f"(direct={len(direct_rows)} nondirect={len(nondirect_rows)} fail={len(failed_rows)})",
                flush=True,
            )
        r = _classify(session, t["asin"])
        if r["captcha"]:
            captcha_hit = True
            print("[reaudit] CAPTCHA 検出、 中断", flush=True)
            break
        if not r["ok"]:
            failed_rows.append({**t, "reason": "fetch_failed"})
            time.sleep(random.uniform(RATE_MIN, RATE_MAX))
            continue

        if r["direct"]:
            direct_rows.append({**t, "merchant_ids": r["merchant_ids"]})
        else:
            # 非直販 → 確認 1 回 (= transient/rotation 対策)
            time.sleep(random.uniform(RATE_MIN, RATE_MAX))
            r2 = _classify(session, t["asin"])
            if r2["captcha"]:
                captcha_hit = True
                print("[reaudit] CAPTCHA 検出 (確認時)、 中断", flush=True)
                break
            if r2["ok"] and r2["direct"]:
                # 確認で直販に変化 (= rotation)
                direct_rows.append({**t, "merchant_ids": r2["merchant_ids"], "flicker": True})
            else:
                mids = r2["merchant_ids"] if r2["ok"] else r["merchant_ids"]
                nondirect_rows.append({**t, "merchant_ids": mids})
        time.sleep(random.uniform(RATE_MIN, RATE_MAX))

    # 書込計画: 非直販 → Q=FLG_EXCLUDE / 直販 → Q クリア (= 古い誤 flag 是正)
    writes: list[dict] = []
    for d in direct_rows:
        if d["cur_q"]:  # 古い誤 FLG があれば クリア
            writes.append({"row": d["row_idx"], "asin": d["asin"], "new_q": "", "old_q": d["cur_q"]})
    for n in nondirect_rows:
        if n["cur_q"] != FLG_EXCLUDE:
            writes.append({"row": n["row_idx"], "asin": n["asin"], "new_q": FLG_EXCLUDE, "old_q": n["cur_q"]})

    print(f"\n[reaudit] === 判定 ===", flush=True)
    print(f"  direct(keep)   : {len(direct_rows)} (flicker={sum(1 for d in direct_rows if d.get('flicker'))})", flush=True)
    print(f"  non-direct(除外): {len(nondirect_rows)}", flush=True)
    print(f"  fetch失敗       : {len(failed_rows)}", flush=True)
    print(f"  Q列 書込予定     : {len(writes)} (= 誤flag是正 + 除外マーク)", flush=True)

    write_done = 0
    if writes and not args.dry_run:
        for w in writes:
            try:
                ws.update_cell(w["row"], COL_FLG, w["new_q"])
                write_done += 1
                tag = "CLEAR" if w["new_q"] == "" else w["new_q"]
                print(f"  row {w['row']} asin={w['asin']}: Q '{w['old_q']}'→'{tag}'", flush=True)
                time.sleep(0.5)
            except Exception as e:
                print(f"  WARN row {w['row']} 書込失敗: {e!r}", flush=True)

    out = {
        "timestamp": datetime.now().isoformat(),
        "tab": TAB_NAME,
        "dry_run": args.dry_run,
        "asin_targets": len(targets),
        "direct_count": len(direct_rows),
        "flicker_count": sum(1 for d in direct_rows if d.get("flicker")),
        "nondirect_count": len(nondirect_rows),
        "fetch_failed_count": len(failed_rows),
        "captcha_hit": captcha_hit,
        "writes_planned": len(writes),
        "writes_done": write_done,
        "nondirect_rows": [
            {"row": n["row_idx"], "asin": n["asin"], "merchant_ids": n["merchant_ids"]}
            for n in nondirect_rows
        ],
        "flicker_rows": [
            {"row": d["row_idx"], "asin": d["asin"], "merchant_ids": d.get("merchant_ids", [])}
            for d in direct_rows if d.get("flicker")
        ],
        "cleared_wrong_flag_rows": [
            {"row": w["row"], "asin": w["asin"], "old_q": w["old_q"]}
            for w in writes if w["new_q"] == ""
        ],
        "fetch_failed_rows": [{"row": f["row_idx"], "asin": f["asin"]} for f in failed_rows],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[reaudit] summary written: {OUT}", flush=True)
    print(json.dumps({k: v for k, v in out.items() if not isinstance(v, list)},
                     ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
