"""ebay_supplier_sync - 実 eBay の枠 × 仕入元の実在庫 (全色) を サイズ・色 で照合して eBay の数量を決める.

★ 2026-10-02 (取下げ漏れ 52 枠の総点検を受けた作り直し):
  旧方式 (auto_qty_zero / audit_and_heal) は シートの K 列 (eBay 現Qty)・B 列 (対処済)・
  report の (listing, SKU) で判断しており、シートがずれると取下げも復活も間違えた。
  ここでは シートを使わず、毎回 **実 eBay (GetItem)** と **仕入元のページ (全色)** を直接読み、
  出品の作りごとに 1 枠ずつ対応させて決める:
    ① 単品 (variation なし)             : 出品の サイズ・色
    ② サイズだけの variation              : 出品の色 (= 仕入元 URL の色) × variation のサイズ
    ③ サイズと色の variation              : variation の サイズ・色

  判断:
    zero    : 仕入元が はっきり ✕ (STOCK_OUT / 完売 / 入荷未定 等) かつ eBay で買える → 0
              ページから その色/サイズ が消えた場合は、色が確かな時 (① ② = URL/タイトルの色) だけ 0
    restore : 仕入元 ◎ が 2 回続いた かつ eBay 0 かつ 対応が 1 つに決まる → 1   (★ユーザーの OK まで止める)
    report  : 仕入元を読めない / 対応が決まらない / 色名が合わない → eBay は変えず知らせる

実行:
    python ebay_supplier_sync.py                       # 判断だけ (eBay は変えない)
    python ebay_supplier_sync.py --execute-zero        # 取下げだけ実行
    python ebay_supplier_sync.py --execute-zero --execute-restore
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import audit_buyable_vs_supplier as A  # noqa: E402  (color_keys / jp_size / _get_item / パス設定)

LOG_DIR = SCRIPT_DIR / "logs"
STATE_FILE = LOG_DIR / "ebay_supplier_sync_state.json"
MAX_ZERO = 60        # 1 回に 0 にする上限 (scrape の系統的誤判定で一斉に落とさない)
MAX_RESTORE = 20     # 1 回に 1 に戻す上限
RESTORE_STREAK = 2   # 仕入元 ◎ が何回続いたら戻すか

_log = A._log


# ------------------------------------------------------------------ 仕入元 (I/O)

def supplier_stock(sup: str, url: str, title: str) -> dict:
    """仕入元の実在庫を全色で読む.

    Returns: {"stock": {(frozenset(色キー), サイズ): True/False}, "trusted_colors": set, "ok": bool}
      trusted_colors = URL / 出品タイトルから確かに分かる 出品の色 (① ② で使う)
    """
    stock, trusted = {}, set()
    if sup in ("uniqlo", "gu"):
        import uniqlo_scraper as U  # noqa: PLC0415
        import gu_scraper as G  # noqa: PLC0415
        S = U if sup == "uniqlo" else G
        info = S.parse_uniqlo_url(url)
        l2s = S._call_l2s_api(info["product_id"], info["price_group"])
        det = S._call_details_api(info["product_id"], info["price_group"])
        names = {c["displayCode"]: (c.get("name") or "").upper()
                 for c in det.get("colors", []) if "displayCode" in c}
        stocks = l2s.get("stocks", {})
        for it in l2s.get("l2s", []):
            code = (it.get("color") or {}).get("displayCode", "")
            size = S._resolve_size_name((it.get("size") or {}).get("displayCode", ""),
                                        det.get("sizes", [])).upper()
            st = (stocks.get(it.get("l2Id")) or {}).get("statusCode", "")
            ok = st in ("IN_STOCK", "LOW_STOCK") and it.get("sales", True)
            keys = frozenset({code, names.get(code, ""), f"{code} {names.get(code, '')}"} - {"", " "})
            stock[(keys, size)] = ok
        c = info.get("color_display_code")
        if c:
            trusted = {c, names.get(c, "")} - {""}
    elif sup == "montbell":
        import montbell_scraper as MB  # noqa: PLC0415
        import main as M  # noqa: PLC0415
        info = MB.fetch_product_inventory(url, target_color_code=None)
        for s in info.get("skus", []):
            stock[(frozenset({(s.get("color_code") or "").upper()}), (s.get("size") or "").upper())] = \
                bool(s.get("in_stock"))
        hint = M.guess_montbell_color(title)
        if hint:
            trusted = {hint}
    else:
        import main as M  # noqa: PLC0415
        info = M.fetch_supplier_inventory(sup, url, title)
        if not info:
            return {"stock": {}, "trusted_colors": set(), "ok": False}
        for s in info.get("skus", []):
            stock[(frozenset({"*"}), (s.get("size") or "*").upper())] = bool(s.get("in_stock"))
    return {"stock": stock, "trusted_colors": trusted, "ok": bool(stock)}


# ------------------------------------------------------------------ 判断 (純関数)

def ebay_slots(item: dict) -> list:
    """実 eBay の出品 → 枠の list [{"kind": ①②③, "size", "color", "spec", "avail"}]."""
    variations = item.get("variations") or []
    if not variations:
        return [{"kind": 1, "size": A.jp_size(item.get("ebay_title", "")) or A.jp_size(item.get("size", "")),
                 "color": item.get("color", ""), "spec": None, "avail": item.get("avail") or 0,
                 "sku": item.get("sku", "")}]
    out = []
    for v in variations:
        spec = v.get("spec") or {}
        low = {k.lower(): val for k, val in spec.items()}
        color = low.get("color") or low.get("colour") or ""
        out.append({"kind": 3 if color else 2,
                    "size": A.jp_size(low.get("sizes") or low.get("size") or ""),
                    "color": color or item.get("color", ""), "spec": spec, "avail": v.get("avail") or 0,
                    "sku": v.get("sku", "")})
    return out


def supplier_state(slot: dict, sup: dict) -> tuple:
    """1 枠の仕入元の状態 → ("in" | "out" | "vanished" | "unknown", 理由)."""
    stock = sup["stock"]
    if not sup["ok"]:
        return "unknown", "仕入元を読めない"
    if all(k == frozenset({"*"}) for k, _ in stock):           # 色の無い仕入元 (amazon / workman 等)
        sizes = {sz for _, sz in stock}
        hits = [ok for (_, sz), ok in stock.items() if sz == slot["size"] or len(sizes) == 1]
        if not hits:
            return "unknown", "サイズが仕入元に無い"
        return ("in" if any(hits) else "out"), ""
    if "ASSORTED" in (slot["color"] or "").upper():
        # ★ 2026-10-02 ユーザー確認: 「Assorted (N Colors Mix)」= 全色を 1 枚ずつ組む商品。
        #   そのサイズで 全色に在庫がある時だけ ◎。1 色でも ✕ なら ✕。
        hits = [ok for (_, sz), ok in stock.items() if sz == slot["size"]]
        if not hits:
            return "unknown", "アソートのサイズが仕入元に無い"
        return ("in" if all(hits) else "out"), "アソート = 全色そろって在庫あり"
    if slot["kind"] in (1, 2):
        colors = sup["trusted_colors"] or A.color_keys(slot["color"])
        trusted = bool(sup["trusted_colors"])
    else:
        colors = A.color_keys(slot["color"])
        trusted = False
    known_colors = set().union(*[k for k, _ in stock]) if stock else set()
    if not (colors & known_colors):
        # 色が仕入元のページに無い: 色が確かなら 消えた = 買えない。そうでなければ名前の不一致かもしれない
        return ("vanished", "仕入元のページから色が消えた") if trusted else ("unknown", "色名が仕入元と合わない")
    hits = [ok for (keys, sz), ok in stock.items() if sz == slot["size"] and keys & colors]
    if not hits:
        sizes_of_color = {sz for (keys, sz) in stock if keys & colors}
        if trusted and sizes_of_color:
            return "vanished", "仕入元のページからサイズが消えた"
        return "unknown", "サイズが仕入元と合わない"
    if len(set(hits)) > 1:
        return "unknown", "対応が 1 つに決まらない"
    return ("in" if hits[0] else "out"), ""


def decide(slot: dict, state: str, streak_in: int) -> str:
    """→ "zero" | "restore" | "keep"."""
    if state in ("out", "vanished") and slot["avail"] > 0:
        return "zero"
    if state == "in" and slot["avail"] <= 0 and streak_in >= RESTORE_STREAK:
        return "restore"
    return "keep"


def slot_key(iid: str, slot: dict) -> str:
    return f"{iid}|{slot['size']}|{slot['color']}"


# ------------------------------------------------------------------ SKU 詳細シートを eBay の枠に合わせる (純関数)
# ★ 2026-10-02 ユーザー了承: SKU 詳細の行は これまで「仕入元 URL の 1 色」から作っていたため、
#   eBay で出している他の色の行が無い (74 枠) / サイズだけで別の色の行に当てる / 古い行が残る、
#   が起きていた。eBay の出品の枠 (①②③) を正として 1 枠 1 行に合わせる。行は消さない。
SHEET_COL_MATCH = 22          # V: eBay対応
SHEET_MATCH_HEADER = "eBay対応"


def supplier_color_name(slot: dict, sup: dict) -> str:
    """新しく作る行の H 列 (色) = 仕入元側の色名 (UNIQLO は "DARK GRAY"、montbell は "BK")."""
    def pick(keys):
        names = sorted((k for k in keys if k and not k.isdigit() and not re.match(r"^\d+\s", k)),
                       key=len, reverse=True)
        return names[0] if names else (sorted(keys)[0] if keys else "")
    if slot["kind"] in (1, 2) and sup.get("trusted_colors"):
        return pick(sup["trusted_colors"])
    ck = A.color_keys(slot["color"])
    for keys, _ in sup.get("stock", {}):
        if keys & ck and keys != frozenset({"*"}):
            return pick(keys)
    return (slot["color"] or "").upper()


def _slot_color_keys(slot: dict, sup: dict) -> set:
    keys = A.color_keys(slot["color"]) | A.color_keys(supplier_color_name(slot, sup))
    if slot["kind"] in (1, 2):
        keys |= set(sup.get("trusted_colors") or ())
    return keys


def plan_sheet(iid: str, title: str, slots: list, rows: list, now: str) -> dict:
    """1 出品分の SKU 詳細シートの直し方を決める.

    slots: [{"slot": ebay_slots の 1 枠, "sup": supplier_stock, "state": in/out/vanished/unknown, "avail": 実行後の残り}]
    rows : その出品の既存行 [{"row", "size", "color", "sku"}]
    Returns: {"updates": {row: {"I","K","L","V"}}, "appends": [行の値], "orphans": [row]}
    """
    updates, appends, used = {}, [], set()
    mark = {"in": "◎", "out": "✕", "vanished": "✕"}
    for s in slots:
        slot, sup = s["slot"], s["sup"]
        ck = _slot_color_keys(slot, sup)
        size = (slot["size"] or "").upper()
        hits = [r for r in rows
                if (r["size"] or "").strip().upper() == size
                and (not ck or A.color_keys(r["color"]) & ck)]
        cells = {"K": s["avail"], "L": now, "V": "対応あり"}
        if s["state"] in mark:
            cells["I"] = mark[s["state"]]
        if hits:
            updates[hits[0]["row"]] = cells
            used.add(hits[0]["row"])
            for extra in hits[1:]:
                updates[extra["row"]] = {"V": "重複 (同じ eBay 枠に複数行)"}
                used.add(extra["row"])
        else:
            appends.append([False, False, "", iid, title, slot.get("sku", ""), size,
                            supplier_color_name(slot, sup), cells.get("I", ""), "", s["avail"], now,
                            "", "", "", "", "", "", "", "", "", "対応あり (自動追加 " + now[:10] + ")"])
    orphans = [r["row"] for r in rows if r["row"] not in used]
    for r in orphans:
        updates[r] = {"V": "eBay に対応なし"}
    return {"updates": updates, "appends": appends, "orphans": orphans}


# ------------------------------------------------------------------ 実行

def _sync_sheet(sh, per_listing: dict, ended: set) -> dict:
    """SKU 詳細シートを eBay の枠に合わせて書く (I/K/L/V を更新、足りない行を追加、行は消さない)."""
    from sheet_updater import get_sku_worksheet  # noqa: PLC0415
    ws = get_sku_worksheet(sh)
    values = ws.get_all_values()
    if ws.col_count < SHEET_COL_MATCH:
        ws.add_cols(SHEET_COL_MATCH - ws.col_count)
    rows_by = {}
    for i, r in enumerate(values[1:], start=2):
        r = list(r) + [""] * SHEET_COL_MATCH
        rows_by.setdefault(r[3].strip(), []).append({"row": i, "size": r[6], "color": r[7], "sku": r[5]})
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    col = {"I": "I", "K": "K", "L": "L", "V": "V"}
    batch, appends, n_upd, n_orph, n_end = [], [], 0, 0, 0
    for iid, (title, slots) in per_listing.items():
        p = plan_sheet(iid, title[:80], [{**s} for s in slots], rows_by.get(iid, []), now)
        for row, cells in p["updates"].items():
            n_upd += 1
            for k, v in cells.items():
                batch.append({"range": f"{col[k]}{row}", "values": [[v]]})
        appends += p["appends"]
        n_orph += len(p["orphans"])
    for iid in ended:
        for r in rows_by.get(iid, []):
            n_end += 1
            batch.append({"range": f"V{r['row']}", "values": [["出品終了"]]})
    batch.append({"range": "V1", "values": [[SHEET_MATCH_HEADER]]})
    for i in range(0, len(batch), 2000):
        ws.batch_update(batch[i:i + 2000], value_input_option="USER_ENTERED")
    if appends:
        ws.append_rows(appends, value_input_option="USER_ENTERED")
    return {"updated": n_upd, "appended": len(appends), "orphans": n_orph, "ended": n_end}


def _revise(iid: str, slot: dict, qty: int) -> dict:
    from ebay_actions.trading_api_client import (  # noqa: PLC0415
        revise_inventory_status, revise_inventory_status_variation)
    if slot["spec"] is None:
        return revise_inventory_status(iid, qty)
    return revise_inventory_status_variation(iid, slot["spec"], qty)


def run(execute_zero: bool, execute_restore: bool, update_sheet: bool = False) -> dict:
    from sheet_updater import open_sheet, read_main_active_rows  # noqa: PLC0415
    try:
        prev = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    except (OSError, ValueError):
        prev = {}
    streaks = prev.get("streak_in", {})
    new_streaks = {}
    plan, reports = [], []
    per_listing = {}          # iid -> (title, [{slot, sup, state}])  シート合わせ用
    ended = set()
    sh = open_sheet()
    listings = read_main_active_rows(sh, supplier_filter="all")
    for L in listings:
        iid, sup_name = L["listing_id"], L.get("supplier", "uniqlo")
        try:
            item = A._get_item(iid)
        except Exception as ex:  # noqa: BLE001
            reports.append({"iid": iid, "why": f"eBay を読めない {type(ex).__name__}: {ex}"})
            continue
        if item.get("status") != "Active":
            ended.add(iid)
            continue
        try:
            sup = supplier_stock(sup_name, L["url"], L["title"])
        except Exception as ex:  # noqa: BLE001
            sup = {"stock": {}, "trusted_colors": set(), "ok": False}
            reports.append({"iid": iid, "why": f"仕入元を読めない {type(ex).__name__}: {ex}"})
        for slot in ebay_slots(item):
            st, why = supplier_state(slot, sup)
            key = slot_key(iid, slot)
            if st == "in":
                new_streaks[key] = streaks.get(key, 0) + 1
            action = decide(slot, st, new_streaks.get(key, 0))
            per_listing.setdefault(iid, (item.get("ebay_title") or L["title"], []))[1].append(
                {"slot": slot, "sup": sup, "state": st, "avail": slot["avail"]})
            rec = {"iid": iid, "title": (item.get("ebay_title") or L["title"])[:40], "sup": sup_name,
                   "slot": f"{slot['size'] or '?'} / {slot['color'] or '-'}", "kind": slot["kind"],
                   "ebay_avail": slot["avail"], "supplier": st, "why": why, "action": action}
            if action != "keep":
                plan.append((rec, iid, slot))
            elif st == "unknown" and slot["avail"] > 0:
                reports.append({"iid": iid, "why": f"{rec['slot']}: {why} (eBay 残り {slot['avail']})"})

    zeros = [p for p in plan if p[0]["action"] == "zero"]
    restores = [p for p in plan if p[0]["action"] == "restore"]
    done = {"zero": [], "restore": [], "failed": []}
    held = []
    for group, allowed, cap, qty in ((zeros, execute_zero, MAX_ZERO, 0),
                                     (restores, execute_restore, MAX_RESTORE, 1)):
        if len(group) > cap:
            held.append(f"{group[0][0]['action']} {len(group)} 枠 > 上限 {cap} → 全部保留 (読み取りの異常を疑う)")
            continue
        for rec, iid, slot in group:
            if not allowed:
                continue
            r = _revise(iid, slot, qty)
            (done[rec["action"]] if r.get("success") else done["failed"]).append(
                {**rec, "ack": r.get("ack"), "err": r.get("error_code")})
            if r.get("success"):
                for ent in per_listing.get(iid, (None, []))[1]:
                    if ent["slot"] is slot:
                        ent["avail"] = qty

    sheet_result = _sync_sheet(sh, per_listing, ended) if update_sheet else None

    STATE_FILE.write_text(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                                      "streak_in": new_streaks}, ensure_ascii=False), encoding="utf-8")
    return {"ts": datetime.now().isoformat(timespec="seconds"), "listings": len(listings),
            "plan": [p[0] for p in plan], "done": done, "held": held, "reports": reports,
            "sheet": sheet_result,
            "execute_zero": execute_zero, "execute_restore": execute_restore}


def main() -> int:
    ap = argparse.ArgumentParser(description="実 eBay × 仕入元 (サイズ・色) で eBay の数量を決める")
    ap.add_argument("--execute-zero", action="store_true")
    ap.add_argument("--execute-restore", action="store_true")
    ap.add_argument("--update-sheet", action="store_true", help="SKU 詳細シートを eBay の枠に合わせる")
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    res = run(args.execute_zero, args.execute_restore, args.update_sheet)
    if res.get("sheet"):
        _log(f"シート: 更新 {res['sheet']['updated']} 行 / 追加 {res['sheet']['appended']} 行 / "
             f"eBay に対応なし {res['sheet']['orphans']} 行 / 出品終了 {res['sheet']['ended']} 行")
    nz = sum(1 for p in res["plan"] if p["action"] == "zero")
    nr = sum(1 for p in res["plan"] if p["action"] == "restore")
    _log(f"判断: 0 にする {nz} 枠 / 1 に戻す {nr} 枠 / 知らせるだけ {len(res['reports'])} 件 / "
         f"実行: 0={len(res['done']['zero'])} 1={len(res['done']['restore'])} 失敗={len(res['done']['failed'])}")
    for p in res["plan"]:
        _log(f"  [{p['action']}] {p['iid']} {p['title']} / {p['slot']} / eBay残り {p['ebay_avail']} / 仕入元 {p['supplier']} {p['why']}")
    for h in res["held"]:
        _log(f"  ⚠️ {h}")
    (LOG_DIR / f"ebay_supplier_sync_{datetime.now():%Y%m%d_%H%M%S}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if (res["done"]["failed"] or res["held"]) else 0


if __name__ == "__main__":
    sys.exit(main())
