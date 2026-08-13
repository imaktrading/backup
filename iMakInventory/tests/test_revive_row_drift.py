"""復活 (revive) queue の行ズレ耐性 regression test.

★ 2026-08-13 制定。実害: pending_revive は row_index でシートと突合していたが、シートは
行の挿入/削除で常時ずれるため、queue に積んだ時の row_index が数日で別商品を指す。結果、
145 件中 84 件が item_id_changed / row_not_found_in_sheet として **永久に deferred**、
08-08〜08-13 の 6 日間 復活が 1 件も実行されなかった (仕入元に在庫が戻っても eBay は qty=0
のまま = 売れない)。queue も drain されず単調増加。

仕様:
- row_index がずれていても itemID でシート上の行を引き直す。
- 同 itemID が複数行あるときは URL 一致で一意に決まる場合のみ採用、決まらなければ
  fail-closed (誤った行で復活させない)。
- itemID がシートのどこにも無い entry は、一定日数経過後に archive へ退避 (queue 肥大化防止、
  証跡は discarded_revive.jsonl に残す)。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sheet_row(row_index, item_id, url, sold=""):
    return {"row_index": row_index, "item_id": item_id, "url": url,
            "current_sold": sold, "title": "t", "err_flag_prev": "", "checked_at": ""}


def _collect(queue, rows, label="SHEET"):
    import ebay_actions.revive_csv_generator as rg
    with patch.object(rg, "read_pending_revive", lambda: queue), \
         patch.object(rg, "open_sheet_by_id", lambda *a, **k: object()), \
         patch.object(rg, "get_listings_worksheet", lambda *a, **k: object()), \
         patch.object(rg, "read_listings_rows", lambda ws, **k: rows), \
         patch.object(rg, "build_sheet_key_map", lambda rows: {}):
        return rg.collect_from_pending_revive(
            single_sheet_id="sid", single_sheet_label=label)


@pytest.mark.offline
def test_row_shifted_is_relocated_by_item_id():
    """行がずれても itemID で引き直して候補に載る (恒久 deferred にしない)."""
    queue = [{"sheet": "SHEET", "row_index": 1455, "item_id": "IID1",
              "url": "https://jp.mercari.com/shops/product/AAA", "ts": "2026-08-12T14:47:13"}]
    rows = [_sheet_row(1338, "IID1", "https://jp.mercari.com/shops/product/AAA"),
            _sheet_row(1455, "OTHER", "https://jp.mercari.com/shops/product/ZZZ")]
    cands, skipped, _ = _collect(queue, rows)
    assert len(cands) == 1 and skipped == []
    assert cands[0]["row_index"] == 1338


@pytest.mark.offline
def test_duplicate_item_id_resolved_by_url():
    """同 itemID 複数行 → URL 一致で一意に決まればその行を使う."""
    queue = [{"sheet": "SHEET", "row_index": 99, "item_id": "IID1",
              "url": "https://jp.mercari.com/shops/product/BBB", "ts": "2026-08-12T14:47:13"}]
    rows = [_sheet_row(10, "IID1", "https://jp.mercari.com/shops/product/AAA"),
            _sheet_row(20, "IID1", "https://jp.mercari.com/shops/product/BBB")]
    cands, skipped, _ = _collect(queue, rows)
    assert len(cands) == 1 and cands[0]["row_index"] == 20


@pytest.mark.offline
def test_ambiguous_rows_are_failclosed():
    """URL でも一意に決まらない → 復活させない (誤った行で qty=1 に戻さない)."""
    queue = [{"sheet": "SHEET", "row_index": 99, "item_id": "IID1",
              "url": "", "ts": "2026-08-12T14:47:13"}]
    rows = [_sheet_row(10, "IID1", "https://jp.mercari.com/shops/product/AAA"),
            _sheet_row(20, "IID1", "https://jp.mercari.com/shops/product/BBB")]
    cands, skipped, _ = _collect(queue, rows)
    assert cands == []
    assert skipped[0]["skip_reason"] == "ambiguous_rows_for_item_id"


@pytest.mark.offline
def test_item_id_absent_is_reported_not_silently_kept():
    queue = [{"sheet": "SHEET", "row_index": 99, "item_id": "GONE",
              "url": "https://x", "ts": "2026-08-01T00:00:00"}]
    rows = [_sheet_row(10, "IID1", "https://jp.mercari.com/shops/product/AAA")]
    cands, skipped, _ = _collect(queue, rows)
    assert cands == []
    assert skipped[0]["skip_reason"] == "row_not_found_by_item_id"


# ============================================================================
# prune (queue 肥大化防止)
# ============================================================================
@pytest.mark.offline
def test_prune_moves_only_old_unresolvable_entries(tmp_path):
    import ebay_actions.revive_csv_generator as rg
    pending = tmp_path / "pending_revive.jsonl"
    discarded = tmp_path / "discarded_revive.jsonl"
    old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
    new_ts = datetime.now().isoformat(timespec="seconds")
    pending.write_text("\n".join([
        json.dumps({"item_id": "OLD_GONE", "ts": old_ts}),
        json.dumps({"item_id": "NEW_GONE", "ts": new_ts}),
        json.dumps({"item_id": "ALIVE", "ts": old_ts}),
    ]) + "\n", encoding="utf-8")
    skipped = [{"item_id": "OLD_GONE", "ts": old_ts, "skip_reason": "row_not_found_by_item_id"},
               {"item_id": "NEW_GONE", "ts": new_ts, "skip_reason": "row_not_found_by_item_id"},
               {"item_id": "ALIVE", "ts": old_ts, "skip_reason": "d_marked_sold"}]
    with patch.object(rg, "PENDING_REVIVE_FILE", pending), \
         patch.object(rg, "DISCARDED_REVIVE_FILE", discarded):
        moved = rg.prune_unresolvable_pending_revive(skipped)
        rest = [json.loads(l)["item_id"] for l in pending.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert moved == 1
    assert rest == ["NEW_GONE", "ALIVE"]          # 新しい/解決可能なものは残す
    arch = [json.loads(l) for l in discarded.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert arch[0]["item_id"] == "OLD_GONE"        # 証跡は残す (silent drop 禁止)


@pytest.mark.offline
def test_prune_noop_when_nothing_expired(tmp_path):
    import ebay_actions.revive_csv_generator as rg
    pending = tmp_path / "pending_revive.jsonl"
    pending.write_text(json.dumps({"item_id": "A", "ts": datetime.now().isoformat()}) + "\n",
                       encoding="utf-8")
    with patch.object(rg, "PENDING_REVIVE_FILE", pending):
        assert rg.prune_unresolvable_pending_revive([]) == 0


# ============================================================================
# GetItem の raw_xml cap (復活が永久 0 件になっていた最後の原因)
# ============================================================================
@pytest.mark.offline
def test_start_price_parsed_when_tag_is_beyond_2000_chars():
    """StartPrice が 2000 文字より後ろにあっても取れる (cap で切ってはいけない).

    ★ 2026-08-13: raw_xml_cap 既定 2000 のまま GetItem を呼んでいたため price=None →
      採算 gate が skip_no_price → 復活が実行されない。09:30 cycle の deferred 149 件中
      61 件がこれだった。同型は単品 verify の QuantitySold 取りこぼし (commit 0b7f566)。
    """
    import ebay_actions.revive_csv_generator as rg
    long_xml = ("<Item>" + "<Filler>x</Filler>" * 300
                + "<StartPrice currencyID='USD'>255.98</StartPrice>"
                + "<Quantity>1</Quantity><QuantitySold>0</QuantitySold></Item>")
    assert long_xml.index("<StartPrice") > 2000        # 前提: cap の外側にある

    captured = {}

    def _fake_call(name, body, access_token=None, **kw):
        captured.update(kw)
        return {"success": True, "error_code": None, "raw_xml": long_xml}

    import ebay_actions.trading_api_client as tc
    with patch.object(tc, "_call_trading", _fake_call):
        price, qty = rg._fetch_ebay_start_price_and_qty("358870181848", "tok")
    assert captured.get("raw_xml_cap") is None, "raw_xml_cap を外していない (price が取れなくなる)"
    assert price == 255.98


# ============================================================================
# 急増ガードは「新規」で判定する (backlog 自体で発火して永久 HOLD にしない)
# ============================================================================
@pytest.mark.offline
def test_burst_guard_counts_only_new_candidates():
    import ebay_actions.revive_csv_generator as rg
    now = datetime(2026, 8, 13, 12, 0, 0)
    old = (now - timedelta(days=4)).isoformat(timespec="seconds")
    fresh = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    cands = [{"queue_ts": old} for _ in range(40)] + [{"queue_ts": fresh} for _ in range(3)]
    assert rg.count_new_candidates(cands, now) == 3      # backlog 40 は数えない


@pytest.mark.offline
def test_unparseable_queue_ts_counts_as_new():
    """queue_ts が読めないものは新規扱い = ガードが厳しい側に倒れる."""
    import ebay_actions.revive_csv_generator as rg
    now = datetime(2026, 8, 13, 12, 0, 0)
    assert rg.count_new_candidates([{"queue_ts": ""}, {}], now) == 2


@pytest.mark.offline
def test_per_cycle_cap_is_bounded_but_not_crippling():
    """上限は「暴走時の天井」であって backlog を何日も残す絞りではない.

    ★ 2026-08-13: 一時 10 にしたが、約 50 件の backlog に 5 cycle (≒1日) かかる = その間
      売れない。誤復活を止めるのは新規基準の急増ガード。上限は 1 cycle で通常量を捌ける値。
    """
    import ebay_actions.revive_csv_generator as rg
    assert rg.DEFAULT_MAX_PER_CYCLE is not None      # 無制限にはしない
    assert 30 <= rg.DEFAULT_MAX_PER_CYCLE <= 100


@pytest.mark.offline
def test_queue_duplicates_collapse_to_latest():
    """同 itemID の再投入は最新 1 件に畳む (候補数・ガード数え上げの水増し防止)."""
    queue = [{"sheet": "SHEET", "row_index": 10, "item_id": "IID1", "url": "https://a",
              "ts": "2026-08-10T00:00:00"},
             {"sheet": "SHEET", "row_index": 10, "item_id": "IID1", "url": "https://a",
              "ts": "2026-08-13T14:00:00"}]
    rows = [_sheet_row(10, "IID1", "https://a")]
    cands, skipped, _ = _collect(queue, rows)
    assert len(cands) == 1
    assert cands[0]["queue_ts"] == "2026-08-13T14:00:00"      # 最新を採用


@pytest.mark.offline
def test_burst_window_uses_last_run_not_fixed_24h():
    """新規判定は「前回 revive 実行以降」。24h 固定窓だと数 cycle 分をまとめて数えてしまう."""
    import ebay_actions.revive_csv_generator as rg
    now = datetime(2026, 8, 13, 13, 30, 0)
    last_run = datetime(2026, 8, 13, 9, 30, 0)               # 前 cycle
    cands = ([{"queue_ts": "2026-08-13T07:30:00"} for _ in range(50)]   # 時間窓内だが前回実行より前
             + [{"queue_ts": "2026-08-13T10:30:00"} for _ in range(2)])  # 前回実行以降 = 新規
    assert rg.count_new_candidates(cands, now, since=last_run) == 2
    # fallback (前回実行が記録されていない初回) は時間窓で数える = 同じ入力でも 52
    assert rg.count_new_candidates(cands, now) == 52


@pytest.mark.offline
def test_last_run_state_roundtrip(tmp_path):
    import ebay_actions.revive_csv_generator as rg
    f = tmp_path / "revive_last_run.json"
    ts = datetime(2026, 8, 13, 13, 30, 0)
    with patch.object(rg, "LAST_REVIVE_RUN_FILE", f), \
         patch.object(rg, "DECISION_LOG_DIR", tmp_path):
        assert rg.load_last_revive_run("SHEET") is None
        rg.save_last_revive_run("SHEET", ts)
        assert rg.load_last_revive_run("SHEET") == ts
        assert rg.load_last_revive_run("LOW") is None        # label 別に持つ
