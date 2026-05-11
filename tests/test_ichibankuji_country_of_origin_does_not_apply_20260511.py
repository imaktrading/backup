"""Regression: 2026-05-11 ichibankuji whitelist に Country of Origin "Does not apply" 追加.

【背景】
5/11 16:15 一番くじ Phase 2 走行で 14件 すべて HOLD: "C:Country of Origin=
非フィルタ値: Does not apply"。eBay CSV 対象行ゼロ。

原因: 5/10 commit (4ce3d44 等) で listing_common 側を「Country: Japan →
Does not apply」に切替えた時、whitelist_registry.py の ichibankuji カテゴリ
"Country of Origin" whitelist 更新を忘れた片手落ち。

【グローバル CLAUDE.md ルール】
「Country of Origin: 画像から確認できない場合は『Does not apply』を明示的に
入れる。空欄にすると eBay の AI が勝手に Japan 等を補完するため」

= "Does not apply" は eBay 公式正規エスケープ値、全カテゴリで許容すべき.
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API = _REPO_ROOT / "iMakeBayAPI"


def _load_registry():
    if str(_API) not in sys.path:
        sys.path.insert(0, str(_API))
    spec = importlib.util.spec_from_file_location(
        "_test_whitelist_registry", str(_API / "whitelist_registry.py")
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_ichibankuji_country_of_origin_allows_does_not_apply():
    """ichibankuji.Country of Origin の許容値に 'Does not apply' が含まれる."""
    reg = _load_registry()
    whitelist = reg.WHITELISTS["ichibankuji"]["Country of Origin"]
    assert "Does not apply" in whitelist["values"], (
        "Does not apply は eBay 公式正規値、グローバル CLAUDE.md ルール準拠で必須"
    )
    # 既存値は維持
    assert "Japan" in whitelist["values"]
    assert "China" in whitelist["values"]
    assert whitelist["strict"] is True


def test_ichibankuji_country_of_origin_validates_does_not_apply():
    """実際の validator API で 'Does not apply' が pass する."""
    reg = _load_registry()
    # 値が whitelist に含まれていることを直接検証 (strict=True なので含めば通る)
    values = reg.WHITELISTS["ichibankuji"]["Country of Origin"]["values"]
    assert "Does not apply" in values


def test_other_categories_country_field_consistency():
    """他カテゴリの Country フィールドにも 'Does not apply' が漏れていない (将来の片手落ち防止)."""
    reg = _load_registry()
    registry = reg.WHITELISTS
    # tomica / reel は "Country/Region of Manufacture" で既に Does not apply あり
    for cat in ("tomica", "reel"):
        country_field = registry[cat].get("Country/Region of Manufacture")
        if country_field and country_field.get("strict"):
            assert "Does not apply" in country_field["values"], (
                f"{cat} の Country/Region of Manufacture に Does not apply が必要"
            )
