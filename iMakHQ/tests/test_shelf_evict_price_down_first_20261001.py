"""棚②: 出品時から値下げしていない出品は落とさず値下げ候補へ (2026-10-01 ユーザー「値下げ履歴ね」)。

値段は仕入値に合わせて毎日上下するので、回数ではなく「出品時からの差し引き」で見る (リバイスくん回答)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import shelf_evict as S  # noqa: E402


def test_net_change():
    assert round(S.net_change({"first_price": 240.98, "now_price": 200.98}), 3) == -0.166
    assert S.net_change({"first_price": 0, "now_price": 1}) is None
    assert S.net_change({}) is None


def test_needs_price_down_first():
    assert S.needs_price_down_first("1", None) is True              # 台帳が無い = 判断できない = 落とさない
    assert S.needs_price_down_first("1", {}) is True                # 載っていない
    assert S.needs_price_down_first("1", {"1": None}) is True
    assert S.needs_price_down_first("1", {"1": 0.21}) is True       # 上がっている
    assert S.needs_price_down_first("1", {"1": -0.007}) is True     # ほぼ同じ
    assert S.needs_price_down_first("1", {"1": -0.166}) is False    # 17% 下げても売れない = 落とす
    assert S.needs_price_down_first(1, {"1": -0.05}) is False


def test_load_price_downs(tmp_path):
    assert S.load_price_downs(str(tmp_path / "none.json")) is None
    p = tmp_path / "c.json"
    p.write_text('{"items": {"820": {"first_price": 100, "now_price": 90}, "821": {}}}', encoding="utf-8")
    d = S.load_price_downs(str(p))
    assert round(d["820"], 2) == -0.10 and d["821"] is None


def test_pick_holds_stale_items_without_price_down(monkeypatch):
    rows = [{"item_id": "A", "title": "PSA 10 One Piece A"}, {"item_id": "B", "title": "PSA 10 One Piece B"}]
    monkeypatch.setattr(S, "tier_of", lambda r, **k: S.TIER_STALE)
    monkeypatch.setattr(S, "is_dead_shelf", lambda r: False)
    held = []
    picked, _ = S.pick(rows, 1e9, lambda r: 100.0, only_tier=S.TIER_STALE,
                       price_downs={"A": -0.2, "B": 0.1}, held=held)
    assert [r["item_id"] for _t, r in picked] == ["A"]
    assert [r["item_id"] for r in held] == ["B"]
    picked2, _ = S.pick(rows, 1e9, lambda r: 100.0, only_tier=S.TIER_STALE)   # 表示用は今までどおり
    assert len(picked2) == 2
