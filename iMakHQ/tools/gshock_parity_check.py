"""gshock_parity_check — 生成済 gshock CSV の Item Specifics を catalog と突合 (read-only)。

TCG の tcg_parity_check の G-shock 横展開 (2026-06-14)。G-shock は既に catalog 駆動
(lookup_gshock) なので「作り直し」でなく **CSV が現 catalog と一致しているかの drift 監査**。

各 CSV 行の model を *Title から抽出し、gshock_to_csv の生成核を **そのまま再利用** して
catalog から期待 Item Specifics を再導出 (scrape 無し):
    lookup_gshock(model) → _catalog_record_to_scrape_dict → build_row → 期待 row
→ catalog 駆動列を CSV 値とフィールド単位で diff し分類:
    OK            : 一致
    GAP_FILLABLE  : CSV 空 / catalog に値あり (= 出品に充填できる。Movement/Display/Features 等)
    CATALOG_GAP   : CSV に値 / catalog 空 (= catalog 拡充候補。Harvest 依頼の材料)
    DRIFT         : 両方値ありで不一致 (= CSV が古い catalog 由来 or scrape override 乖離。要確認)

ロジックは gshock_to_csv を import 再利用 (値の二重定義をしない = SSOT)。

使い方:
  python gshock_parity_check.py [csv_path]   # 省略時 csv_output 最新 gshock_upload_*.csv
  exit code: DRIFT が1件でもあれば 1、無ければ 0。
"""
from __future__ import annotations
import csv
import glob
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_GSHOCK = r"C:/dev/iMak/iMakG-shock"
for _p in (_HERE, _GSHOCK):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

CSV_DIR = r"C:/dev/iMak/iMakHQ/csv_output"

# catalog (lookup_gshock) が決定論で埋める列だけ parity 対象 (静的/採点/定数列は除外)。
PARITY_COLS = [
    "*Title",
    "C:Display", "C:Band Color", "C:Dial Color", "C:Bezel Color",
    "C:Band Material", "C:Case Material", "C:Features", "C:Movement",
    "C:Water Resistance", "C:Case Size", "C:Year Manufactured",
    "C:Case Thickness", "C:Band Width", "C:Item Weight", "C:Model",
]

_SEVERITY_ORDER = {"drift": 0, "gap_fillable": 1, "catalog_gap": 2, "ok": 3}


def _norm(s: str) -> str:
    s = (s or "").lower().replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip()


def extract_model(title: str) -> str:
    """*Title 'CASIO G-Shock <MODEL> Mens Watch ...' から model を抽出。無ければ ''。"""
    m = re.search(r"G-?Shock\s+([A-Za-z0-9][A-Za-z0-9\-]+)", title or "", re.I)
    return m.group(1).strip() if m else ""


def classify(col: str, old: str, new: str) -> tuple[str, str]:
    """CSV値(old) vs catalog期待値(new) を分類 (純関数=テスト可能)。"""
    no, nn = _norm(old), _norm(new)
    if no == nn:
        return ("ok", "一致")
    if col == "*Title":
        return ("gap_fillable" if not no else "drift",
                "title変更 (catalog由来specの反映を確認)" if no else "title 空→生成")
    if not no and nn:
        return ("gap_fillable", f"CSV空 / catalog '{new}' → 充填可")
    if no and not nn:
        return ("catalog_gap", f"CSV '{old}' / catalog 空 → catalog拡充候補")
    return ("drift", f"不一致 CSV '{old}' ≠ catalog '{new}'")


def _expected_row(model: str, headers: list):
    """gshock_to_csv の生成核で catalog から期待 row を再導出 (scrape 無し)。
    Returns (row_list|None, err)。row_list は headers 順。"""
    import gshock_to_csv as G
    lookup = getattr(G, "_catalog_lookup", None)
    if lookup is None:
        return None, "catalog lookup 不能 (gshock_lookup 未ロード)"
    rec = lookup(model)
    if not rec:
        return None, f"catalog MISS ({model})"
    data = G._catalog_record_to_scrape_dict(rec, model)
    if not data:
        return None, f"catalog record 変換失敗 ({model})"
    try:
        row = G.build_row("", G.DEFAULT_PRICE, data, "")
    except Exception as e:
        return None, f"build_row 失敗: {type(e).__name__}: {e}"
    if not isinstance(row, list) or len(row) != len(headers):
        return None, f"row 長不一致 (build_row={len(row) if isinstance(row,list) else '?'} vs headers={len(headers)})"
    # 実パイプラインと同じ eBay フィルタ (SELECTION_ONLY不在→空欄等) を期待行にも適用。
    # これを省くと Item Weight 等「build_row は出すが eBay filter が blank する」値を
    # 偽 GAP_FILLABLE として誤検出する (= 狼少年化)。psa/gshock 本番と同じ後処理を踏む。
    try:
        ret = G.apply_ebay_filter_to_row_gshock(row, headers, category="gshock")
        if isinstance(ret, list) and len(ret) == len(headers):
            row = ret
    except Exception:
        pass  # フィルタ未ロード等は素の build_row で続行 (verify不能で落とさない)
    return row, None


