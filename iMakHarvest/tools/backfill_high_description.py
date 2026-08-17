"""backfill_high_description - 本番 HIGH/LOW の H列 (商品説明) 空欄を中間スプシから埋める.

2026-08-17 新設。 中間スプシ `mercari_<label>` の H列が空欄のまま HIGH にコピーされたため、
同じ item_id の行を突合して H列だけを書き戻す。

- 突合キー: A列 URL から取った item_id (m\\d+)。 URL 文字列そのものでは合わない場合があるため。
- 書込むのは **H列が空欄の行だけ**。 既に何か入っている行は触らない。
- 中間スプシに説明が無い item は 要対応として一覧表示する (黙って飛ばさない)。

使い方:
  python tools/backfill_high_description.py --label porter --dry-run
  python tools/backfill_high_description.py --label porter
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import sheet_writer  # noqa: E402
from sheet_writer_amazon import COL_DESCRIPTION, COL_URL  # noqa: E402
from sheet_writer_mercari_search import build_mercari_tab_name, dedupe_key  # noqa: E402


def _log(m: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def load_staging_descriptions(label: str) -> dict[str, str]:
    """中間スプシ `mercari_<label>` から {item_id: description} を作る."""
    from sheet_writer_mercari_seller import open_seller_staging_sheet  # noqa: PLC0415

    ws = open_seller_staging_sheet().worksheet(build_mercari_tab_name(label))
    out: dict[str, str] = {}
    for row in ws.get_all_values()[1:]:
        url = (row[COL_URL - 1] if len(row) >= COL_URL else "").strip()
        desc = (row[COL_DESCRIPTION - 1] if len(row) >= COL_DESCRIPTION else "").strip()
        key = dedupe_key(url)
        if key and desc:
            out[key] = desc
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="porter", help="中間スプシ tab (= mercari_<label>)")
    ap.add_argument("--sheet-id", default=sheet_writer.HIGH_SHEET_ID,
                    help="書込先 spreadsheet ID (既定 HIGH)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    desc_map = load_staging_descriptions(args.label)
    _log(f"中間スプシ mercari_{args.label}: 説明あり {len(desc_map)} 件")
    if not desc_map:
        _log("説明が1件も無い → 何もしない")
        return 0

    sh = sheet_writer.open_sheet_by_id(args.sheet_id)
    ws = sheet_writer.get_listings_worksheet(sh)
    values = ws.get_all_values()
    _log(f"書込先: {ws.title} ({len(values) - 1}行) / H列見出し="
         f"{values[0][COL_DESCRIPTION - 1] if values else '?'}")

    updates: list[dict] = []
    missing: list[tuple[int, str]] = []  # 該当行だが中間スプシに説明が無い
    already: int = 0
    for i, row in enumerate(values[1:], start=2):
        url = (row[COL_URL - 1] if len(row) >= COL_URL else "").strip()
        key = dedupe_key(url)
        if not key or not key.startswith("m"):
            continue
        desc_now = (row[COL_DESCRIPTION - 1] if len(row) >= COL_DESCRIPTION else "").strip()
        if desc_now:
            if key in desc_map:
                already += 1
            continue
        if key in desc_map:
            updates.append({"range": f"H{i}", "values": [[desc_map[key]]]})
        else:
            missing.append((i, url))

    _log(f"H列 空欄で埋められる行: {len(updates)} / 既に入っている行: {already} / "
         f"空欄だが中間スプシに説明無し: {len(missing)}")
    for u in updates[:5]:
        _log(f"  {u['range']} <- {u['values'][0][0][:40]}...")
    if args.dry_run:
        _log("dry-run → 書込なし")
        if missing:
            _log("参考: 説明が用意できない行 (メルカリ以外 or 未収集)")
            for r, url in missing[:10]:
                _log(f"    row{r} {url}")
        return 0
    if not updates:
        return 0

    ws.batch_update(updates, value_input_option="USER_ENTERED")
    _log(f"完了: H列 {len(updates)}行を更新")
    if missing:
        _log(f"⚠️要対応: 説明を用意できなかった {len(missing)}行")
        for r, url in missing[:20]:
            _log(f"    row{r} {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
