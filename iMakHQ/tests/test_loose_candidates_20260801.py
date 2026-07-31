"""番号未確認(名前一致のみ)の候補フォールバックの回帰テスト (2026-08-01)。

背景 (実測):
    補URL補強の対象82→74件のうち **39件が「候補なし」** だった。その内訳を調べると
    27件は snkrdunk の DB にすら無く mercari 単独判定。mercari は PSA10 出品の商品名に
    **カード番号を書かない出品が多い**ため、番号のトークン一致を必須にすると
    在庫が実在しても0件になり「市場に無い」と誤診する。

ユーザー方針 (2026-08-01):
    > 最終は目視するわけだから、近しいのを含めてくれてもいいけどね。

設計 (守るべき性質):
    1. **strict が0件のときだけ**の フォールバック。良い候補がある時に薄めない
    2. 番号未確認は `number_ok=False` で持ち回り、UI が 🔴番号未確認 と明示する
    3. **価格判定 (`best`) と RESTOCK ゲートには絶対に混ぜない** (番号未確認のものを
       仕入値の根拠にすると誤った価格で出品しかねない)
    4. 名前が取れなければ出さない (fail-closed)
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

from mercari_psa_resource import pick_psa10_loose_candidates      # noqa: E402
from psa_resource_gate import _build_visual_candidates            # noqa: E402
from psa_hoju_fill import _cache_candidate_urls                   # noqa: E402
import psa_resource_confirm as prc                                # noqa: E402


def _it(price, href, name):
    return {"price": price, "href": href, "name": name}


ITEMS = [
    _it(9000, "https://m/1", "ポケモンカード リザードンex SAR PSA10"),      # 番号なし・名前一致
    _it(9500, "https://m/2", "PSA10 リザードン ex SAR 美品"),               # 表記ゆれ・名前一致
    _it(8000, "https://m/3", "ピカチュウ PSA10"),                            # 別カード
    _it(7000, "https://m/4", "リザードンex SAR PSA9"),                       # PSA10 でない
]


def test_loose_picks_name_matches_without_number():
    got = pick_psa10_loose_candidates(ITEMS, "リザードンex")
    assert [g[1] for g in got] == ["https://m/1", "https://m/2"]


def test_loose_excludes_other_cards_and_non_psa10():
    got = [g[1] for g in pick_psa10_loose_candidates(ITEMS, "リザードンex")]
    assert "https://m/3" not in got      # 別カード
    assert "https://m/4" not in got      # PSA9


def test_loose_returns_nothing_without_name():
    """名前が取れなければ出さない (判定材料が無いのに候補を出さない = fail-closed)。"""
    assert pick_psa10_loose_candidates(ITEMS, "") == []
    assert pick_psa10_loose_candidates(ITEMS, None) == []


def test_loose_normalizes_spacing_and_dots():
    items = [_it(100, "https://m/x", "PSA10 ポートガス・D・エース ST15-005")]
    assert pick_psa10_loose_candidates(items, "ポートガスDエース")


# ---- 視覚確証への載り方 ------------------------------------------------------

_STRICT = (1000, "https://m/strict", "strict PSA10")
_LOOSE = (900, "https://m/loose", "loose PSA10")


def test_loose_is_marked_number_unconfirmed():
    got = _build_visual_candidates({"cands": [], "all_cands": [], "loose_cands": [_LOOSE]}, {})
    assert len(got) == 1
    assert got[0]["number_ok"] is False
    assert got[0]["variant_ok"] is False


def test_loose_comes_after_strict_and_does_not_dilute():
    """厳密一致があるときは loose を後ろに置く (良い候補を薄めない)。"""
    got = _build_visual_candidates(
        {"cands": [_STRICT], "all_cands": [_STRICT], "loose_cands": [_LOOSE]}, {})
    assert [c["url"] for c in got] == ["https://m/strict", "https://m/loose"]
    assert got[0].get("number_ok") is None      # strict には番号フラグを付けない
    assert got[1]["number_ok"] is False


def test_strict_candidate_has_no_number_warning():
    got = _build_visual_candidates({"cands": [_STRICT], "all_cands": [_STRICT]}, {})
    assert got[0].get("number_ok") is None


# ---- 「候補なし」で埋もれないこと --------------------------------------------

def test_loose_only_row_is_counted_as_having_candidates():
    """loose しか無い行が『候補なし』として確証UIから漏れないこと(実測39件がこの状態)。"""
    entry = {"date": "2026-08-01", "snkrdunk": {},
             "mercari": {"best": None, "cands": [], "all_cands": [], "loose_cands": [_LOOSE]}}
    assert _cache_candidate_urls(entry) == ["https://m/loose"]


def test_strict_takes_precedence_in_url_extraction():
    entry = {"date": "2026-08-01", "snkrdunk": {},
             "mercari": {"all_cands": [_STRICT], "loose_cands": [_LOOSE]}}
    assert _cache_candidate_urls(entry) == ["https://m/strict"]


# ---- UI 表示 ----------------------------------------------------------------

def test_confirm_html_shows_number_warning_over_variant_badge():
    """番号未確認は変種未確認より強い警告なので、そちらを優先して出す。"""
    html = prc.build_restock_html([{
        "idx": 1, "title": "t", "card_no": "X", "ebay_url": "https://e/1",
        "ref_image": "https://r/ref.jpg",
        "candidates": [{"channel": "mercari", "url": "https://m/loose", "price": 900,
                        "variant_ok": False, "number_ok": False}]}])
    assert "🔴番号未確認" in html
    assert "⚠️変種未確認" not in html
