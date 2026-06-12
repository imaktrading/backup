"""catalog_io.lookup_don の image_url 引数 forward-compat 動作 test (= Phase 1r).

Catalog B (= lookup_don 画像 hash 統合) 完成前後で signature inspect で安全動作.
"""

from unittest.mock import patch

import pytest

from dedupe import catalog_io

pytestmark = pytest.mark.offline


class TestLookupDonImageUrlForwardCompat:
    def test_lookup_don_without_image_url_when_catalog_supports_only_brand_subject(self):
        """Catalog B 未対応 (= lookup_don(brand, subject, verbose)) → image_url 渡さない."""
        calls = []

        def fake_old_lookup_don(brand, subject, verbose=True):
            calls.append({"brand": brand, "subject": subject})
            return {"product_id": "DON-OP15-002"}

        with patch.object(
            catalog_io, "_import_catalog_lookup", return_value=fake_old_lookup_don
        ):
            result = catalog_io.lookup_don(
                brand="BRAND", subject="DON", image_url="http://x.jpg"
            )
        assert result == {"product_id": "DON-OP15-002"}
        # 既存 signature には image_url が無いので渡されない (= TypeError 回避)
        assert "image_url" not in calls[0]

    def test_lookup_don_with_image_url_when_catalog_supports(self):
        """Catalog B 対応後 (= image_url kwarg あり) → image_url 渡す."""
        calls = []

        def fake_new_lookup_don(brand, subject, verbose=True, image_url=None):
            calls.append(
                {"brand": brand, "subject": subject, "image_url": image_url}
            )
            return {"product_id": "DON-OP15-007"}

        with patch.object(
            catalog_io, "_import_catalog_lookup", return_value=fake_new_lookup_don
        ):
            result = catalog_io.lookup_don(
                brand="BRAND", subject="DON", image_url="http://x.jpg"
            )
        assert result == {"product_id": "DON-OP15-007"}
        assert calls[0]["image_url"] == "http://x.jpg"

    def test_lookup_don_image_url_none_not_passed(self):
        """image_url=None なら catalog 対応関数でも渡さない (= optional behavior)."""
        calls = []

        def fake_new_lookup_don(brand, subject, verbose=True, image_url=None):
            calls.append(
                {"brand": brand, "subject": subject, "image_url": image_url}
            )
            return None

        with patch.object(
            catalog_io, "_import_catalog_lookup", return_value=fake_new_lookup_don
        ):
            catalog_io.lookup_don(brand="BRAND", subject="DON", image_url=None)
        # image_url=None は渡さず (= default の None 採用、 重複 set 回避)
        assert calls[0].get("image_url") is None or "image_url" not in calls[0]

    def test_lookup_don_image_url_empty_string_not_passed(self):
        """image_url='' (= 空文字列) も渡さない (= falsy check)."""
        calls = []

        def fake_new_lookup_don(brand, subject, verbose=True, image_url=None):
            calls.append(
                {"brand": brand, "subject": subject, "image_url": image_url}
            )
            return None

        with patch.object(
            catalog_io, "_import_catalog_lookup", return_value=fake_new_lookup_don
        ):
            catalog_io.lookup_don(brand="BRAND", subject="DON", image_url="")
        # '' は falsy なので default の None
        assert calls[0].get("image_url") is None
