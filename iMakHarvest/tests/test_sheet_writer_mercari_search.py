"""sheet_writer_mercari_search の純関数テスト (item_id dedup / tab名)."""
import pytest
from sheet_writer_mercari_search import dedupe_key, build_mercari_tab_name

pytestmark = pytest.mark.offline


@pytest.mark.parametrize("url,key", [
    ("https://jp.mercari.com/item/m14394792935", "m14394792935"),
    ("https://jp.mercari.com/item/m14394792935?foo=1", "m14394792935"),
    ("https://jp.mercari.com/item/m30222516408/", "m30222516408"),
    ("", ""),
])
def test_dedupe_key(url, key):
    assert dedupe_key(url) == key


def test_dedupe_same_item_different_query():
    a = dedupe_key("https://jp.mercari.com/item/m1?a=1")
    b = dedupe_key("https://jp.mercari.com/item/m1?b=2")
    assert a == b == "m1"


def test_tab_name():
    assert build_mercari_tab_name("porter") == "mercari_porter"
    assert build_mercari_tab_name("") == "mercari_unknown"
