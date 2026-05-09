"""Regression: 2026-05-10 一番くじ向け gap_limit_override kwarg 追加.

事故/背景:
  2026-05-09 一番くじ Phase 3 (eBay CSV 生成) で 4 件全 HOLD:
    A 賞 ルフィ:        median $6.98  / 当社 $91.98 = +1217%
    B 賞 MASTERLISE:    median $9.98  / 当社 $85.98 = +761%
    C 賞 Revible Moment: median $14.98 / 当社 $91.98 = +514%
    D 賞 ギア5:          median $9.98  / 当社 $100.98 = +912%
  → eBay CSV 対象行 0 件、入稿不可. eBay 市場未成熟 (各賞 16-30 件 hit) で
    median が下方歪み、無在庫プレミア仕入 (¥4,500-6,500) と本質的に乖離.

修正方針 (no_modification_chain 準拠):
  pricing_engine.compute_listing_price() に gap_limit_override kwarg 追加.
  None (default) なら従来通り価格帯 tier の gap_limit を使用 (後方互換完全).
  ichibankuji_to_csv.py のみ override=10.0 (= 中央値の 11 倍まで OK) を渡し、
  collectibles 特性 + 新発売 median 信頼性の問題を吸収.

設計原則:
  - if 商品分岐ゼロ (override は kwarg、呼出側 1 箇所で hardcode)
  - 他カテゴリ (TCG/G-shock/Mercari/Tシャツ/Porter) は kwarg 渡さず → None →
    従来動作維持. 影響範囲は ichibankuji のみ
  - 将来「Porter は 30%」「リールは 80%」等の細分化も同 kwarg で対応可能
"""
from __future__ import annotations
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API = _REPO_ROOT / "iMakeBayAPI"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))


def test_default_gap_limit_unchanged():
    """default (override=None) 時、従来通り tier の gap_limit を適用."""
    from pricing_engine import compute_listing_price
    # コスト ¥1,500 / 中央値 $10 / Tシャツ($0-39 帯, gap_limit=50%)
    # コストプラスで $20 程度に着地、median $10 → 乖離 +100% > 50% → ALERT
    r = compute_listing_price(cost_jpy=1500, median_usd=10, category="Tシャツ(UT)")
    assert r["status"] == "ALERT", f"Expected ALERT, got {r['status']}: {r}"
    assert r["gap_limit_pct"] == 50.0, f"Expected 50%, got {r['gap_limit_pct']}"


def test_gap_override_relaxed_passes_high_gap():
    """override=10.0 (=1000%) なら、+800% 程度の乖離も通る."""
    from pricing_engine import compute_listing_price
    # 5/9 一番くじ B 賞ケース近似: 仕入¥4500 / median $9.98 → 当社 ~$86
    # 乖離 +761% < 1000% (=10.0) → GO
    r = compute_listing_price(
        cost_jpy=4500, median_usd=9.98, category="一番くじ",
        gap_limit_override=10.0,
    )
    assert r["status"] == "GO", f"Expected GO with 10.0 override, got {r['status']}: gap={r['gap_pct']}"
    assert r["gap_limit_pct"] == 1000.0, f"Expected 1000%, got {r['gap_limit_pct']}"


def test_gap_override_still_blocks_extreme_gap():
    """override=10.0 でも +1217% (5/9 A 賞) は弾く. 安全弁ゼロ化していないこと."""
    from pricing_engine import compute_listing_price
    # 5/9 一番くじ A 賞ケース近似: 仕入¥5000 / median $6.98 → 当社 ~$92
    # 乖離 +1217% > 1000% → ALERT
    r = compute_listing_price(
        cost_jpy=5000, median_usd=6.98, category="一番くじ",
        gap_limit_override=10.0,
    )
    assert r["status"] == "ALERT", f"Expected ALERT (gap > 1000%), got {r['status']}"


def test_gap_override_does_not_affect_other_categories():
    """override 引数は呼出ごと、他カテゴリの default 動作に影響しない (副作用ゼロ)."""
    from pricing_engine import compute_listing_price
    # Tシャツ default (override 渡さず) → 従来通り 50% 適用
    r1 = compute_listing_price(cost_jpy=1500, median_usd=10, category="Tシャツ(UT)")
    assert r1["gap_limit_pct"] == 50.0
    # 直後に 一番くじ override 呼び出し
    r2 = compute_listing_price(
        cost_jpy=4500, median_usd=9.98, category="一番くじ",
        gap_limit_override=10.0,
    )
    assert r2["gap_limit_pct"] == 1000.0
    # もう一度 Tシャツ default → 50% に戻ってる (グローバル汚染なし)
    r3 = compute_listing_price(cost_jpy=1500, median_usd=10, category="Tシャツ(UT)")
    assert r3["gap_limit_pct"] == 50.0


def test_no_median_path_unaffected_by_override():
    """median 0/None 時は NO_MEDIAN 戻り、override 関係なし."""
    from pricing_engine import compute_listing_price
    r = compute_listing_price(
        cost_jpy=4500, median_usd=0, category="一番くじ",
        gap_limit_override=10.0,
    )
    assert r["status"] == "NO_MEDIAN"
    assert r["gap_pct"] is None
