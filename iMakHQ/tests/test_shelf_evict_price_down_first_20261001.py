"""棚②: 一度も値下げしていない出品は落とさず値下げ候補へ (2026-10-01 ユーザー「値下げ履歴ね」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import shelf_evict as S  # noqa: E402


def test_needs_price_down_first():
    assert S.needs_price_down_first("1", None) is True             # 台帳が無い = 判断できない = 落とさない
    assert S.needs_price_down_first("1", {}) is True               # 一度も値下げしていない
    assert S.needs_price_down_first("1", {"1": 0}) is True
    assert S.needs_price_down_first("1", {"1": 1}) is False        # 1回下げても売れない = 落とす
    assert S.needs_price_down_first(1, {"1": 2}) is False


def test_load_price_downs_missing_is_none(tmp_path):
    assert S.load_price_downs(str(tmp_path / "none.json")) is None
    p = tmp_path / "c.json"
    p.write_text('{"items": {"820": {"downs": 2}, "821": {}}}', encoding="utf-8")
    assert S.load_price_downs(str(p)) == {"820": 2, "821": 0}


def test_pick_holds_stale_items_without_price_down(monkeypatch):
    rows = [{"item_id": "A", "title": "PSA 10 One Piece A"}, {"item_id": "B", "title": "PSA 10 One Piece B"}]
    monkeypatch.setattr(S, "tier_of", lambda r, **k: S.TIER_STALE)
    monkeypatch.setattr(S, "is_dead_shelf", lambda r: False)
    held = []
    picked, total = S.pick(rows, 1e9, lambda r: 100.0, only_tier=S.TIER_STALE,
                           price_downs={"A": 1}, held=held)
    assert [r["item_id"] for _t, r in picked] == ["A"]
    assert [r["item_id"] for r in held] == ["B"]
    # 表示用の呼び出し (price_downs を渡さない) は今までどおり
    picked2, _ = S.pick(rows, 1e9, lambda r: 100.0, only_tier=S.TIER_STALE)
    assert len(picked2) == 2
