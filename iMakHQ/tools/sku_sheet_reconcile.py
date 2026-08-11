#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SKU 詳細シート ↔ eBay Variation 突合 dry-run レポート (2026-08-11)。

回答書: `2026-08-11_inventory_sku_sheet_duplicate_rows_conflict_response.md`

処理ルール (12 組も残り 44 組も同じ、例外なし):
  1. listing_id ごとに GetItem して `SKU UUID → (Sizes, Color)` の正解表を作る
  2. シートの各行の UUID を引く
       - 一致 → 残す
       - 不一致 (表記が違う) → その行が古い。廃止候補
       - eBay に無い UUID → 出品側から消えた variation。廃止候補
  3. 同一 UUID の行が 2 つあり両方一致してしまう場合のみ、`updated_at`
     (L 列 = 自動 CHK 日) が新しい方を残す

**dry-run only**。シートは 1 セルも変更しない。判定結果を JSON + text で出す。
実削除フェーズは別ツール (窓口 GO 後に起票)。

使い方:
    python sku_sheet_reconcile.py                    # 本番: sheet 読 + eBay fetch
    python sku_sheet_reconcile.py --fixture <path>   # sheet 読 + fixture (テスト/検証用)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

# ============================================================================
# SKU 詳細シート 列マッピング (A-L, 0-based)
#   実装: iMakeBayAPI/inventory_monitor/sheet_updater.py:8-20 と同じ
# ============================================================================
SKU_COL_TAIO_YOU = 0     # A: 対処要 (TRUE/FALSE)
SKU_COL_TAIO_ZUMI = 1    # B: 対処済 (TRUE/FALSE)
SKU_COL_TAIO_DATE = 2    # C: 対処日
SKU_COL_LISTING_ID = 3   # D: listing ID
SKU_COL_TITLE = 4        # E: title
SKU_COL_UUID = 5         # F: eBay SKU ID (= UUID)
SKU_COL_SIZE = 6         # G: サイズ
SKU_COL_COLOR = 7        # H: 色
SKU_COL_STOCK = 8        # I: 仕入元在庫 (◎ / ✕)
SKU_COL_PRICE = 9        # J: 仕入元価格
SKU_COL_QTY = 10         # K: eBay 現 Qty
SKU_COL_CHK_DATE = 11    # L: 自動 CHK 日 (= updated_at 相当)


# ============================================================================
# 純関数: reconcile (I/O 依存無し、test 可)
# ============================================================================
_UUID_RE = re.compile(r"^[0-9a-f]{6,}$", re.IGNORECASE)


def _norm_uuid(s: str) -> str:
    """UUID を突合キーに正規化 (前後空白除去 + 小文字化)。空 or 明らかに非 UUID は "" を返す。"""
    s = (str(s) if s is not None else "").strip().lower()
    if not s:
        return ""
    # ハイフン付き full UUID / 8桁短縮 の両方許容 (SKU_UUID 実データは 8 桁短縮)
    if _UUID_RE.match(s.replace("-", "")):
        return s
    return ""


def _norm_str(s: str) -> str:
    """size / color の突合キー。前後空白と NBSP を除いて lower。"""
    return (str(s) if s is not None else "").replace(" ", "").strip().lower()


def _parse_updated_at(s: str) -> tuple:
    """L 列を並べ替え key に変換。空/不明は最小値を返す (=より古い扱い)。"""
    s = (s or "").strip()
    if not s:
        return (0,)
    # 実データ形式は 'YYYY/MM/DD' or 'YYYY/MM/DD HH:MM' 等
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return (1, datetime.strptime(s, fmt).timestamp())
        except ValueError:
            continue
    return (0,)


