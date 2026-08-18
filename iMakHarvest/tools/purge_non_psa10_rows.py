"""purge_non_psa10_rows - 中間スプシから PSA10 でない行を落とす.

2026-08-18 (user 指摘「PSA9 や BGS9.5、ARS、CCG が混じっているね」)。
cert が読めなかった行を グレードを見ずに入れていたため、 PSA9 / 他社鑑定 / 生カードが並んだ。

- 判定は `scrapers.psa_grade_gate.looks_like_psa10` (タイトルのみ。 スプシにラベルは無い)
- **I列に cert がある行は触らない**。 Vision がラベルを読めている = 別の根拠があるため
- 既定は dry-run。 消す時は --apply

使い方:
  python tools/purge_non_psa10_rows.py
  python tools/purge_non_psa10_rows.py --apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.psa_grade_gate import looks_like_psa10  # noqa: E402
from sheet_writer_amazon import COL_CERT, COL_TITLE  # noqa: E402


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="mercari_psa10")
    ap.add_argument("--apply", action="store_true", help="実際に削除する")
    args = ap.parse_args(argv)

    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415

    sh = open_seller_staging_sheet()
    total = 0
    for ws in sh.worksheets():
        if not (ws.title or "").startswith(args.prefix):
            continue
        values = ws.get_all_values()
        drop = []
        for i, r in enumerate(values[1:], start=2):
            cert = (r[COL_CERT - 1] or "").strip() if len(r) >= COL_CERT else ""
            if cert:
                continue  # cert がある行は Vision がラベルを読めている → 触らない
            title = (r[COL_TITLE - 1] or "").strip() if len(r) >= COL_TITLE else ""
            if not looks_like_psa10(title=title):
                drop.append((i, title))
        if not drop:
            continue
        total += len(drop)
        _log(f"{ws.title}: PSA10 と確認できない行 {len(drop)} / 全 {len(values) - 1}")
        for _, t in drop[:5]:
            _log(f"    {t[:52]}")
        if args.apply:
            for i, _ in sorted(drop, reverse=True):
                ws.delete_rows(i)
            _log(f"  → {len(drop)} 行を削除")
    _log(f"合計 {total} 行" + ("" if args.apply else " (dry-run。 消すには --apply)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
