"""UT 目視で決めた商品を、同じタイトル / 同じタグ番号の別の出品に最初から選んでおく (2026-10-07 ユーザー「うん」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ut_identify as U  # noqa: E402


def test_learned_by_title_and_tag():
    led = {"u1": {"decision": "go", "product_id": "E1", "title": "ユニクロ  呪術廻戦 UT M", "tag": "123456"},
           "u2": {"decision": "out", "product_id": "E9", "title": "x"}}
    bt, bg = U.learned_index(led)
    assert U.learned_pid("ユニクロ 呪術廻戦 UT M", "", bt, bg) == ("E1", "タイトル")
    assert U.learned_pid("別のタイトル", "123456", bt, bg) == ("E1", "タグの番号")
    assert U.learned_pid("x", "", bt, bg) == ("", "")


def test_split_or_disagree_is_not_used():
    led = {"u1": {"decision": "go", "product_id": "E1", "title": "ポケモン UT M"},
           "u2": {"decision": "go", "product_id": "E2", "title": "ポケモン UT M"},
           "u3": {"decision": "go", "product_id": "E3", "title": "A", "tag": "1"},
           "u4": {"decision": "go", "product_id": "E4", "title": "B", "tag": "2"}}
    bt, bg = U.learned_index(led)
    assert U.learned_pid("ポケモン UT M", "", bt, bg) == ("", "")          # 同じタイトルで割れた
    assert U.learned_pid("A", "2", bt, bg) == ("", "")                     # タイトルとタグが食い違う


def test_tag_backfilled_from_rows():
    led = {"u1": {"decision": "go", "product_id": "E1", "title": "t"}}
    _, bg = U.learned_index(led, {"u1": "654321"})
    assert bg == {"654321": {"E1"}}
