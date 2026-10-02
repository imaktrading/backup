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
                 "color": item.get("color", ""), "spec": None, "avail": item.get("avail") or 0}]
    out = []
    for v in variations:
        spec = v.get("spec") or {}
        low = {k.lower(): val for k, val in spec.items()}
        color = low.get("color") or low.get("colour") or ""
        out.append({"kind": 3 if color else 2,
                    "size": A.jp_size(low.get("sizes") or low.get("size") or ""),
                    "color": color or item.get("color", ""), "spec": spec, "avail": v.get("avail") or 0})
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


# ------------------------------------------------------------------ 実行

def _revise(iid: str, slot: dict, qty: int) -> dict:
    from ebay_actions.trading_api_client import (  # noqa: PLC0415
        revise_inventory_status, revise_inventory_status_variation)
    if slot["spec"] is None:
        return revise_inventory_status(iid, qty)
    return revise_inventory_status_variation(iid, slot["spec"], qty)


def run(execute_zero: bool, execute_restore: bool) -> dict:
    from sheet_updater import open_sheet, read_main_active_rows  # noqa: PLC0415
    try:
        prev = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    except (OSError, ValueError):
        prev = {}
    streaks = prev.get("streak_in", {})
    new_streaks = {}
    plan, reports = [], []
    listings = read_main_active_rows(open_sheet(), supplier_filter="all")
    for L in listings:
        iid, sup_name = L["listing_id"], L.get("supplier", "uniqlo")
        try:
            item = A._get_item(iid)
        except Exception as ex:  # noqa: BLE001
            reports.append({"iid": iid, "why": f"eBay を読めない {type(ex).__name__}: {ex}"})
            continue
        if item.get("status") != "Active":
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

    STATE_FILE.write_text(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                                      "streak_in": new_streaks}, ensure_ascii=False), encoding="utf-8")
    return {"ts": datetime.now().isoformat(timespec="seconds"), "listings": len(listings),
            "plan": [p[0] for p in plan], "done": done, "held": held, "reports": reports,
            "execute_zero": execute_zero, "execute_restore": execute_restore}


def main() -> int:
    ap = argparse.ArgumentParser(description="実 eBay × 仕入元 (サイズ・色) で eBay の数量を決める")
    ap.add_argument("--execute-zero", action="store_true")
    ap.add_argument("--execute-restore", action="store_true")
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    res = run(args.execute_zero, args.execute_restore)
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
