"""gshock_merge.compute_merge の単体テスト (= 冪等・空枠のみ・満杯skip・新規別出し)."""
import pytest

from gshock_merge import compute_merge

pytestmark = pytest.mark.offline

A = "https://www.amazon.co.jp/dp/B0AMAZON001"
Y = "https://www.yodobashi.com/product/100000001000000001/"


def _existing(primary, supp=None):
    return {"GA-2100-1A1JF": {"primary_url": primary, "supp_urls": supp or []}}


def test_adds_supplement_to_existing_model():
    res = compute_merge(
        _existing(A),
        [{"model": "GA-2100-1A1JF", "url": Y, "source": "yodobashi"}],
    )
    assert res["supp_additions"] == {"GA-2100-1A1JF": [Y]}
    assert res["new_candidates"] == []


def test_idempotent_skips_url_already_primary():
    # 追加URL が既に主URL → 冪等 skip
    res = compute_merge(_existing(A), [{"model": "GA-2100-1A1JF", "url": A, "source": "amazon"}])
    assert res["supp_additions"] == {}
    assert res["skipped_dup"] == 1


def test_idempotent_skips_url_already_supplement():
    res = compute_merge(
        _existing(A, [Y]),
        [{"model": "GA-2100-1A1JF", "url": Y + "/", "source": "yodobashi"}],  # 末尾/違いも吸収
    )
    assert res["supp_additions"] == {}
    assert res["skipped_dup"] == 1


def test_new_model_goes_to_candidates():
    res = compute_merge(
        _existing(A),
        [{"model": "DW-5000R-1AJF", "url": Y, "source": "yodobashi"}],
    )
    assert res["supp_additions"] == {}
    assert len(res["new_candidates"]) == 1
    assert res["new_candidates"][0]["model"] == "DW-5000R-1AJF"


def test_full_slots_skips_without_overwrite():
    # 補枠 5 満杯 → 新URL は入らず既存保持 (skipped_full)
    full = {"GA-2100-1A1JF": {"primary_url": A,
                              "supp_urls": [f"https://x/{i}" for i in range(5)]}}
    res = compute_merge(full, [{"model": "GA-2100-1A1JF", "url": Y, "source": "yodobashi"}])
    assert res["supp_additions"] == {}
    assert res["skipped_full"] == 1


def test_respects_remaining_slots_only():
    # 既存補 4 → 空き 1 枠。 2 件来ても 1 件だけ入る
    ex = {"GA-2100-1A1JF": {"primary_url": A,
                            "supp_urls": [f"https://x/{i}" for i in range(4)]}}
    res = compute_merge(ex, [
        {"model": "GA-2100-1A1JF", "url": Y, "source": "yodobashi"},
        {"model": "GA-2100-1A1JF", "url": "https://z/9", "source": "other"},
    ])
    added = res["supp_additions"]["GA-2100-1A1JF"]
    assert len(added) == 1
    assert res["skipped_full"] == 1


def test_batch_dedup_same_model_url():
    res = compute_merge(_existing(A), [
        {"model": "GA-2100-1A1JF", "url": Y, "source": "yodobashi"},
        {"model": "GA-2100-1A1JF", "url": Y, "source": "yodobashi"},  # batch 内重複
    ])
    assert res["supp_additions"]["GA-2100-1A1JF"] == [Y]


def test_case_insensitive_model_key():
    res = compute_merge(
        {"GA-2100-1A1JF": {"primary_url": A, "supp_urls": []}},
        [{"model": "ga-2100-1a1jf", "url": Y, "source": "yodobashi"}],
    )
    assert res["supp_additions"] == {"GA-2100-1A1JF": [Y]}


def test_does_not_touch_stock_state():
    # 返り値に D 列/在庫状態のキーが無い (= 状態は Inventory 責務)
    res = compute_merge(_existing(A), [{"model": "GA-2100-1A1JF", "url": Y}])
    assert set(res) == {"supp_additions", "new_candidates", "skipped_dup", "skipped_full"}
