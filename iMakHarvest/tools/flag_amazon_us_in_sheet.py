"""中間スプシ amazon_gshock タブの Amazon US 商品に Q 列 FLG=AMAZON_US 立て.

2026-06-11 user 指示: Amazon US (= merchantId ≠ AN1VRQENFRJN5) を Q 列 FLG マークで識別。

仕様:
  - 対象: 中間スプシ `amazon_gshock` タブの全行 (= 376 件想定)
  - 各 ASIN を HTTP detail fetch で merchantId 確認
  - merchantId が 'AN1VRQENFRJN5' (= Amazon.co.jp) でない → Q 列に 'AMAZON_US' 書込
  - 既存 Q 列値あり行は skip (= 上書き禁止、 安全)
  - rate limit 2-3s (= Amazon ブロック対策)

実行:
  python tools/flag_amazon_us_in_sheet.py

出力:
  - 進捗 console log
  - debug/flag_amazon_us_result.json (= 検査結果 dump)
"""
from __future__ import annotations

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
from sheet_writer_amazon import dedupe_key  # noqa: E402
from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: E402

TAB_NAME = "amazon_gshock"
COL_URL = 1     # A
COL_FLG = 17    # Q (= 既存 mercari format)
FLG_VALUE = "AMAZON_US"

RATE_MIN = 2.0
RATE_MAX = 3.0

OUT = ROOT / "debug" / "flag_amazon_us_result.json"


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


def main() -> int:
    print(f"[flag] open sheet '{TAB_NAME}'", flush=True)
    sh = open_seller_staging_sheet()
    ws = sh.worksheet(TAB_NAME)
    vals = ws.get_all_values()
    print(f"[flag] total rows: {len(vals)} (= header + data)", flush=True)

    # 各 row の ASIN を取り、 Q 列既存値を確認
    targets: list[dict] = []
    for row_idx, row in enumerate(vals[1:], start=2):  # row 2 から
        if not row:
            continue
        url = (row[COL_URL - 1] or "").strip() if len(row) >= COL_URL else ""
        if not url:
            continue
        asin = parse_asin_from_url(url)
        if not asin:
            continue
        existing_q = (row[COL_FLG - 1] or "").strip() if len(row) >= COL_FLG else ""
        targets.append({
            "row_idx": row_idx,
            "url": url,
            "asin": asin,
            "existing_q": existing_q,
        })
    print(f"[flag] targets: {len(targets)}", flush=True)

    # 既存 Q 列値ありの行は skip
    skip_existing = [t for t in targets if t["existing_q"]]
    to_check = [t for t in targets if not t["existing_q"]]
    print(f"[flag] skip existing Q value: {len(skip_existing)} rows", flush=True)
    print(f"[flag] to check: {len(to_check)} rows", flush=True)

    # 各 ASIN を HTTP detail で merchantId 検証
    session = amazon_search_http.create_session()
    flagged: list[dict] = []
    kept_jp: list[dict] = []
    fetch_failed: list[dict] = []
    captcha_hit = False
    flg_marker = amazon_search_http.SELLER_AMAZON_PRIMARY_MARKER

    for i, t in enumerate(to_check, start=1):
        if i % 20 == 0:
            print(
                f"[flag] {i}/{len(to_check)} (flagged={len(flagged)} kept={len(kept_jp)} fail={len(fetch_failed)})",
                flush=True,
            )
        text, captcha = amazon_search_http.fetch_detail_page(session, t["asin"])
        if captcha:
            captcha_hit = True
            print("[flag] CAPTCHA 検出、 中断", flush=True)
            break
        if not text:
            fetch_failed.append(t)
        elif flg_marker in text:
            kept_jp.append(t)
        else:
            t["reason"] = "merchantId_not_amazon_jp"
            flagged.append(t)
        time.sleep(random.uniform(RATE_MIN, RATE_MAX))

    # スプシ書込 (= flagged 行の Q 列に AMAZON_US)
    print(f"[flag] flagged total: {len(flagged)} → スプシ書込", flush=True)
    write_count = 0
    if flagged:
        col_letter = _col_to_letter(COL_FLG)
        for f in flagged:
            try:
                ws.update_cell(f["row_idx"], COL_FLG, FLG_VALUE)
                write_count += 1
                print(
                    f"  row {f['row_idx']} asin={f['asin']}: Q={FLG_VALUE} 書込",
                    flush=True,
                )
                time.sleep(0.5)  # API rate limit
            except Exception as e:
                print(f"  WARN row {f['row_idx']} 書込失敗: {e!r}", flush=True)

    out = {
        "timestamp": datetime.now().isoformat(),
        "tab": TAB_NAME,
        "total_targets": len(targets),
        "skip_existing": len(skip_existing),
        "checked": len(kept_jp) + len(flagged) + len(fetch_failed),
        "kept_jp_count": len(kept_jp),
        "flagged_count": len(flagged),
        "written_to_sheet": write_count,
        "fetch_failed_count": len(fetch_failed),
        "captcha_hit": captcha_hit,
        "flagged_asins": [{"asin": f["asin"], "row": f["row_idx"]} for f in flagged],
        "fetch_failed_asins": [{"asin": f["asin"], "row": f["row_idx"]} for f in fetch_failed],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[flag] === summary ===", flush=True)
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
    print(f"[flag] wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
