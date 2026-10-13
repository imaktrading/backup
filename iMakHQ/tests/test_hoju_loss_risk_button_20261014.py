"""次の仕入元で買うと赤字になる出品を専用ボタンで出す (2026-10-14 ユーザー「それも専用がいいな。優先順位が高い順に処理したい」)。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import psa_hoju_fill as H  # noqa: E402


def _vals(now, main_url, aux):
    r = [""] * 40
    r[0], r[1], r[13] = main_url, "111", str(now)
    for k, u in enumerate(aux):
        r[H.AUX0 + k] = u
    return [["h"] * 40, r]


def test_loss_when_next_supply_exceeds_margin():
    vals = _vals(10000, "https://m/main", ["https://a/1", "https://a/2"])
    prices = {H._norm_url("https://a/1"): 13000, H._norm_url("https://a/2"): 15000}
    t = {"row": 2, "itemID": "111"}
    # 利益 27% → 次 ¥13,000 は +30% = 赤字
    assert H.loss_risk_next(t, vals, prices, rate_of=lambda c: 0.27) == 13000
    # 利益 40% なら赤字にならない
    assert H.loss_risk_next(t, vals, prices, rate_of=lambda c: 0.40) is None


def test_no_aux_is_not_loss_but_cancel():
    vals = _vals(10000, "https://m/main", [])
    assert H.loss_risk_next({"row": 2, "itemID": "111"}, vals, {}, rate_of=lambda c: 0.27) is None


def test_cheaper_aux_than_main_means_no_loss():
    vals = _vals(10000, "https://m/main", ["https://a/1"])
    prices = {H._norm_url("https://m/main"): 20000, H._norm_url("https://a/1"): 10000}
    # 今いちばん安いのは補 ¥10,000。それが切れたら主 ¥20,000 = 赤字
    assert H.loss_risk_next({"row": 2, "itemID": "111"}, vals, prices, rate_of=lambda c: 0.27) == 20000


def test_candidate_cheaper_than_next_is_kept_even_on_full_swap(monkeypatch):
    monkeypatch.setattr(H, "_row_cost_and_dead", lambda t, vals: (10000, False))
    monkeypatch.setattr(H, "_price_cache_get", lambda hd: {})
    t = {"row": 2, "n_backups": 5, "loss_next": 15000}
    keep, drop = H.filter_candidates_by_cost(
        [{"url": "https://x/1", "price": 12000}, {"url": "https://x/2", "price": 16000}], t, [])
    assert [c["url"] for c in keep] == ["https://x/1"]


def test_button_and_counts_are_wired():
    root = os.path.join(HERE, "..")
    cp = open(os.path.join(root, "control_panel.py"), encoding="utf-8").read()
    assert '"--loss-risk"' in cp and '"badge": "hoju_loss"' in cp
    assert '"hoju_loss"' in open(os.path.join(root, "console", "server.py"), encoding="utf-8").read()
    assert '["hoju_loss", "次で赤字"' in open(os.path.join(root, "console", "static", "app.js"), encoding="utf-8").read()
    assert "mark_loss_risk" in open(os.path.join(root, "tools", "kagoya_offload.py"), encoding="utf-8").read()
