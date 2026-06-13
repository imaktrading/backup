"""R1: snapshot fresh-or-fail のテスト (= silent stale fallback 廃止の動作実証).

4 cases + 失敗注入:
  1. DL 成功 → 正常
  2. DL 失敗 + retry で復旧 → 正常
  3. DL 失敗 + retry 尽き → SnapshotFetchError raise (= 中止)
  4. mtime > 6h の既存 snapshot → SnapshotFetchError raise (= 中止)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

THIS = Path(__file__).resolve().parent
PROJECT = THIS.parent
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from revise import price_revise


@pytest.fixture
def tmp_snapshot_dir(tmp_path, monkeypatch):
    """共有 snapshot dir を tmp に向ける."""
    return tmp_path


# ============================================================================
# fetch_and_save_snapshot (= DL + retry + raise)
# ============================================================================
class TestFetchAndSaveSnapshot:
    def test_dl_success(self, tmp_snapshot_dir, monkeypatch):
        """case1: DL 成功 → 正常 path 返却"""
        sentinel_path = tmp_snapshot_dir / "ebay_active_test.csv"

        def fake_fetch(verbose=False):
            return [{"item_id": "1", "title": "t", "price_usd": 1.0,
                     "currency": "USD", "site": "US", "qty": 1,
                     "shipping_profile_name": "X"}]

        def fake_save(items, output_dir):
            sentinel_path.write_text("dummy", encoding="utf-8")
            return sentinel_path

        def fake_rotate(d, keep_count=5):
            return []

        monkeypatch.setattr("revise.ebay_trading_api.save_snapshot_csv", fake_save)
        monkeypatch.setattr("revise.ebay_trading_api.rotate_snapshots", fake_rotate)
        result = price_revise.fetch_and_save_snapshot(
            output_dir=tmp_snapshot_dir, fetch_fn=fake_fetch, max_retries=1, verbose=False)
        assert result == sentinel_path

    def test_dl_fail_then_retry_success(self, tmp_snapshot_dir, monkeypatch):
        """case2: 1 回目失敗 → 2 回目成功 → 正常"""
        sentinel_path = tmp_snapshot_dir / "ebay_active_test.csv"
        call_count = {"n": 0}

        def fake_fetch(verbose=False):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("DNS failed")
            return [{"item_id": "1", "title": "t", "price_usd": 1.0,
                     "currency": "USD", "site": "US", "qty": 1,
                     "shipping_profile_name": "X"}]

        def fake_save(items, output_dir):
            sentinel_path.write_text("dummy", encoding="utf-8")
            return sentinel_path

        def fake_rotate(d, keep_count=5):
            return []

        # flushdns / sleep は副作用なしで通す
        with patch("revise.price_revise._flush_dns_cache"), \
             patch("revise.price_revise.time.sleep"):
            monkeypatch.setattr("revise.ebay_trading_api.save_snapshot_csv", fake_save)
            monkeypatch.setattr("revise.ebay_trading_api.rotate_snapshots", fake_rotate)
            result = price_revise.fetch_and_save_snapshot(
                output_dir=tmp_snapshot_dir, fetch_fn=fake_fetch,
                max_retries=3, verbose=False)

        assert result == sentinel_path
        assert call_count["n"] == 2  # 2 回目で成功

    def test_dl_fail_all_retries_raises(self, tmp_snapshot_dir, monkeypatch):
        """case3: 全 retry 尽き → SnapshotFetchError (= run 中止)"""
        call_count = {"n": 0}

        def fake_fetch_always_fail(verbose=False):
            call_count["n"] += 1
            raise ConnectionError(f"DNS failed (attempt {call_count['n']})")

        with patch("revise.price_revise._flush_dns_cache"), \
             patch("revise.price_revise.time.sleep"):
            with pytest.raises(price_revise.SnapshotFetchError) as exc:
                price_revise.fetch_and_save_snapshot(
                    output_dir=tmp_snapshot_dir, fetch_fn=fake_fetch_always_fail,
                    max_retries=3, verbose=False)

        assert "3 回 retry 尽き" in str(exc.value)
        assert call_count["n"] == 3  # 3 回 retry 実行


# ============================================================================
# _check_snapshot_freshness (= mtime 6h ガード)
# ============================================================================
class TestSnapshotFreshness:
    def test_fresh_snapshot_ok(self, tmp_snapshot_dir):
        """case4 前段: 新しい snapshot (= mtime now) → 通過"""
        p = tmp_snapshot_dir / "fresh.csv"
        p.write_text("dummy", encoding="utf-8")
        # raise しないことを確認
        price_revise._check_snapshot_freshness(p, max_age_sec=6 * 3600, verbose=False)

    def test_stale_snapshot_raises(self, tmp_snapshot_dir):
        """case4: mtime > 6h → SnapshotFetchError (= run 中止)"""
        p = tmp_snapshot_dir / "stale.csv"
        p.write_text("dummy", encoding="utf-8")
        # mtime を 7 時間前に偽装
        old_time = time.time() - 7 * 3600
        import os
        os.utime(p, (old_time, old_time))

        with pytest.raises(price_revise.SnapshotFetchError) as exc:
            price_revise._check_snapshot_freshness(
                p, max_age_sec=6 * 3600, verbose=False)
        assert "stale" in str(exc.value).lower()
        assert "7." in str(exc.value)  # 7.x h 前と報告

    def test_missing_snapshot_raises(self, tmp_snapshot_dir):
        """補足: 存在しない snapshot → SnapshotFetchError"""
        p = tmp_snapshot_dir / "missing.csv"
        with pytest.raises(price_revise.SnapshotFetchError) as exc:
            price_revise._check_snapshot_freshness(p, verbose=False)
        assert "not found" in str(exc.value)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
