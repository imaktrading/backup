"""補URL の自動追記が、満杯でも **より安ければ入れ替える** (2026-09-07 ユーザー指示).

> 1は修正して、徒労に終わりたくない

目視 (`psa_hoju_fill`) は 2026-09-05 から「安い順に5本へ持ち直す」になっていたが、
自動追記 (2枚目→primary) は満杯だと**捨てるだけ**だった (実測: 1走行で23本 溢れ)。
押し出してよいのは **値段が分かっていて新URLより高い** 既存だけ。
"""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import hoju_url_from_dupes as D  # noqa: E402

E = ["https://a/1", "https://a/2", "https://a/3", "https://a/4", "https://a/5"]


def _p(**kw):
    return {D._norm(k): v for k, v in kw.items()}


def test_cheaper_new_url_replaces_the_most_expensive():
    prices = {D._norm(u): 1000 + i * 100 for i, u in enumerate(E)}   # 1000..1400
    prices[D._norm("https://a/new")] = 500
    full, removed = D.plan_replacement(E, "https://a/new", prices)
    assert full is not None
    assert removed == ["https://a/5"]          # 一番高い既存が出る
    assert "https://a/new" in full and len(full) == 5


def test_more_expensive_new_url_is_not_taken():
    prices = {D._norm(u): 1000 for u in E}
    prices[D._norm("https://a/new")] = 9999
    assert D.plan_replacement(E, "https://a/new", prices) == (None, [])


def test_unknown_price_existing_is_never_pushed_out():
    """値段の分からない既存を根拠なく捨てない (もっと安いかもしれない)."""
    prices = {D._norm("https://a/new"): 500}   # 既存は全部 値段不明
    assert D.plan_replacement(E, "https://a/new", prices) == (None, [])


def test_unknown_price_new_url_does_nothing():
    assert D.plan_replacement(E, "https://a/new", {}) == (None, [])


def test_writer_uses_full_when_replaced():
    """入替が決まった行は full をそのまま書く (existing+add では5本を超える)."""
    src = (TOOLS / "hoju_url_from_dupes.py").read_text(encoding="utf-8")
    assert 'v.get("full") or (v["existing"] + v["add"])' in src


def test_row_price_uses_listing_price_not_cost():
    """比較の土台は **出品価格** (M→F)。N(仕入値)はポイントを引いた後なので使わない."""
    r = [""] * 14
    r[D.F] = "¥12,000"
    assert D.row_price(r) == 12000
    r[D.M] = "9,800"
    assert D.row_price(r) == 9800          # M が優先
    assert D.row_price([""] * 14) is None


def test_new_price_override_lets_row_price_win():
    """キャッシュに無い新URLでも、行の値段で比較できる (実測: これが無いと23本が判定不能)."""
    prices = {D._norm(u): 5000 for u in E}
    full, removed = D.plan_replacement(E, "https://a/new", prices, new_price=1000)
    assert full is not None and removed