def compare_row(csv_row: dict, headers: list):
    """CSV1行 vs catalog期待。Returns {model, err, diffs:[(col,old,new,sev,note)]}。"""
    title = csv_row.get("*Title", "")
    model = extract_model(title)
    if not model:
        return {"model": "", "err": "model 抽出不能 (title 異常)", "diffs": []}
    exp_row, err = _expected_row(model, headers)
    if err:
        return {"model": model, "err": err, "diffs": []}
    exp = dict(zip(headers, exp_row))
    diffs = []
    for col in PARITY_COLS:
        if col not in exp:
            continue
        old_val = csv_row.get(col, "")
        new_val = exp.get(col, "")
        sev, note = classify(col, old_val, new_val)
        if sev != "ok":
            diffs.append((col, old_val, new_val, sev, note))
    diffs.sort(key=lambda d: _SEVERITY_ORDER.get(d[3], 9))
    return {"model": model, "err": None, "diffs": diffs}


def run(csv_path: str) -> int:
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        all_rows = list(reader)
    if not all_rows:
        print("空 CSV"); return 0
    headers = all_rows[0]
    print("=" * 70)
    print(f"gshock_parity_check (生成CSV vs catalog・read-only)\n対象: {os.path.basename(csv_path)}")
    print("=" * 70)
    n_drift = n_gap = n_cgap = n_miss = 0
    for n, raw in enumerate(all_rows[1:], 1):
        csv_row = dict(zip(headers, raw))
        res = compare_row(csv_row, headers)
        title = csv_row.get("*Title", "")[:60]
        if res.get("err"):
            if "MISS" in res["err"]:
                n_miss += 1
            print(f"\n[{n}] ⚠️ {res['model']}: {res['err']}")
            continue
        diffs = res["diffs"]
        drifts = [d for d in diffs if d[3] == "drift"]
        mark = "🚨" if drifts else ("🔧" if any(d[3] == "gap_fillable" for d in diffs) else
                                    ("👀" if diffs else "✅"))
        print(f"\n[{n}] {mark} {res['model']}  {title}")
        for col, old, new, sev, note in diffs:
            tag = {"drift": "🚨DRIFT", "gap_fillable": "🔧GAP_FILLABLE",
                   "catalog_gap": "👀CATALOG_GAP"}.get(sev, sev)
            print(f"     [{tag}] {col}: {note}")
            if sev == "drift":
                n_drift += 1
            elif sev == "gap_fillable":
                n_gap += 1
            else:
                n_cgap += 1
    print("\n" + "=" * 70)
    print(f"結果: DRIFT(不一致) {n_drift} / GAP_FILLABLE(catalog有CSV空) {n_gap} / "
          f"CATALOG_GAP(CSV有catalog空) {n_cgap} / catalog MISS {n_miss}")
    if n_drift:
        print("🚨 DRIFT あり → CSV が現 catalog と不一致。再生成 or catalog 確認。")
    else:
        print("✅ DRIFT なし。差分は充填可(再生成で改善) or catalog拡充候補のみ。")
    print("=" * 70)
    return n_drift


def find_latest_csv():
    cands = [c for c in glob.glob(os.path.join(CSV_DIR, "gshock_upload_*.csv"))
             if ".bak" not in os.path.basename(c)]
    return max(cands, key=os.path.getmtime) if cands else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else find_latest_csv()
    if not path or not os.path.exists(path):
        print(f"CSV が見つかりません: {path}"); sys.exit(2)
    sys.exit(1 if run(path) else 0)


if __name__ == "__main__":
    main()