def reconcile_rows(sheet_rows: Iterable[list],
                   ebay_truth: dict) -> dict:
    """SKU 詳細シート rows と eBay 真実表 (listing_id → {uuid: (sizes, color)}) を突合。

    Args:
        sheet_rows: 2 次元配列 (SKU 詳細タブの全行、ヘッダ除いた data 行)。
            各行は少なくとも列 A-L (index 0-11) を持つ。短い行は無視する。
        ebay_truth: {listing_id (str): {uuid (str, 正規化済): (sizes, color)}}
            sizes/color も呼出側で _norm_str() 済であること。

    Returns:
        {
            "decisions": [
                {
                    "row_idx": int,          # 1-based (シート上の行番号)
                    "listing_id": str,
                    "uuid": str,
                    "sheet_size": str,
                    "sheet_color": str,
                    "decision": "keep" | "retire_mismatch" | "retire_orphan"
                                | "retire_dup_older",
                    "reason": str,           # 判定根拠 (人が読む文言)
                    "ebay_size": str,        # 対比用 (取れれば)
                    "ebay_color": str,
                    "updated_at": str,       # L 列の値 (raw)
                },
                ...
            ],
            "summary": {
                "total": int,
                "keep": int,
                "retire_mismatch": int,
                "retire_orphan": int,
                "retire_dup_older": int,
                "listings_examined": int,
            },
        }
    """
    # 1) 各行を先に「listing 内で UUID が一致するか」で分類
    per_listing: dict = defaultdict(list)  # listing_id → [row_info]
    for idx, row in enumerate(sheet_rows, start=2):  # 2 = header 分の +1
        if len(row) <= SKU_COL_CHK_DATE:
            continue
        listing_id = str(row[SKU_COL_LISTING_ID] or "").strip()
        uuid_raw = row[SKU_COL_UUID]
        uuid = _norm_uuid(uuid_raw)
        if not listing_id or not uuid:
            continue
        per_listing[listing_id].append({
            "row_idx": idx,
            "listing_id": listing_id,
            "uuid": uuid,
            "sheet_size": row[SKU_COL_SIZE] or "",
            "sheet_color": row[SKU_COL_COLOR] or "",
            "updated_at": row[SKU_COL_CHK_DATE] or "",
        })

    decisions = []
    for listing_id, rows in per_listing.items():
        truth = ebay_truth.get(listing_id, {})
        # 同一 UUID の行を束ねてから判定 (dup older の判定に必要)
        by_uuid = defaultdict(list)
        for r in rows:
            by_uuid[r["uuid"]].append(r)

        for uuid, group in by_uuid.items():
            # ebay 真実側 lookup
            e = truth.get(uuid)
            for r in group:
                ebay_size = _norm_str(e[0]) if e else ""
                ebay_color = _norm_str(e[1]) if e else ""
                sheet_size = _norm_str(r["sheet_size"])
                sheet_color = _norm_str(r["sheet_color"])

                if e is None:
                    r["decision"] = "retire_orphan"
                    r["reason"] = (
                        f"eBay に UUID {uuid} が存在しない = 出品側から消えた variation"
                    )
                elif sheet_size != ebay_size or sheet_color != ebay_color:
                    r["decision"] = "retire_mismatch"
                    r["reason"] = (
                        f"表記不一致: sheet=(size='{r['sheet_size']}', "
                        f"color='{r['sheet_color']}') vs eBay=(size='{e[0]}', "
                        f"color='{e[1]}')"
                    )
                else:
                    r["decision"] = "keep"
                    r["reason"] = "UUID 一致 + 表記一致"
                r["ebay_size"] = e[0] if e else ""
                r["ebay_color"] = e[1] if e else ""

            # 「同一 UUID の行が 2 つあり両方一致」ケース
            keepers = [r for r in group if r["decision"] == "keep"]
            if len(keepers) > 1:
                # updated_at 新しい方を残す
                keepers.sort(key=lambda r: _parse_updated_at(r["updated_at"]), reverse=True)
                for older in keepers[1:]:
                    older["decision"] = "retire_dup_older"
                    older["reason"] = (
                        f"同一 UUID {uuid} が両方一致で重複 → "
                        f"updated_at が古い側 ({older['updated_at']}) を廃止候補"
                    )

            decisions.extend(group)

    # サマリ
    sums = {"total": len(decisions), "keep": 0, "retire_mismatch": 0,
            "retire_orphan": 0, "retire_dup_older": 0,
            "listings_examined": len(per_listing)}
    for d in decisions:
        sums[d["decision"]] = sums.get(d["decision"], 0) + 1

    # row_idx 順に並べて出す (人が読みやすい)
    decisions.sort(key=lambda d: (d["listing_id"], d["row_idx"]))
    return {"decisions": decisions, "summary": sums}


