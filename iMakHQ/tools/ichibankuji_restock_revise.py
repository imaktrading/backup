# -*- coding: utf-8 -*-
"""一番くじ RESTOCK内容刷新 — Add CSV → Revise CSV 変換(後処理)。

psa_restock_revise_csv.py と同型の薄い後処理。新規生成器(ichibankuji_to_csv)が吐く Add 形式の
行を Revise 化するだけ(新規生成コードには触れない=drift無し)。一番くじは PSA と違い cert# が
無いので、行の **CustomLabel(=mercari SKU)→ itemID** で逆引きする点だけ異なる。

変換ルール(proven, psa と同一):
  - *Action 列の値 → "Revise"
  - ItemID 列を Action 直後に挿入(CustomLabel → itemID 逆引き)
  - *Quantity → "1"(在庫復活)
  - PicURL 列を削除(= 既存eBay画像を維持。空欄送信で画像消失を防ぐ)
  - ScheduleTime 列を削除(Revise は予約不要)
  - 業務Profile(Shipping/Return/Payment)列は残す(Revise挫折=Profile空欄bug 回避)
  - Title/Item Specifics/Description/StartPrice は Add のまま = 新コア刷新値

itemID が引けない行は fail-closed で skip。add_rows_to_revise は純関数(test可)。
"""
import csv

_ACTION_PREFIX = "*Action"
_SKU_COL = "CustomLabel"
_DROP_COLS = ("PicURL", "ScheduleTime")


def add_rows_to_revise(add_header, add_rows, sku_to_itemid):
    """Add CSV(header+rows2d) → Revise(header+rows2d)。純関数。

    Returns: (revise_header, revise_rows, skipped)  skipped=[(sku, 理由)]。
    """
    def _find(pred):
        for i, h in enumerate(add_header):
            if pred(h):
                return i
        return None

    action_i = _find(lambda h: h.startswith(_ACTION_PREFIX))
    sku_i = add_header.index(_SKU_COL) if _SKU_COL in add_header else None
    qty_i = add_header.index("*Quantity") if "*Quantity" in add_header else None
    drop_idx = {add_header.index(c) for c in _DROP_COLS if c in add_header}

    if action_i is None or sku_i is None:
        raise ValueError("Add CSV に *Action / CustomLabel 列が無い(format不一致)")

    # Revise header = Add から drop列を除き、Action の直後に ItemID を挿入
    revise_header = []
    for i, h in enumerate(add_header):
        if i in drop_idx:
            continue
        revise_header.append(h)
        if i == action_i:
            revise_header.append("ItemID")

    revise_rows = []
    skipped = []
    for row in add_rows:
        sku = (row[sku_i] if sku_i < len(row) else "").strip()
        itemid = (sku_to_itemid.get(sku) or "").strip()
        if not itemid:
            skipped.append((sku, "itemID未解決→Revise不可"))
            continue
        out = []
        for i, h in enumerate(add_header):
            if i in drop_idx:
                continue
            val = row[i] if i < len(row) else ""
            if i == action_i:
                val = "Revise"
            elif i == qty_i:
                val = "1"
            out.append(val)
            if i == action_i:
                out.append(itemid)     # ItemID を Action 直後に
        revise_rows.append(out)
    return revise_header, revise_rows, skipped


def convert_file(add_csv_path, out_path, sku_to_itemid):
    """Add CSV ファイル → Revise CSV ファイル。戻り (件数, skipped)。"""
    with open(add_csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0, []
    header, body = rows[0], rows[1:]
    rh, rr, skipped = add_rows_to_revise(header, body, sku_to_itemid)
    # eBay FileExchange 規約: QUOTE_NONNUMERIC + utf-8(BOMなし)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(rh)
        for r in rr:
            w.writerow(r)
    return len(rr), skipped
