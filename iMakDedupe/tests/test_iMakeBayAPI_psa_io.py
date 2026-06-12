"""iMakeBayAPI_psa_io unit tests — 越境 import wrapper (network 不要).

Phase 1q (= 5/28 体系再設計): psa_api.py 越境 read-only wrapper.
"""

from unittest.mock import patch

import pytest

from dedupe import iMakeBayAPI_psa_io

pytestmark = pytest.mark.offline


class TestGetCachedPsa:
    def test_returns_none_on_empty_cert(self):
        assert iMakeBayAPI_psa_io.get_cached_psa("") is None
        assert iMakeBayAPI_psa_io.get_cached_psa(None) is None

    def test_returns_none_on_import_failure(self):
        """psa_api.py path 不在 / import 失敗 → None (= fail-closed)."""
        # _import_psa_api を mock して例外 raise
        with patch.object(
            iMakeBayAPI_psa_io, "_import_psa_api", side_effect=FileNotFoundError
        ):
            assert iMakeBayAPI_psa_io.get_cached_psa("12345") is None

    def test_returns_dict_on_hit(self):
        """正常 cache hit → dict 返却."""
        mock_module = type(
            "FakePsaApi",
            (),
            {"get_cached": staticmethod(
                lambda cert: {"Brand": "X", "Subject": "Y"} if cert == "12345" else None
            )},
        )
        with patch.object(
            iMakeBayAPI_psa_io, "_import_psa_api", return_value=mock_module
        ):
            result = iMakeBayAPI_psa_io.get_cached_psa("12345")
            assert result == {"Brand": "X", "Subject": "Y"}

    def test_returns_none_on_cache_miss(self):
        """get_cached が None 返却 (= cache file 不在) → None."""
        mock_module = type(
            "FakePsaApi",
            (),
            {"get_cached": staticmethod(lambda cert: None)},
        )
        with patch.object(
            iMakeBayAPI_psa_io, "_import_psa_api", return_value=mock_module
        ):
            assert iMakeBayAPI_psa_io.get_cached_psa("12345") is None

    def test_returns_none_on_get_cached_exception(self):
        """get_cached が例外 → wrapper が吸収して None."""
        mock_module = type(
            "FakePsaApi",
            (),
            {"get_cached": staticmethod(
                lambda cert: (_ for _ in ()).throw(RuntimeError("boom"))
            )},
        )
        with patch.object(
            iMakeBayAPI_psa_io, "_import_psa_api", return_value=mock_module
        ):
            assert iMakeBayAPI_psa_io.get_cached_psa("12345") is None