# ============================================================================
# I/O レイヤー (sheet 読取 / eBay GetItem)
# ============================================================================
def load_sheet_rows_from_sku_tab():
    """SKU 詳細タブの全行 (header 除く) を取得。"""
    sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI\inventory_monitor")
    import sheet_updater as SU
    sh = SU.open_sheet()
    ws = SU.get_sku_worksheet(sh)
    rows = ws.get_all_values()
    return rows[1:] if rows else []


def parse_variation_truth_from_getitem(xml_text: str) -> dict:
    """GetItem XML → {uuid_norm: (sizes_raw, color_raw)}。純関数、test 可。"""
    truth = {}
    # <Variation>...</Variation> をブロック毎に処理
    for m in re.finditer(r"<Variation>(.*?)</Variation>", xml_text, re.DOTALL):
        block = m.group(1)
        sku_m = re.search(r"<SKU>(.*?)</SKU>", block)
        if not sku_m:
            continue
        uuid = _norm_uuid(sku_m.group(1))
        if not uuid:
            continue
        # <NameValueList><Name>Sizes</Name><Value>JP L-R</Value></NameValueList>
        specs = {}
        for nv in re.finditer(
            r"<NameValueList>\s*<Name>(.*?)</Name>\s*<Value>(.*?)</Value>\s*</NameValueList>",
            block, re.DOTALL,
        ):
            specs[nv.group(1).strip()] = nv.group(2).strip()
        # 「Sizes」名がカテゴリで違うことがあるので複数候補を試す
        size_val = specs.get("Sizes") or specs.get("Size") or specs.get("US Shoe Size") or ""
        color_val = specs.get("Color") or ""
        truth[uuid] = (size_val, color_val)
    return truth


def fetch_ebay_truth(listing_ids: Iterable[str]) -> dict:
    """listing_ids を GetItem で舐めて {listing_id: {uuid: (size, color)}} を返す。

    外部 I/O。テストからは呼ばず、fixture 経路 (--fixture) で bypass する。
    """
    sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
    import fix_de_speedpak_shipping as fx
    fx.refresh()
    tok = fx.token()

    out = {}
    for lid in listing_ids:
        try:
            xml = fx.post(
                "GetItem",
                f"<ItemID>{lid}</ItemID><DetailLevel>ReturnAll</DetailLevel>",
                tok, site="0",
            )
            out[lid] = parse_variation_truth_from_getitem(xml)
        except Exception as e:                              # noqa: BLE001
            # dry-run: 取得失敗は空 dict にして「orphan 判定」に倒す方が危険。
            # 「取得できなかった listing は判定除外」とわかる形で報告する。
            out[lid] = {"__fetch_error__": str(e)}          # type: ignore[assignment]
    return out


def _filter_fetch_errors(ebay_truth: dict) -> tuple:
    """fetch_error のあった listing を分離。判定不能として別枠で報告する。"""
    ok, fail = {}, {}
    for lid, tru in ebay_truth.items():
        if isinstance(tru, dict) and "__fetch_error__" in tru:
            fail[lid] = tru["__fetch_error__"]
        else:
            ok[lid] = tru
    return ok, fail


