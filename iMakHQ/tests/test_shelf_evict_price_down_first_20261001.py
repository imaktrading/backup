"""棚②: 出品時から値下げしていない出品は落とさず値下げ候補へ (2026-10-01 ユーザー「値下げ履歴ね」)。

値段は仕入値に合わせて毎日上下するので、回数ではなく「出品時からの差し引き」で見る (リバイスくん回答)。
％だと価格でムラが出るので、価格帯ごとの金額で決める (ユーザー「％だと、価格によってムラがでるね」)。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import shelf_evict as S  # noqa: E402

B = [[50, 5], [200, 15], [500, 30], [None, 50]]


def test_down_needed_by_band():
    assert S.down_needed(20, B) == 5
    assert S.down_needed(150, B) == 15
    assert S.down_needed(300, B) == 30
    assert S.down_needed(1200, B) == 50


def test_needs_price_down_first():
    assert S.needs_price_down_first("1", None, B) is True                 # 台帳が無い = 判断できない = 落とさない
    assert S.needs_price_down_first("1", {}, B) is True                   # 載っていない
    assert S.needs_price_down_first("1", {"1": None}, B) is True
    assert S.needs_price_down_first("1", {"1": (148.98, 179.98)}, B) is True   # 上がっている
    assert S.needs_price_down_first("1", {"1": (283.98, 281.98)}, B) is True   # $2 しか下がっていない ($30 要る)
    assert S.needs_price_down_first("1", {"1": (240.98, 200.98)}, B) is False  # $40 下げても売れない = 落とす
    assert S.needs_price_down_first("1", {"1": (20.0, 16.0)}, B) is True       # $4 ($5 要る)
    assert S.needs_price_down_first(1, {"1": (20.0, 15.0)}, B) is False


def test_load_price_downs(tmp_path):
    assert S.load_price_downs(str(tmp_path / "none.json")) is None
    p = tmp_path / "c.json"
    p.write_text('{"items": {"820": {"first_price": 100, "now_price": 90}, "821": {}}}', encoding="utf-8")
    d = S.load_price_downs(str(p))
    assert d["820"] == (100.0, 90.0) and d["821"] is None


def test_bands_from_settings_file(tmp_path):
    assert S.load_price_down_bands(str(tmp_path / "none.json")) == S.DEFAULT_PRICE_DOWN_BANDS
    p = tmp_path / "s.json"
    p.write_text('{"price_down_bands": [[100, 10], [null, 40]]}', encoding="utf-8")
    assert S.load_price_down_bands(str(p)) == [[100, 10], [None, 40]]


def test_pick_holds_stale_items_without_price_down(monkeypatch):
    rows = [{"item_id": "A", "title": "PSA 10 One Piece A"}, {"item_id": "B", "title": "PSA 10 One Piece B"}]
    monkeypatch.setattr(S, "tier_of", lambda r, **k: S.TIER_STALE)
    monkeypatch.setattr(S, "is_dead_shelf", lambda r: False)
    monkeypatch.setattr(S, "load_price_down_bands", lambda *a, **k: B)
    held = []
    picked, _ = S.pick(rows, 1e9, lambda r: 100.0, only_tier=S.TIER_STALE,
                       price_downs={"A": (240.0, 200.0), "B": (240.0, 239.0)}, held=held)
    assert [r["item_id"] for _t, r in picked] == ["A"]
    assert [r["item_id"] for r in held] == ["B"]
    picked2, _ = S.pick(rows, 1e9, lambda r: 100.0, only_tier=S.TIER_STALE)   # 表示用は今までどおり
    assert len(picked2) == 2
