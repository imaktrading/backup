# -*- coding: utf-8 -*-
"""PSA再仕入れ RESTOCK — Add CSV → Revise CSV 変換(後処理)。

設計: 2026-06-17_psa_restock_pipeline_design.md (B)。CSV生成は新規出品と完全同一(psa_to_csv)に
保ち、その Add CSV を **Revise 化するだけ** の薄い後処理。新規生成コードには一切触れない
(= 新規と drift しない・本番リスク無し)。

変換ルール(RESTOCK = 既存出品を itemID維持で復活+刷新):
  - *Action 列の値 → "Revise"
  - ItemID 列を追加(cert# → itemID。商品管理シート I列=cert / B列=itemID の逆引き)
  - *Quantity → "1"(在庫復活)
  - PicURL 列を削除(= 既存eBay画像を維持。空欄で送ると画像消失するため列ごと落とす)
  - ScheduleTime 列を削除(Revise は予約不要)
  - 業務ポリシー(Shipping/Return/Payment Profile)列は残す(過去の「Revise挫折=Profile空欄bug」回避)
  - その他 Title/Item Specifics/Description/StartPrice は Add のまま = 新コアで刷新済の値

itemID が引けない行は Revise できない → 出力せず skipped に返す(fail-closed)。
add_rows_to_revise は純関数(test可)。I/O(CSV読書・商品管理シート)は別関数。
"""
import csv

_ACTION_PREFIX = "*Action"
_CERT_COL = "CDA:Certification Number - (ID: 27503)"
_DROP_COLS = ("PicURL", "ScheduleTime")


def add_rows_to_revise(add_header, add_rows, cert_to_itemid):
    """Add CSV(header+rows) → Revise CSV(header+rows)。純関数。

    Returns: (revise_header, revise_rows, skipped)  skipped=[(cert, 理由)]。
    """
    # 列 index
    def _find(pred):
        for i, h in enumerate(add_header):
            if pred(h):
                return i
        return None
    action_i = _find(lambda h: h.startswith(_ACTION_PREFIX))
    cert_i = add_header.index(_CERT_COL) if _CERT_COL in add_header else None
    qty_i = add_header.index("*Quantity") if "*Quantity" in add_header else None
    drop_idx = {add_header.index(c) for c in _DROP_COLS if c in add_header}

    if action_i is None or cert_i is None:
        raise ValueError("Add CSV に *Action / CDA:Certification Number 列が無い(format不一致)")

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
        cert = (row[cert_i] if cert_i < len(row) else "").strip()
        itemid = cert_to_itemid.get(cert)
        if not itemid:
            skipped.append((cert, "itemID未解決(商品管理シートに無い)→Revise不可"))
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


def _valid_cert_itemid(cert, itemid):
    """cert=PSA cert(数字8-9桁) / itemID=eBay itemID(数字11-12桁) の形式検証。

    商品管理シートは多カテゴリ(TCG/Tシャツ/G-shock等)混在で、非TCG行は I列がcertでない
    (= 商品名や別IDが入る)。形式で弾かないと cert→itemID が汚染される(2026-06-18 試走で
    cert='356700921169' → itemID='Cowes T-shirt XL' のゴミ混入を検出)。
    """
    return (cert.isdigit() and 7 <= len(cert) <= 9
            and itemid.isdigit() and 11 <= len(itemid) <= 12)


def _cert_to_itemid_map():
    """商品管理シート(I列=cert# / B列=itemID)の逆引き {cert: itemID} (I/O)。形式検証で汚染除去。"""
    from sheet_io import _product_ws, PRODUCT_COL_ITEMID, PRODUCT_COL_CERT
    out = {}
    for r in _product_ws().get_all_values()[1:]:
        if len(r) > max(PRODUCT_COL_ITEMID, PRODUCT_COL_CERT):
            iid = (r[PRODUCT_COL_ITEMID] or "").strip()
            cert = (r[PRODUCT_COL_CERT] or "").strip()
            if iid and cert and _valid_cert_itemid(cert, iid):
                out[cert] = iid
    return out


def convert_file(add_csv_path, out_path, cert_to_itemid=None):
    """Add CSV ファイル → Revise CSV ファイル。戻り (件数, skipped)。"""
    with open(add_csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0, []
    header, body = rows[0], rows[1:]
    if cert_to_itemid is None:
        cert_to_itemid = _cert_to_itemid_map()
    rh, rr, skipped = add_rows_to_revise(header, body, cert_to_itemid)
    # eBay FileExchange 規約: QUOTE_NONNUMERIC + utf-8(BOMなし)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
        w.writerow(rh)
        for r in rr:
            w.writerow(r)
    return len(rr), skipped