# ============================================================================
# レポート出力 (dry-run のみ、シート書換なし)
# ============================================================================
def render_text_report(result: dict, fetch_errors: dict) -> str:
    lines = []
    s = result["summary"]
    lines.append("=== SKU 詳細シート ↔ eBay Variation 突合 dry-run ===")
    lines.append(f"生成時刻: {datetime.now(timezone.utc).isoformat(timespec='seconds')}Z")
    lines.append(f"検査 listing 数: {s['listings_examined']}")
    lines.append(f"検査 row 数    : {s['total']}")
    lines.append("")
    lines.append(f"[判定サマリ]")
    lines.append(f"  keep              : {s['keep']}")
    lines.append(f"  retire_mismatch   : {s['retire_mismatch']}  (UUID一致 + 表記不一致 → 廃止候補)")
    lines.append(f"  retire_orphan     : {s['retire_orphan']}    (eBay に UUID 無し → 廃止候補)")
    lines.append(f"  retire_dup_older  : {s['retire_dup_older']}  (同 UUID 二重登録の古い側 → 廃止候補)")
    lines.append("")
    if fetch_errors:
        lines.append(f"⚠️ GetItem 取得失敗 {len(fetch_errors)} 件 (判定不能。対象外):")
        for lid, err in sorted(fetch_errors.items()):
            lines.append(f"  listing={lid}: {err[:100]}")
        lines.append("")

    # 廃止候補だけ詳細を出す (keep は数だけ)
    to_retire = [d for d in result["decisions"] if d["decision"].startswith("retire_")]
    if to_retire:
        lines.append(f"[廃止候補 詳細 {len(to_retire)} 件]")
        for d in to_retire:
            lines.append(
                f"  row {d['row_idx']:>5}  listing={d['listing_id']}  uuid={d['uuid']}  "
                f"→ {d['decision']}"
            )
            lines.append(f"           {d['reason']}")
    else:
        lines.append("[廃止候補] なし")
    lines.append("")
    lines.append("★シートは 1 セルも変更していません (dry-run only)。実削除は窓口 GO 後。")
    return "\n".join(lines)


def write_reports(result: dict, fetch_errors: dict, out_dir: Path) -> tuple:
    """JSON + text 両方を書く。上書きせず timestamp 付きで残す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"sku_reconcile_dryrun_{stamp}.json"
    txt_path = out_dir / f"sku_reconcile_dryrun_{stamp}.txt"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"result": result, "fetch_errors": fetch_errors},
                  f, ensure_ascii=False, indent=2)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(render_text_report(result, fetch_errors))
    return json_path, txt_path


# ============================================================================
# CLI
# ============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixture", type=str, default=None,
                    help="eBay 真実表を fixture JSON から読む "
                         "({listing_id: {uuid: [size, color]}})")
    ap.add_argument("--sheet-fixture", type=str, default=None,
                    help="SKU 詳細タブ rows を fixture JSON から読む "
                         "(2次元配列, header 除)")
    ap.add_argument("--out-dir", type=str,
                    default=r"C:\dev\iMak_data\hq\reports\sku_reconcile")
    args = ap.parse_args(argv)

    # sheet
    if args.sheet_fixture:
        with open(args.sheet_fixture, "r", encoding="utf-8") as f:
            sheet_rows = json.load(f)
    else:
        sheet_rows = load_sheet_rows_from_sku_tab()

    # 検査対象 listing_id を集める
    listing_ids = set()
    for r in sheet_rows:
        if len(r) > SKU_COL_LISTING_ID:
            lid = str(r[SKU_COL_LISTING_ID] or "").strip()
            if lid:
                listing_ids.add(lid)

    # eBay truth
    if args.fixture:
        with open(args.fixture, "r", encoding="utf-8") as f:
            raw = json.load(f)
        ebay_truth = {
            lid: {_norm_uuid(u): tuple(v) for u, v in tru.items()}
            for lid, tru in raw.items()
        }
        fetch_errors = {}
    else:
        raw = fetch_ebay_truth(sorted(listing_ids))
        ok, fetch_errors = _filter_fetch_errors(raw)
        ebay_truth = ok

    result = reconcile_rows(sheet_rows, ebay_truth)
    json_path, txt_path = write_reports(result, fetch_errors, Path(args.out_dir))
    print(f"レポート:")
    print(f"  {txt_path}")
    print(f"  {json_path}")
    print()
    print(render_text_report(result, fetch_errors))


if __name__ == "__main__":
    main()
