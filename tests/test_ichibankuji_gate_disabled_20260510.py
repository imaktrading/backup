"""Regression: 2026-05-10 一番くじ category を PRICE_CHECK_CONFIG から外す.

事故/背景:
  2026-05-09 一番くじ Phase 3 で 4 件全 HOLD (median との乖離 +514%〜+1217%):
  collectibles 新発売時の eBay 市場未成熟 (各賞 16-30 件 hit のみ) で median が
  下方歪み、無在庫プレミア仕入と本質的に乖離. 構造的に出品不可だった.

修正方針:
  listing_common.PRICE_CHECK_CONFIG["ichibankuji"] を False に変更.
  → audit_csv_row 内の price ALERT → error 化を skip.
  → ALERT は compute_listing_price で warning として print されるが、
     CSV からは除外されない (= 出品される).

設計原則 (no_modification_chain):
  - 他カテゴリ (reel/tshirt/tomica/montbell) は True 維持、影響範囲は ichibankuji のみ
  - PRICE_CHECK_CONFIG 機構自体は維持、将来の細分化余地として残す
  - commit 0b14d6a の gap_limit_override=10.0 は併存 (compute_listing_price 段階で
    ALERT 発生条件を緩和、audit_csv_row 段階で gate 撤廃の二段構成)
"""
from __future__ import annotations
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API = _REPO_ROOT / "iMakeBayAPI"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))


def test_ichibankuji_disabled_in_config():
    """PRICE_CHECK_CONFIG['ichibankuji'].enabled が False."""
    from listing_common import PRICE_CHECK_CONFIG
    assert PRICE_CHECK_CONFIG.get("ichibankuji", {}).get("enabled") is False


def test_other_categories_still_enabled():
    """副作用ゼロ: 他カテゴリの enabled 設定は変更前のまま.
    (tshirt は 2026-06-21 に価格NO-GO廃止で False 化 → test_tshirt_gate_disabled_20260621 で別途検証)。"""
    from listing_common import PRICE_CHECK_CONFIG
    # True 維持
    for cat in ("reel", "tomica", "montbell"):
        assert PRICE_CHECK_CONFIG[cat]["enabled"] is True, f"{cat} should remain True"
    # False (gshock/porter 元々 / tshirt 2026-06-21廃止 / ichibankuji 本ファイル subject)
    for cat in ("gshock", "porter", "tshirt"):
        assert PRICE_CHECK_CONFIG[cat]["enabled"] is False, f"{cat} should be False"


def test_audit_csv_row_does_not_gate_ichibankuji_alert():
    """ichibankuji の ALERT は audit_csv_row で error 化されない (= CSV に残る)."""
    from listing_common import audit_csv_row
    row_data = {
        "*Title": "Ichiban Kuji One Piece A Prize Monkey D Luffy Figure New",
        "*Category": "261055",
        "*StartPrice": "91.98",
        "ConditionID": "1000",
    }
    violations = audit_csv_row(
        row_data, category="ichibankuji",
        price_status="ALERT", median_usd=6.98,
    )
    # ALERT 由来の error は無いこと
    price_errors = [v for v in violations if v[0] == "*StartPrice" and v[2] == "error"
                    and "exceeds market" in v[1]]
    assert price_errors == [], f"Expected no price ALERT error, got: {price_errors}"


def test_audit_csv_row_still_gates_enabled_category_alert():
    """副作用ゼロ確認: enabled カテゴリ(reel)の ALERT は従来通り error 化される
    (= gate 機構自体は生きてる。tshirt は 2026-06-21 に外したが reel/tomica/montbell は維持)。"""
    from listing_common import audit_csv_row
    row_data = {
        "*Title": "Shimano Stradic Spinning Fishing Reel 2500 Japan New",
        "*Category": "261052",
        "*StartPrice": "57.98",
        "ConditionID": "1000",
    }
    violations = audit_csv_row(
        row_data, category="reel",
        price_status="ALERT", median_usd=18.46,
    )
    # reel は依然 gate される
    price_errors = [v for v in violations if v[0] == "*StartPrice" and v[2] == "error"
                    and "exceeds market" in v[1]]
    assert len(price_errors) == 1, f"Expected 1 price ALERT error for reel, got: {price_errors}"
