"""ebay_api unit tests — network 不要 (= file I/O + mock 経由)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dedupe import ebay_api

pytestmark = pytest.mark.offline


class TestExtractKey:
    @pytest.mark.parametrize(
        "specifics,expected_key,expected_aspect",
        [
            ({"Card Number": "OP01-016", "Game": "One Piece"}, "OP01-016", "Card Number"),
            ({"Model": "DW-5600-1JF", "Brand": "Casio"}, "DW-5600-1JF", "Model"),
            ({"MPN": "12345-ABC"}, "12345-ABC", "MPN"),
            ({"Card Number": "OP02-100", "Model": "ignored"}, "OP02-100", "Card Number"),
            ({"Game": "Pokemon"}, None, ""),
            ({}, None, ""),
            ({"_error": "HTTP 404"}, None, ""),
            ({"Card Number": "   "}, None, ""),
        ],
    )
    def test_priority(self, specifics, expected_key, expected_aspect):
        k, a = ebay_api.extract_key_from_specifics(specifics)
        assert k == expected_key
        assert a == expected_aspect


class TestCacheIO:
    def test_load_missing_returns_empty(self, tmp_path):
        assert ebay_api.load_cache_if_exists(tmp_path / "nope.json") == {}

    def test_load_corrupt_returns_empty(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid json", encoding="utf-8")
        assert ebay_api.load_cache_if_exists(p) == {}

    def test_save_and_reload_roundtrip(self, tmp_path):
        p = tmp_path / "ok.json"
        cache = {
            "358372285429": {"Card Number": "OP05-060", "Game": "One Piece"},
            "356700921169": {"_error": "HTTP 404"},
        }
        ebay_api.save_cache(cache, p)
        loaded = ebay_api.load_cache_if_exists(p)
        assert loaded == cache

    def test_save_creates_parent_dir(self, tmp_path):
        p = tmp_path / "nested" / "deep" / "cache.json"
        ebay_api.save_cache({"foo": {}}, p)
        assert p.exists()


class TestFindLatestCache:
    def test_returns_none_on_missing(self, tmp_path):
        assert ebay_api.find_latest_cache(tmp_path / "nope") is None

    def test_returns_none_on_empty(self, tmp_path):
        (tmp_path / "other.txt").write_text("ignore")
        assert ebay_api.find_latest_cache(tmp_path) is None

    def test_picks_lexicographically_last(self, tmp_path):
        for name in [
            "listing_specs_2026-05-25.json",
            "listing_specs_2026-05-27.json",
            "listing_specs_2026-05-26.json",
        ]:
            (tmp_path / name).write_text("{}")
        latest = ebay_api.find_latest_cache(tmp_path)
        assert latest is not None
        assert latest.name == "listing_specs_2026-05-27.json"


class TestBatchFetchResumable:
    def test_skips_existing_cache_entries(self, tmp_path):
        """既に cache にある item_id は fetch しない (= resumable)."""
        p = tmp_path / "cache.json"
        # pre-existing partial cache
        ebay_api.save_cache(
            {"existing_id": {"Card Number": "OP01-001"}},
            p,
        )
        calls = []

        def fake_fetch(token, item_id):
            calls.append(item_id)
            return {"Card Number": f"FAKE-{item_id}"}

        with patch.object(ebay_api, "fetch_specifics", side_effect=fake_fetch):
            cache = ebay_api.batch_fetch_specifics(
                token="dummy",
                item_ids=["existing_id", "new_id_1", "new_id_2"],
                output_path=p,
                flush_every=1,
                sleep_seconds=0,
                progress=False,
            )

        assert calls == ["new_id_1", "new_id_2"]  # existing_id は skip
        assert cache["existing_id"] == {"Card Number": "OP01-001"}
        assert cache["new_id_1"] == {"Card Number": "FAKE-new_id_1"}
        assert cache["new_id_2"] == {"Card Number": "FAKE-new_id_2"}

    def test_records_error_results(self, tmp_path):
        p = tmp_path / "cache.json"
        responses = {
            "ok_id": {"Card Number": "OP02-050"},
            "err_id": {"_error": "HTTP 404"},
        }

        def fake_fetch(token, item_id):
            return responses[item_id]

        with patch.object(ebay_api, "fetch_specifics", side_effect=fake_fetch):
            cache = ebay_api.batch_fetch_specifics(
                token="dummy",
                item_ids=["ok_id", "err_id"],
                output_path=p,
                flush_every=10,
                sleep_seconds=0,
                progress=False,
            )

        assert cache["ok_id"] == {"Card Number": "OP02-050"}
        assert "_error" in cache["err_id"]

    def test_empty_item_ids_skipped(self, tmp_path):
        p = tmp_path / "cache.json"
        with patch.object(ebay_api, "fetch_specifics", return_value={"Card Number": "OP01-001"}) as m:
            ebay_api.batch_fetch_specifics(
                token="dummy",
                item_ids=["", None, "real"],
                output_path=p,
                flush_every=10,
                sleep_seconds=0,
                progress=False,
            )
            m.assert_called_once_with("dummy", "real")


def test_build_cache_path():
    p = ebay_api.build_cache_path(
        cache_dir=Path("/tmp/cache"),
        date_str="2026-05-27",
    )
    assert p == Path("/tmp/cache/listing_specs_2026-05-27.json")
