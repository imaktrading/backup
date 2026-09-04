# -*- coding: utf-8 -*-
"""PSA再仕入れ RESTOCK — 最後の配線(orchestrator)。

「RESTOCK確定」タブ → cert/KEY 解決 → psa_to_csv(RESTOCK入力モード)で Add CSV生成(新規と完全同一)
 → Add→Revise 変換 → Revise CSV(手動アップロード用)。

フロー:
  1. read_tab("RESTOCK確定") → itemID 群
  2. 商品管理シート: itemID→cert#(I列) / itemID→KEY(AI列)
  3. RESTOCK入力 json {certs, forced:{cert:KEY}, cost, supply_url} を出力
  4. psa_to_csv を PSA_RESTOCK_INPUT=json + TCG_USE_NEW_GEN=1 で subprocess 実行(新コア生成・forced変種)
  5. 生成された tcg_upload_*.csv(Add) を Add→Revise 変換 → Revise CSV
  6. → 手動 FileExchange アップロード → 別途 writeback(qty verify)

build_restock_input は純関数(test可)。実行(subprocess/CSV)は main。
"""
import glob
import json
import os
import subprocess
import sys

_TCG_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "iMakTCG"))
_CSV_OUT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "csv_output"))
_DESK = r"C:\Users\imax2\OneDrive\デスクトップ"


def _cost_sanity(cost_jpy, live_price_usd=None):
    """仕入値の妥当性 (pricing_engine が唯一の判定。ここには基準を書かない)。

    読めない環境でも **止まる側**に倒す = 判定できない時は通さない、ではなく
    「判定器が無い」を理由に素通しにしない。import 失敗はそのまま上げる。
    """
    import os as _os
    import sys as _sys
    _api = _os.path.join(_os.path.dirname(_os.path.dirname(
        _os.path.dirname(_os.path.abspath(__file__)))), "iMakeBayAPI")
    if _api not in _sys.path:
        _sys.path.insert(0, _api)
    from pricing_engine import cost_sanity
    return cost_sanity(cost_jpy, live_price_usd=live_price_usd)


def build_restock_input(restock_rows, itemid_to_cert, itemid_to_key):
    """RESTOCK確定 rows → psa_to_csv RESTOCK入力 dict。純関数。

    restock_rows: [{"itemID":.., "cost":¥, "supply_url":url}]
    Returns: (input_dict, skipped[(itemID, 理由)])
    """
    certs, forced, cost, supply = [], {}, {}, {}
    skipped = []
    seen = set()
    for r in restock_rows:
        iid = (r.get("itemID") or "").strip()
        if not iid:
            continue
        cert = itemid_to_cert.get(iid)
        if not cert:
            skipped.append((iid, "cert#未解決(商品管理シートI列に無い)→生成不可"))
            continue
        if cert in seen:
            continue
        seen.add(cert)
        certs.append(cert)
        key = itemid_to_key.get(iid)
        if key:
            forced[cert] = key
        if r.get("cost"):
            try:
                _c = float(r["cost"])
            except (TypeError, ValueError):
                _c = None
            if _c is not None:
                # ★2026-09-03: 仕入値がありえない額なら **生成に回さない**。
                #   実害: 仕入元のダミー価格 ¥1,111,111 をそのまま拾い、cost-plus で
                #   $11,707.98 の Revise 行を作った (現在価格 $83.98 の139倍)。
                #   判定は pricing_engine.cost_sanity (全カテゴリ共通・しきい値は global.yaml)。
                _ng = _cost_sanity(_c)
                if _ng:
                    certs.pop()
                    seen.discard(cert)
                    forced.pop(cert, None)
                    skipped.append((iid, "%s→生成不可" % _ng))
                    continue
                cost[cert] = _c
        if r.get("supply_url"):
            supply[cert] = r["supply_url"]
    return {"certs": certs, "forced": forced, "cost": cost, "supply_url": supply}, skipped


def _read_restock_confirmed():
    """「RESTOCK確定」タブ → [{itemID, cost, supply_url}] (I/O)。

    RESTOCK状態=実行済(=既に再出品済)は除外する。一度再出品したものを毎回再Reviseし続けると
    在庫切れ(supply無し)になった出品まで qty=1 で出し直してしまう(2026-06-22 ユーザー指摘)。
    再出品後の取下げは在庫監視くんが担うので、♻ は **未だ出していない分(入稿待ち/新規)だけ**生成する。
    売れ直し(qty=0)は writeback で「入稿待ち」へ戻るため再度拾われる(取りこぼしなし)。
    """
    from sheet_io import read_tab
    rows = read_tab("RESTOCK確定")
    out, skipped_done = _pending_from_confirmed_rows(rows)
    if skipped_done:
        print(f"  ⏭ 実行済(再出品済) {skipped_done}件は生成スキップ(再出品の二重化防止)")
    return out


def _pending_from_confirmed_rows(rows):
    """RESTOCK確定の2d行 → (未出品リスト[{itemID,cost,supply_url}], 実行済skip件数) (純関数)。

    RESTOCK状態に「実行済」を含む行は除外(=一度再出品したものは再生成しない)。
    """
    if not rows or len(rows) < 2:
        return [], 0
    h = rows[0]

    def _i(name):
        return h.index(name) if name in h else None
    ii, ci, ui, si = _i("itemID"), _i("最安¥"), _i("仕入URL"), _i("RESTOCK状態")
    out, skipped_done = [], 0
    for r in rows[1:]:
        if not any(r):
            continue
        status = (r[si] if si is not None and si < len(r) else "") or ""
        # 終了済も「もう作らない」側。押しても revise では戻せない (2026-09-04)。
        if "実行済" in status or "終了済" in status:
            skipped_done += 1
            continue
        out.append({"itemID": (r[ii] if ii is not None and ii < len(r) else ""),
                    "cost": (r[ci] if ci is not None and ci < len(r) else ""),
                    "supply_url": (r[ui] if ui is not None and ui < len(r) else "")})
    return out, skipped_done


