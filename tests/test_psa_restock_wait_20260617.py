"""Regression: 2026-06-17 — PSA再仕入れ 待ち台帳(End候補を消さず毎回再チェック)。

再仕入れ不能(End候補)= 今 Mercari/SNKRDUNK に出品が無いだけ。供給は動的なので台帳に蓄積し、
ファネルの需要減衰に関係なく毎回再チェック → 出品が出たら「復活可(RESTOCK)」。目視済(KEY付与済)
なので再目視不要。state同期の安全原則(消さない/復活を見逃さない)。
"""
import importlib.util
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"


def _load(name):
    p = _TOOLS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name + "_t", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _ec(iid, **kw):
    d = {"itemID": iid, "key": "", "card_no": "", "title": "", "ebay_url": ""}
    d.update(kw)
    return d


def test_reconcile_accumulates_and_revives():
    w = _load("psa_restock_wait")
    led, st = w.reconcile([], [_ec("1", key="OP01-016"), _ec("2", key="P-041")], set(), "2026-06-17")
    assert st["new"] == 2 and st["total_wait"] == 2
    # 次回: 1は継続(再チェック+1)、2は供給戻り→復活可
    led, st = w.reconcile(led, [_ec("1", key="OP01-016")], {"2"}, "2026-06-18")
    by = {r["itemID"]: r for r in led}
    assert st["still_waiting"] == 1 and st["revived"] == 1
    assert by["1"]["再チェック回数"] == "2" and by["1"]["status"] == w.ST_WAIT
    assert by["1"]["初出日"] == "2026-06-17"
    assert by["2"]["status"] == w.ST_REVIVED


def test_recheck_targets_excludes_revived():
    w = _load("psa_restock_wait")
    led, _ = w.reconcile([], [_ec("1"), _ec("2")], set(), "2026-06-17")
    led, _ = w.reconcile(led, [_ec("1")], {"2"}, "2026-06-18")   # 2 復活
    tids = [t["itemID"] for t in w.recheck_targets(led)]
    assert tids == ["1"]        # 待ちのみ再チェック、復活可は対象外


def test_tab_roundtrip_revived_on_top():
    w = _load("psa_restock_wait")
    led, _ = w.reconcile([], [_ec("1"), _ec("2")], set(), "2026-06-17")
    led, _ = w.reconcile(led, [], {"2"}, "2026-06-18")
    rows = w.to_tab_rows(led)
    assert rows[0] == w.LEDGER_HEADER
    assert rows[1][4] == "2"    # 復活可が先頭(要対応)
    assert len(w.ledger_from_rows(rows)) == 2
    assert w.ledger_from_rows([["foo"], ["x"]]) == []


def test_gate_wires_restock_wait():
    src = (_TOOLS / "psa_resource_gate.py").read_text(encoding="utf-8")
    assert "recheck_targets" in src                 # 待ち台帳を再チェックに合流
    assert "wait_end" in src and "wait_resourceable" in src
    assert 'write_rows_to_tab("再仕入れ待ち"' in src   # End候補を台帳に記録
    # 合流は確認ゲートの後・探索の前(目視skip)
    i_merge = src.index("再チェックに合流")
    i_search = src.index("メルカリ最安取得")
    assert i_merge < i_search


def test_held_unknown_accumulated_as_new(_prw=None):
    """★2026-07-24: 在庫不明(取得失敗)は台帳に無ければ ST_UNKNOWN で新規蓄積(孤児化防止)。"""
    prw = _load("psa_restock_wait")
    held = [{"itemID": "H1", "key": "P-041", "card_no": "P-041", "title": "Luffy", "ebay_url": "u"}]
    ledger, stats = prw.reconcile([], [], set(), "2026-07-24", held_candidates=held)
    assert stats["unknown"] == 1
    row = next(r for r in ledger if r["itemID"] == "H1")
    assert row["status"] == prw.ST_UNKNOWN
    # recheck 対象に含まれる(毎回再取得)
    assert any(t["itemID"] == "H1" for t in prw.recheck_targets(ledger))


def test_held_does_not_downgrade_known_wait():
    """在庫不明が既存の ST_WAIT(供給なし確定)を downgrade しない(recheck++のみ)。"""
    prw = _load("psa_restock_wait")
    prev = [{"初出日": "2026-07-01", "最終確認日": "2026-07-01", "status": prw.ST_WAIT,
             "再チェック回数": "5", "itemID": "W1", "KEY": "", "card_no": "", "title": "", "ebay_url": ""}]
    held = [{"itemID": "W1", "key": "", "card_no": "", "title": "", "ebay_url": ""}]
    ledger, stats = prw.reconcile(prev, [], set(), "2026-07-24", held_candidates=held)
    row = next(r for r in ledger if r["itemID"] == "W1")
    assert row["status"] == prw.ST_WAIT           # downgrade しない
    assert row["再チェック回数"] == "6"            # recheck は進む


def test_held_becomes_revived_when_supply_returns():
    """在庫不明→次回 再仕入れ可なら復活可に昇格。"""
    prw = _load("psa_restock_wait")
    prev = [{"初出日": "2026-07-20", "最終確認日": "2026-07-20", "status": prw.ST_UNKNOWN,
             "再チェック回数": "2", "itemID": "U1", "KEY": "", "card_no": "", "title": "", "ebay_url": ""}]
    ledger, stats = prw.reconcile(prev, [], {"U1"}, "2026-07-24")
    row = next(r for r in ledger if r["itemID"] == "U1")
    assert row["status"] == prw.ST_REVIVED
