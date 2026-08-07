"""Regression: 2026-06-08 生成側を「公式 Aspects JSON」基準で検証 (itemsp ドリフト後手の解消).

経緯: 生成は手動 whitelist_registry(2026-04-23スナップショット)で正規化、監査は最新公式JSONで照合 →
ズレ(ドリフト)を後から監査・週次drift検査で拾う後手構造。ユーザー「監査項目を生成に追加できるものは?」
→ SELECTION_ONLY の公式値照合を生成(validate_and_normalize)に追加(additive)。監査はそのまま(backstop)。

固定する不変条件:
  - 公式 SELECTION_ONLY 許容外の値は generation で violation 化 (手動whitelistに無いフィールドも対象)。
  - 既存の手動whitelist 値 (公式に在る) は誤検出しない。
  - 公式JSONが無いカテゴリ(tomica/tshirt)は従来通り(公式violation追加なし)。
  - eBay特殊値(Does not apply等)は許容。
"""
import importlib.util
import sys
from pathlib import Path

_API = Path(__file__).resolve().parent.parent / "iMakeBayAPI"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))


def _load():
    spec = importlib.util.spec_from_file_location("whitelist_registry", str(_API / "whitelist_registry.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


W = _load()


def test_official_sel_values_loaded_for_covered_categories():
    for cat in ("porter", "ichibankuji", "reel"):
        assert W._official_sel_values(cat), f"{cat} の公式SELECTION_ONLY値が読めていない"
    # 公式JSON未対応カテゴリは空
    assert W._official_sel_values("tomica") == {}


def test_official_flags_value_beyond_manual_whitelist():
    """手動whitelistに無い公式SELECTION_ONLYフィールド(例 Country of Origin)も公式値で検証される。"""
    off = W._official_sel_values("porter")
    assert "Country of Origin" in off  # 前提
    _, viol = W.validate_and_normalize({"Country of Origin": "BogusXYZ"}, "porter")
    assert any(f == "Country of Origin" and "公式" in str(reason) for f, _o, _e, reason in viol)


def test_official_value_passes():
    off = W._official_sel_values("porter")
    good = sorted(off["Country of Origin"])[0]
    _, viol = W.validate_and_normalize({"Country of Origin": good}, "porter")
    assert not any("公式" in str(reason) for *_x, reason in viol)


def test_special_optout_allowed():
    _, viol = W.validate_and_normalize({"Country of Origin": "Does not apply"}, "porter")
    assert not any("公式" in str(reason) for *_x, reason in viol)


def test_no_official_json_category_unchanged():
    """tomica は公式JSON未対応 → 公式violationは付かない (従来挙動)。"""
    _, viol = W.validate_and_normalize({"Country of Origin": "BogusXYZ"}, "tomica")
    assert not any("公式SELECTION_ONLY" in str(e) for *_x, e in viol)


def test_existing_manual_values_not_falsely_flagged():
    """既存の手動whitelist値(公式に在る)は公式チェックで誤検出しない。"""
    for cat in ("porter", "ichibankuji", "reel"):
        off = W._official_sel_values(cat)
        rules = W.WHITELISTS.get(cat, {})
        for field, rule in rules.items():
            if field not in off:
                continue
            for v in rule.get("values", []):
                if v.lower() in W._OFFICIAL_SPECIAL_OK:
                    continue
                assert v in off[field], f"{cat}/{field}: 手動値 '{v}' が公式に無い(過剰検出源)"