def count_workload(rows=None, itemid_to_cert=None):
    """押したら『何件ぶん CSV が出るか』を数える (パネルのヒント用・2026-09-01).

    eBay は1回も叩かない。材料は「RESTOCK確定」タブと 商品管理シートの cert だけ。
    判定は本体と同じ `_pending_from_confirmed_rows` を通す (二重実装しない)。
    rows を渡せばスプシを読まない (同じ subprocess で writeback と読みを共有するため)。

    ★2026-09-04 ユーザー指摘「ヒントテキストでは7件やけど (実際は5件しか出ない)」。
      cert# が引けない行は **生成できない** のに件数に入れていた。実測でその差は
      2件 (B列=9999 の見送り / 商品管理シートに itemID の行が無い分)。
      押す前に「本当に何件出るか」が分かるよう、引けない分は blocked として分ける。
      itemid_to_cert を渡さない時だけ自分で読む (呼び側が既に持っていれば読まない)。
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        if rows is None:
            from sheet_io import read_tab
            rows = read_tab("RESTOCK確定")
        pending, done = _pending_from_confirmed_rows(rows)
        if itemid_to_cert is None:
            try:
                from sheet_io import build_cert_map, _product_ws
                itemid_to_cert = build_cert_map(_product_ws().get_all_values())
            except Exception:                                  # noqa: BLE001
                itemid_to_cert = None
        blocked = 0
        if itemid_to_cert is not None:
            blocked = sum(1 for p in pending
                          if not itemid_to_cert.get((p.get("itemID") or "").strip()))
        return {"actionable": len(pending) - blocked, "done": done,
                "blocked": blocked, "total": len(pending) + done}
    except Exception as e:                                     # noqa: BLE001
        return {"error": "%s: %s" % (type(e).__name__, e)}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from sheet_io import product_index, build_cert_map, _product_ws
    import psa_restock_revise_csv as rv

    rows = _read_restock_confirmed()
    if not rows:
        sys.exit("「RESTOCK確定」タブが空。先に PSA再仕入れ照合→視覚確証で確定してください。")
    keymap, _itemrow, _certmap = product_index()
    itemid_to_cert = build_cert_map(_product_ws().get_all_values())
    inp, skipped = build_restock_input(rows, itemid_to_cert, keymap)
    print(f"RESTOCK確定 {len(rows)}件 → cert解決 {len(inp['certs'])} / forced KEY {len(inp['forced'])} / skip {len(skipped)}")
    for s in skipped[:10]:
        print("  ⏭", s)
    if not inp["certs"]:
        sys.exit("cert解決0件 → 生成対象なし。")

    json_path = os.path.join(_CSV_OUT_DIR, "restock_input.json")
    os.makedirs(_CSV_OUT_DIR, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(inp, f, ensure_ascii=False, indent=2)

    # psa_to_csv を RESTOCK入力モードで実行(新コア生成・forced変種)。Selenium PSA scrape は新規と同じ。
    # 並走安全化: 新規出品と別 Chrome profile(PSA_PROFILE_DIR)→ profile競合回避。
    restock_profile = os.path.join(os.path.dirname(_CSV_OUT_DIR.rstrip("/\\")), "chrome_profile_psa_restock")
    env = dict(os.environ, PSA_RESTOCK_INPUT=json_path, TCG_USE_NEW_GEN="1", PSA_NO_SHUFFLE="1",
               PSA_PROFILE_DIR=restock_profile)
    # 並走安全化: 「最新」でなく **本実行で生成された** tcg_upload を差分で特定(新規出品の並走CSV誤掴み防止)
    before = set(glob.glob(os.path.join(_CSV_OUT_DIR, "tcg_upload_*.csv")))
    # 新規 psa_to_csv.py は「触らない」(ユーザー指示 2026-06-20)。RESTOCK は psa_to_csv の fork
    # (psa_restock_csv.py) を使う。fork = psa_to_csv のコピー + RESTOCK入力モード/別profile/isatty。
    print("▶ psa_restock_csv(RESTOCK fork)で Add CSV生成中...(Selenium・新規と同一生成・別profile)")
    r = subprocess.run([sys.executable, "psa_restock_csv.py"], cwd=_TCG_DIR, env=env)
    if r.returncode != 0:
        sys.exit(f"psa_restock_csv 異常終了(returncode={r.returncode})")
    new_files = sorted(set(glob.glob(os.path.join(_CSV_OUT_DIR, "tcg_upload_*.csv"))) - before,
                       key=os.path.getmtime)
    if not new_files:
        sys.exit("本実行で生成された Add CSV(tcg_upload_*.csv)が見つからない")
    add_csv = new_files[-1]   # 本実行で新規生成された分だけから選ぶ(並走の他CSVを掴まない)
    print(f"✅ Add CSV生成: {add_csv}")
    # Add→Revise 変換は **control_panel の post-chain (excluder/title-fix/dedup) の後** に実施する
    # (control_panel が restock_revise=True を見て _run_restock_revise_for_latest_csv を呼ぶ)。
    # ここで変換すると dedup 前=赤字/重複/旧タイトルが混入する(2026-06-19 バグ)→ 変換しない。
    print("→ post-chain(除外/タイトル補強/重複除外)後に Revise CSV を自動生成します。")


if __name__ == "__main__":
    main()
