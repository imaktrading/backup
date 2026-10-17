"""tests/test_vision_reject_cache - 写真を読んで対象外と確定した出品の永続控え."""
from __future__ import annotations

import pytest

from scrapers import vision_reject_cache as C

pytestmark = pytest.mark.offline


def test_load_missing_file_returns_empty(tmp_path):
    assert C.load(tmp_path / "nope.json") == {}
    assert C.load_url_set(tmp_path / "nope.json") == set()


def test_merge_and_save_roundtrip(tmp_path):
    p = tmp_path / "cache.json"
    added1 = C.merge_and_save({"https://x/a": "not_psa10_listing"}, p)
    assert added1 == 1
    assert C.load_url_set(p) == {"https://x/a"}

    added2 = C.merge_and_save({"https://x/a": "not_psa10_listing", "https://x/b": "bundle"}, p)
    assert added2 == 1  # a は既存、 b だけ新規
    assert C.load_url_set(p) == {"https://x/a", "https://x/b"}
