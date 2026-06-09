"""Regression: 2026-06-08 G-SHOCK タイトル下限パディングが実ファクトで効く.

問題:
  pad_title_to_target / normalize_title (70字目標) は実装済で G-SHOCK も通していたが、
  渡す pad 材料が {Color, Material, Year} だけ。Color/Material は既にタイトルに在る or 空 →
  足す材料が尽きて 61〜68 字で打ち止め (実CSV gshock_upload_20260607_072221 で 10件中5件 <70字)。
  「実装されていても動いていなければ意味がない」(ユーザー 2026-06-08)。

修正方針 (捏造禁止):
  1. listing_common.pad_title_to_target の pad_keys_priority に 'Water Resistance' / 'Movement' 追加
  2. gshock_to_csv.build_row の _gs_specs に Style / Water Resistance / Movement を実ファクトで投入
  → 70-80字をバイヤー検索語 (Sport / Quartz / 200M Water Resistant 等) で埋める。
"""
import sys
from pathlib import Path

_API = Path(__file__).resolve().parent.parent / "iMakeBayAPI"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from listing_common import pad_title_to_target, normalize_title  # noqa: E402


def test_water_resistance_movement_are_pad_keys():
    """新キー (Water Resistance / Movement) が pad 材料として効く."""
    short = "CASIO G-Shock GW-M5610U-1B Mens Digital Watch Black Resin New"  # 60字
    assert len(short) < 70
    specs = {"Color": "Black", "Material": "Resin", "Style": "Sport",
             "Water Resistance": "200M Water Resistant", "Movement": "Quartz"}
    out = pad_title_to_target(short, specs, category="gshock", target_min=70, max_chars=80)
    assert 70 <= len(out) <= 80
    # 既にタイトルに在る値は再挿入しない
    assert out.count("Black") == 1 and out.count("Resin") == 1


def test_pad_never_exceeds_80():
    """長い実ファクトが来ても 80字を超えない (はみ出す候補はスキップ)."""
    base = "CASIO G-Shock GM-2100BB-1AJF Mens Analog & Digital Watch Black New"  # 65字
    specs = {"Color": "Black", "Material": "Carbon Fiber", "Style": "Sport",
             "Water Resistance": "200M Water Resistant", "Movement": "Quartz"}
    out = normalize_title(base, is_new=True, item_specifics=specs,
                          category="gshock", target_min=70, max_chars=80)
    assert len(out) <= 80
    assert len(out) >= 70


def test_pad_no_fabrication_when_no_facts():
    """材料が空なら伸ばさない (捏造しない). 70未満のまま返ることを許容."""
    base = "CASIO G-Shock ABC-1 Mens Digital Watch Black New"
    specs = {"Color": "Black", "Material": "", "Style": "", "Water Resistance": "", "Movement": ""}
    out = pad_title_to_target(base, specs, category="gshock", target_min=70, max_chars=80)
    # Black は既出 → 何も足せない → 元のまま (捏造しない)
    assert out == base
