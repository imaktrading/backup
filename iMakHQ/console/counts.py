# -*- coding: utf-8 -*-
"""出品くん Console: 残り件数を数えて JSON を1行出す (2026-09-15)。

control_panel.py の refresh_hoju_badge が subprocess で回している集計と **同じ関数・同じキー**。
どれも eBay もスクレイプも叩かない (材料は funnel CSV・スプシ・キャッシュ)。
キーが control_panel とずれたら tests/test_console_home_20260915.py が赤になる。
"""
import json
import os
import sys
import time

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)


def hits_quota(v):
    """結果のどこかに 429 (読み取り上限) のエラーがあるか (入れ子の error も見る)。純関数。"""
    if isinstance(v, dict):
        return any(("429" in str(x) or "Quota exceeded" in str(x)) if k == "error" else hits_quota(x)
                   for k, x in v.items())
    return False


def _restock_tab():
    """RESTOCK確定タブは 1回だけ読んで両方に渡す (control_panel と同じ)。読めなければ None。"""
    try:
        from sheet_io import read_tab
        return read_tab("RESTOCK確定")
    except Exception:                                          # noqa: BLE001
        return None


def main():
    rk = {"rows": None, "read": False}

    def restock_rows():
        if not rk["read"]:
            rk["rows"], rk["read"] = _restock_tab(), True
        return rk["rows"]

    fns = {
        "hoju": lambda: __import__("psa_hoju_fill").count_workload(),
        "newcand": lambda: __import__("newcand_confirm").count_workload(),
        "newcand_high": lambda: __import__("newcand_confirm").count_workload_high(),
        "kuji": lambda: __import__("ichibankuji_restock").count_workload(),
        "cull": lambda: __import__("cull_end").count_workload(),
        "shelf": lambda: __import__("shelf_evict").count_workload(),
        "restock": lambda: __import__("sold_restock").count_workload(),
        "ut": lambda: __import__("ut_hoju_fill").count_workload(),
        "ut_identify": lambda: __import__("ut_identify").count_workload(),
        "psa_gate": lambda: __import__("psa_resource_gate").count_workload(),
        "restock_build": lambda: __import__("psa_restock_build").count_workload(restock_rows()),
        "restock_wb": lambda: __import__("psa_restock_writeback").count_workload(restock_rows()),
    }
    d = {}

    def grab(key):
        try:
            d[key] = fns[key]()
        except Exception as e:                                 # noqa: BLE001
            d[key] = {"error": "%s: %s" % (type(e).__name__, e)}

    for key in fns:
        grab(key)

    # ★2026-09-15 実測: 12項目がまとめて同じスプシを読むので、後半 (UT / UT 特定 / 売れた分の補充 /
    #   くじ再仕入れ) が 1分の読み取り上限 (429) に当たった。上限は1分で開くので、待ってその項目だけ数え直す。
    retry = [k for k, v in d.items() if hits_quota(v)]
    if retry:
        time.sleep(65)
        if "restock_build" in retry or "restock_wb" in retry:
            rk["read"] = False
        for key in retry:
            grab(key)
    print(json.dumps(d, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
