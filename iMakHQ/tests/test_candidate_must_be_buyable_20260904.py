# -*- coding: utf-8 -*-
"""候補は「仕入れるに値するもの」だけ (2026-09-04 ユーザー指示)。

> この段階で、セラーフィルタ含めて仕入れるに値するものにしておくべきでは？

## 何が起きていたか
1. **オークションが混入**。ユーザー報告の m30195199994 は実機で bid-button あり=
   オークション。それが 補URL (スプシ1 行1564 AC列) に入っていた
2. **検索結果では見分けが付かない**。実測 (キーワード 'PSA10 ST01-012' 99セル):
   オークションのセルに 'オークション/入札/現在価格/残り時間' は1つも出ず、
   itemtype も通常と同じ。data-testid / class / aria-label の集合比較でも
   **差は商品名だけ**。2026-06-09 のマーカー方式はもう成り立たない
3. **セラーフィルタが ①探す で掛かっていなかった**。opt-in で、渡していたのは
   補URL夜間検索だけ。psa_resource_gate は無指定=素通し。しかも両者は
   psa_research_cache を共有し再検索判定が「日付が今日」だけなので、
   その日に①探すを先に押すと補URL側は再検索せず素通しの候補が流れた

## 直し方
判定を **候補を確定する所** に置く。呼出側の引数まかせにしない
(渡し忘れた入口から素通りしたものが共有キャッシュに焼かれる)。
確実な鑑別子は詳細ページのボタンだけ = buyable_from_detail。
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TOOLS = os.path.join(_ROOT, "iMakHQ", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import mercari_psa_resource as M                   # noqa: E402


# ── 買えるかの判定 ──────────────────────────────────────────
def test_auction_is_not_buyable():
    """bid-button = オークション。確定価格で買えないので候補にしない。"""
    assert M.buyable_from_detail('<div data-testid="bid-button">入札する</div>') is False


def test_normal_listing_is_buyable():
    assert M.buyable_from_detail('<div data-testid="checkout-button">購入</div>') is True


def test_sold_or_unknown_is_not_buyable():
    """どちらのボタンも無い = 売り切れ / 読めなかった。fail-closed で落とす。"""
    assert M.buyable_from_detail("<div>SOLD</div>") is False
    assert M.buyable_from_detail("") is False


def test_words_alone_do_not_decide():
    """『入札』『現在価格』等の語は i18n で全ページに出る。語では判定しない。"""
    noise = '<script>{"bid":"入札する","cur":"現在価格","left":"残り時間"}</script>'
    assert M.buyable_from_detail(noise) is False              # ボタンが無いので不可
    assert M.buyable_from_detail(noise + '<div data-testid="checkout-button">') is True


# ── 仕入れるに値するかの判定 ────────────────────────────────
def test_not_buyable_fails_even_if_everything_else_is_fine():
    assert M.candidate_passes_filter("新品、未使用", "送料込み", 500, False,
                                     buyable=False) is False


def test_buyable_and_the_rest_passes():
    assert M.candidate_passes_filter("新品、未使用", "送料込み", 500, False,
                                     buyable=True) is True


def test_existing_rules_still_hold():
    """着払い / 評価不足 / 評価が取れない個人 は従来どおり落とす。"""
    assert M.candidate_passes_filter("新品、未使用", "着払い", 500, False) is False
    assert M.candidate_passes_filter("新品、未使用", "送料込み", 3, False) is False
    assert M.candidate_passes_filter("新品、未使用", "送料込み", None, False) is False
    # Shops (業者) は評価不問
    assert M.candidate_passes_filter("新品、未使用", "送料込み", None, True) is True


# ── 入口を問わず掛かるか ────────────────────────────────────
def test_the_filter_is_on_by_default():
    """opt-in をやめた。①探す (無指定で呼ぶ) でも掛かる。"""
    import inspect
    sig = inspect.signature(M.fetch_mercari_cheapest)
    assert sig.parameters["freeship_min_reviews"].default == 100


def test_every_category_checks_buyability():
    """PSA / 一番くじ / UT のどれも 買えるか を見ている (片方だけ直る、をやめる)。"""
    import io as _io
    for f, need in (("ichibankuji_restock.py", "buyable_from_detail"),
                    ("ut_hoju_fill.py", "buyable_from_detail")):
        s = _io.open(os.path.join(_TOOLS, f), encoding="utf-8").read()
        assert need in s, f
    # PSA は _detail_supply_check 経由 (共通の判定を通る)
    s = _io.open(os.path.join(_TOOLS, "mercari_psa_resource.py"), encoding="utf-8").read()
    # ★2026-09-04 (後): 判定結果を台帳にも残すため、一度 変数に受けてから渡す形にした。
    assert "_buyable = buyable_from_detail(src)" in s
    assert "buyable=_buyable" in s


def test_ichibankuji_refetches_cache_without_buyable():
    """買えるか未収録の古いキャッシュは取り直す。

    欠けを False 扱い → 候補が全滅 / True 扱い → オークションが通る。
    取り直すのが唯一正しい。
    """
    import importlib
    K = importlib.import_module("ichibankuji_restock")
    old = {"date": "2026-09-04", "cond": "新品、未使用", "ship": "送料込み", "reviews": 500}
    assert K.detail_cache_fresh(old, today="2026-09-04") is False
    new = dict(old); new["buyable"] = True
    assert K.detail_cache_fresh(new, today="2026-09-04") is True
