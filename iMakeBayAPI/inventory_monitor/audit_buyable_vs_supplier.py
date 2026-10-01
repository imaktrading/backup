"""audit_buyable_vs_supplier - 実 eBay で買える枠 × 仕入元の在庫 を サイズ・色 で突合せる (読むだけ).

★ 2026-10-02 (オファーで発覚した取下げ漏れの再発防止):
  既存の audit は「シートの K 列 / 対処済 B 列 / report の (listing, SKU)」で判断していたため、
    - 単品 listing を report が読まず、シートだけ K=0 にして eBay は買えるまま (サンダーパス RED)
    - 同じ SKU に別の色の行 (✕ と ◎) があると「重複で保留」になり、本物の取下げ漏れが埋もれる (EVANGELION NAVY)
    - eBay に色があるのに仕入元の行が無い枠は誰も見ていない (74 枠)
  を見逃した。ここでは **実 eBay (GetItem) を正** として、出品の作りごとに サイズ・色 で
  仕入元の行に 1 対 1 で対応させ、次を知らせる (eBay は一切変えない):
    danger    : 仕入元 ✕ なのに eBay で買える              → ⚠️要対応 (取下げが要る)
    gap       : eBay で買えるのに 対応する仕入元の行が無い  → 監視されていない枠
    ambiguous : 対応する行が複数あって ✕/◎ が食い違う      → どちらが正しいか決められない
    stale     : 対応する行の 自動CHK日 が古い (巡回で見られていない)

  出品の作り:
    ① 単品 (variation なし)             : 出品の サイズ・色 ↔ 仕入元の1行
    ② サイズだけの variation (色は出品全体) : 出品の色 × variation のサイズ ↔ 仕入元の1行
    ③ サイズと色の variation              : variation の サイズ・色 ↔ 仕入元の1行

実行:
    python audit_buyable_vs_supplier.py            # 突合せ + 要対応ならメール/デスクトップ
    python audit_buyable_vs_supplier.py --no-alert # 突合せだけ
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
_INV_ROOT = SCRIPT_DIR.parent.parent / "iMakInventory"
for _p in (_INV_ROOT, _INV_ROOT / "ebay_actions"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))   # append: inventory_monitor の解決を優先

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

LOG_DIR = SCRIPT_DIR / "logs"
STATE_FILE = LOG_DIR / "audit_buyable_state.json"
STALE_HOURS = 24          # 自動CHK日 がこれより古い行は「巡回で見られていない」
LIVE_DAYS = 3             # これより古い行は 対応付けに使わない (= 今の出品と無関係な昔の行)

# モンベルの出品タイトル/eBay 色 → 公式の色コード (main.MONTBELL_COLOR_MAP と同じ。2026-05-14 ユーザー確認)
MONTBELL_COLOR_MAP = {
    "RED": "RDBR", "BLUE": "NV/PB", "ORANGE": "HN/MA", "BROWN": "GP/OC",
}


def _log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ 正規化 (純関数)

def color_keys(c: str) -> set:
    """色の表記ゆれを吸収した照合キーの集合.

    "Black(BK)" → {BLACK(BK), BK, BLACK} / "09 BLACK" → {09 BLACK, BLACK} / "Red" → {RED, RDBR}
    """
    c = (c or "").strip().upper()
    if not c:
        return set()
    keys = {c}
    m = re.search(r"\(([A-Z0-9/]+)\)", c)
    if m:
        keys.add(m.group(1))
        keys.add(c[:m.start()].strip())
    keys.add(re.sub(r"^\d+\s+", "", c))
    for k in list(keys):
        if k in MONTBELL_COLOR_MAP:
            keys.add(MONTBELL_COLOR_MAP[k])
    return {k for k in keys if k}


def jp_size(text: str) -> str:
    """eBay の サイズ表記 → JP サイズ. "US S(JP M)" → "M" / "JP L" → "L" / 取れなければ ""."""
    m = re.search(r"JP\s*([0-9A-Z\-\.]+)", (text or "").upper())
    return m.group(1) if m else ""


def _chk_dt(s: str):
    try:
        return datetime.strptime((s or "").strip(), "%Y/%m/%d %H:%M")
    except ValueError:
        return None


# ------------------------------------------------------------------ 突合せ (純関数)

def classify_listing(item: dict, rows: list, now: datetime = None) -> list:
    """1 出品分の 買える枠 を仕入元の行と突き合わせ、問題のある枠の list を返す.

    item: {"iid","title","status","avail","color","size","variations":[{"spec":{name:value},"avail"}]}
    rows: SKU 詳細シートのその出品の行 [{"row","size","color","supplier","chk"}]
    """
    now = now or datetime.now()
    out = []
    if item.get("status") != "Active":
        return out
    live = [r for r in rows if (_chk_dt(r["chk"]) or datetime.min) >= now - timedelta(days=LIVE_DAYS)]

    def judge(slot_label, avail, cands):
        if avail <= 0:
            return
        base = {"iid": item["iid"], "title": item["title"][:40], "slot": slot_label, "ebay_avail": avail}
        if not cands:
            out.append({**base, "kind": "gap"})
            return
        marks = {c["supplier"] for c in cands}
        rows_s = [c["row"] for c in cands]
        if len(marks) > 1:
            out.append({**base, "kind": "ambiguous", "rows": rows_s, "marks": sorted(marks)})
            return
        mark = marks.pop()
        if mark == "✕":
            out.append({**base, "kind": "danger", "rows": rows_s})
        elif mark != "◎":
            out.append({**base, "kind": "ambiguous", "rows": rows_s, "marks": [mark]})
        if any((_chk_dt(c["chk"]) or datetime.min) < now - timedelta(hours=STALE_HOURS) for c in cands):
            out.append({**base, "kind": "stale", "rows": rows_s})

    def match(size, colors):
        return [r for r in live
                if r["size"].strip().upper() == size
                and (not colors or color_keys(r["color"]) & colors)]

    variations = item.get("variations") or []
    if not variations:                                         # ① 単品
        avail = item.get("avail") or 0
        size = jp_size(item.get("title", "")) or jp_size(item.get("size", ""))
        colors = color_keys(item.get("color", ""))
        cands = match(size, colors) if size else []
        if not cands and len(live) == 1:                       # 巡回が1行に集約している単品
            cands = live
        judge(f"{size or '?'} / {item.get('color', '')}", avail, cands)
        return out

    listing_colors = color_keys(item.get("color", ""))
    # ② サイズだけの出品は 1 色。eBay の色名 (Beige) と仕入元の色名 (NATURAL) が違うことがあるので、
    #    名前が合わなくても 仕入元の行が 1 色だけならその色で判定し、色の対応は 1 回だけ確かめてもらう。
    size_only = not any("color" in {k.lower() for k in (v.get("spec") or {})} for v in variations)
    live_colors = {r["color"].strip().upper() for r in live}
    use_any_color = False
    if size_only and not any(color_keys(r["color"]) & listing_colors for r in live) and len(live_colors) == 1:
        use_any_color = True
        out.append({"iid": item["iid"], "title": item["title"][:40], "kind": "color_check",
                    "slot": f"eBay {item.get('color', '') or '(色なし)'} / 仕入元 {next(iter(live_colors))}",
                    "ebay_avail": sum(max(v.get("avail") or 0, 0) for v in variations)})
    for v in variations:
        spec = {k.lower(): val for k, val in (v.get("spec") or {}).items()}
        size = jp_size(spec.get("sizes") or spec.get("size") or "")
        vcolor = spec.get("color") or spec.get("colour") or ""
        colors = color_keys(vcolor) if vcolor else (None if use_any_color else listing_colors)   # ③ / ②
        cands = match(size, colors) if size else []
        judge(f"{size or '?'} / {vcolor or item.get('color', '')}", v.get("avail") or 0, cands)
    return out


# ------------------------------------------------------------------ I/O

def _get_item(iid: str) -> dict:
    from ebay_actions.trading_api_client import _call_trading  # noqa: PLC0415
    body = ("<?xml version='1.0' encoding='utf-8'?><GetItemRequest xmlns='urn:ebay:apis:eBLBaseComponents'>"
            f"<ItemID>{iid}</ItemID><DetailLevel>ReturnAll</DetailLevel>"
            "<IncludeItemSpecifics>true</IncludeItemSpecifics></GetItemRequest>")
    x = _call_trading("GetItem", body, raw_xml_cap=None).get("raw_xml") or ""
    if "<ListingStatus>" not in x:
        return {"status": None}
    status = re.search(r"<ListingStatus>(\w+)</ListingStatus>", x).group(1)
    variations = []
    for v in re.findall(r"<Variation>(.*?)</Variation>", x, re.S):
        q = int((re.search(r"<Quantity>(\d+)</Quantity>", v) or [0, "0"])[1])
        s = int((re.search(r"<QuantitySold>(\d+)</QuantitySold>", v) or [0, "0"])[1])
        spec = dict(re.findall(r"<NameValueList><Name>([^<]*)</Name><Value>([^<]*)</Value>", v))
        variations.append({"spec": spec, "avail": q - s})
    top = re.sub(r"<Variations>.*?</Variations>", "", x, flags=re.S)
    q = re.search(r"<Quantity>(\d+)</Quantity>", top)
    s = re.search(r"<QuantitySold>(\d+)</QuantitySold>", top)
    specs = {k.lower(): val for k, val in re.findall(
        r"<NameValueList><Name>([^<]*)</Name><Value>([^<]*)</Value>", top)}
    title = (re.search(r"<Title>([^<]*)</Title>", x) or [0, ""])[1]
    return {"status": status, "avail": (int(q[1]) - int(s[1])) if q and s else 0,
            "color": specs.get("color", ""), "size": specs.get("size", ""),
            "ebay_title": title, "variations": variations}


def run() -> dict:
    from sheet_updater import open_sheet, get_sku_worksheet, read_main_active_rows  # noqa: PLC0415
    sh = open_sheet()
    listings = read_main_active_rows(sh, supplier_filter="all")
    sku = get_sku_worksheet(sh).get_all_values()
    rows_by = {}
    for i, r in enumerate(sku[1:], start=2):
        r = list(r) + [""] * 12
        rows_by.setdefault(r[3].strip(), []).append(
            {"row": i, "size": r[6], "color": r[7], "supplier": r[8].strip(), "chk": r[11]})

    findings, fetch_errors, n_checked = [], [], 0
    for L in listings:
        iid = L["listing_id"]
        try:
            e = _get_item(iid)
        except Exception as ex:  # noqa: BLE001
            fetch_errors.append(f"{iid}: {type(ex).__name__}: {ex}")
            continue
        if e.get("status") is None:
            fetch_errors.append(f"{iid}: eBay の状態を取得できず")
            continue
        n_checked += 1
        item = {"iid": iid, "title": e.get("ebay_title") or L.get("title", ""), **e}
        findings += classify_listing(item, rows_by.get(iid, []))

    by_kind = {k: [f for f in findings if f["kind"] == k]
               for k in ("danger", "gap", "ambiguous", "stale", "color_check")}
    return {"ts": datetime.now().isoformat(timespec="seconds"), "listings": len(listings),
            "checked": n_checked, "fetch_errors": fetch_errors,
            "counts": {k: len(v) for k, v in by_kind.items()}, "findings": findings}


def _alert(result: dict, prev: dict) -> None:
    """danger があれば必ず、gap/ambiguous は前回より増えた時だけ、メール + デスクトップで知らせる."""
    c, pc = result["counts"], (prev or {}).get("counts", {})
    reasons = []
    if c["danger"]:
        reasons.append(f"⚠️要対応 仕入元✕ なのに eBay で買える {c['danger']} 枠")
    for k, label in (("gap", "監視されていない枠"), ("ambiguous", "行が食い違う枠"),
                     ("color_check", "eBay と仕入元で色名が違う出品")):
        if c[k] > pc.get(k, 0):
            reasons.append(f"{label} {pc.get(k, 0)} → {c[k]}")
    if result["fetch_errors"]:
        reasons.append(f"eBay を読めなかった出品 {len(result['fetch_errors'])} 件")
    if not reasons:
        return
    lines = ["公式監視くん: 実 eBay × 仕入元 突合せ (サイズ・色)", ""] + reasons + [""]
    for f in result["findings"]:
        if f["kind"] in ("danger", "ambiguous") or (
                f["kind"] in ("gap", "color_check") and c[f["kind"]] > pc.get(f["kind"], 0)):
            lines.append(f"[{f['kind']}] {f['iid']} {f['title']} / {f['slot']} / eBay残り {f['ebay_avail']}"
                         + (f" / 行 {f.get('rows')}" if f.get("rows") else ""))
    lines += [""] + result["fetch_errors"][:10]
    text = "\n".join(lines)
    subj = f"[公式監視くん] {reasons[0]}"
    try:
        desk = Path.home() / "OneDrive" / "デスクトップ" / f"ALERT_公式監視くん_eBay突合せ_{datetime.now():%Y%m%d_%H%M%S}.txt"
        if c["danger"]:
            desk.write_text(text, encoding="utf-8")
    except Exception as ex:  # noqa: BLE001
        _log(f"  [WARN] desktop alert 失敗: {ex}")
    try:
        if str(_INV_ROOT) not in sys.path:
            sys.path.insert(0, str(_INV_ROOT))
        from email_notifier import _send_via_gmail   # noqa: PLC0415
        from auth.encrypted_gmail import load_gmail_config   # noqa: PLC0415
        cfg = load_gmail_config()
        if cfg:
            _send_via_gmail(cfg[0], cfg[1], cfg[2], subj, text)
            _log(f"  [alert] email 送信: {subj}")
    except Exception as ex:  # noqa: BLE001
        _log(f"  [WARN] email 送信失敗: {type(ex).__name__}: {ex}")


def main() -> int:
    ap = argparse.ArgumentParser(description="実 eBay × 仕入元 突合せ (読むだけ)")
    ap.add_argument("--no-alert", action="store_true")
    args = ap.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        prev = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    except (OSError, ValueError):
        prev = {}
    result = run()
    c = result["counts"]
    _log(f"突合せ: 出品 {result['listings']} / eBay 読込 {result['checked']} / "
         f"⚠️要対応 {c['danger']} / 監視されていない枠 {c['gap']} / 食い違い {c['ambiguous']} / "
         f"巡回で古い {c['stale']} / 色名が違う出品 {c['color_check']} / 読込失敗 {len(result['fetch_errors'])}")
    for f in result["findings"]:
        if f["kind"] == "danger":
            _log(f"  ⚠️要対応 {f['iid']} {f['title']} / {f['slot']} / eBay残り {f['ebay_avail']} / 行 {f['rows']}")
    (LOG_DIR / f"audit_buyable_{datetime.now():%Y%m%d_%H%M%S}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.no_alert:
        _alert(result, prev)
    STATE_FILE.write_text(json.dumps({"ts": result["ts"], "counts": c}, ensure_ascii=False), encoding="utf-8")
    # danger / 読込失敗 があれば step を NG にして巡回レポートに出す
    return 1 if (c["danger"] or result["fetch_errors"]) else 0


if __name__ == "__main__":
    sys.exit(main())
