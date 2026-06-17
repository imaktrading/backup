"""Regression: 2026-06-17 — PSA再仕入れ 不一致 PDCA。

確認ゲートで OFF にした「①現物 vs ②catalog 不一致」を台帳に蓄積し、原因別に振り分け、
前回比トレンド(新規/再発/再燃/解決)を出す。Check止まりにしない(pdca_spiral_up_expectation)。

純関数(reconcile/route_buckets/to_tab_rows/ledger_from_rows/build_catalog_request_md)を固定。
"""
import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "psa_mismatch_pdca.py"
_spec = importlib.util.spec_from_file_location("psa_mismatch_pdca_t", _P)
pdca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pdca)


def _rej(iid, reason, **kw):
    d = {"itemID": iid, "reason": reason, "cert": "", "key": "", "card_no": "",
         "title": "", "psa_image": "", "catalog_image": "", "ebay_url": ""}
    d.update(kw)
    return d


def test_classify_route_maps_known_and_unknown():
    assert pdca.classify_route("catalog") == "catalog"
    assert pdca.classify_route("CERT") == "cert"
    assert pdca.classify_route("listing") == "listing"
    assert pdca.classify_route("") == "unknown"
    assert pdca.classify_route("???") == "unknown"


def test_reconcile_new_then_recurring_and_resolved():
    led, st = pdca.reconcile([], [_rej("111", "catalog", card_no="OP11-106"),
                                  _rej("222", "cert")], set(), "2026-06-17")
    assert st["new"] == 2 and st["open"] == 2
    # round2: 111 再発, 222 解決(confirmed), 333 新規
    led2, st2 = pdca.reconcile(led, [_rej("111", "catalog"), _rej("333", "listing")],
                               {"222"}, "2026-06-18")
    by = {r["itemID"]: r for r in led2}
    assert st2["recurring"] == 1 and st2["new"] == 1 and st2["resolved"] == 1
    assert by["111"]["再発回数"] == "2"
    assert by["222"]["status"] == "解決"
    assert by["111"]["初出日"] == "2026-06-17"   # 初出日は保持
    assert by["333"]["振り分け先"] == pdca.ROUTE_LABEL["listing"]
    assert st2["open"] == 2   # 111, 333 が未対処 (222は解決)


def test_reconcile_reopen_after_resolved():
    led, _ = pdca.reconcile([], [_rej("222", "cert")], set(), "2026-06-17")
    led, _ = pdca.reconcile(led, [], {"222"}, "2026-06-18")           # 解決
    led, st = pdca.reconcile(led, [_rej("222", "cert")], set(), "2026-06-19")  # 再燃
    assert st["reopened"] == 1
    assert {r["itemID"]: r for r in led}["222"]["status"] == "未対処"


def test_route_buckets_excludes_resolved():
    led, _ = pdca.reconcile([], [_rej("111", "catalog"), _rej("222", "cert")],
                            set(), "2026-06-17")
    led, _ = pdca.reconcile(led, [], {"222"}, "2026-06-18")   # 222 解決
    b = pdca.route_buckets(led)
    assert [r["itemID"] for r in b.get("catalog", [])] == ["111"]
    assert "cert" not in b or all(r["status"] != "解決" for r in b["cert"])


def test_tab_roundtrip_and_catalog_md():
    led, _ = pdca.reconcile([], [_rej("111", "catalog", card_no="OP11-106",
                                       psa_image="P", catalog_image="C")], set(), "2026-06-17")
    rows = pdca.to_tab_rows(led)
    assert rows[0] == pdca.LEDGER_HEADER
    back = pdca.ledger_from_rows(rows)
    assert back[0]["itemID"] == "111" and back[0]["原因"] == "catalog"
    md = pdca.build_catalog_request_md(pdca.route_buckets(led)["catalog"], "2026-06-17")
    assert "OP11-106" in md and "依頼日: 2026-06-17" in md and "現物" in md


def test_ledger_from_rows_rejects_foreign_header():
    assert pdca.ledger_from_rows([["foo", "bar", "baz"], ["1", "2", "3"]]) == []
    assert pdca.ledger_from_rows([]) == []
