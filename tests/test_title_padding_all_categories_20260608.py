"""Regression: 2026-06-08 全カテゴリのタイトル下限パディングを実ファクトで効かせる.

経緯 (ユーザー「実装されていても動いていなければ意味がない」「聞かずに全部やって」):
  normalize_title(70字目標) は全カテゴリ通していたが、各カテゴリが pad に渡すキーが
  共通 pad_keys_priority に無く実質無効だった:
    - 一番くじ: 渡すキー(Theme/Franchise)が priority に無い → pad 完全に無効だった
    - montbell: 材料キー名が 'Outer Shell Material' で priority の 'Material' と不一致
    - Workman : そもそも normalize_title 未経由
  対策: priority に Theme/Franchise(フィギュア) と Type/Activity/Season(アパレル) を追加。
        各 build_row 側で実ファクトを pad 材料として渡す。捏造はしない(材料無ければ伸ばさない)。
"""
import sys
from pathlib import Path

_API = Path(__file__).resolve().parent.parent / "iMakeBayAPI"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from listing_common import pad_title_to_target  # noqa: E402


def test_figure_keys_theme_franchise_pad():
    """一番くじ: Theme / Franchise / Year が pad 材料として効く."""
    short = "Ichiban Kuji My Hero Academia A Prize Deku Figure New"  # 53字
    assert len(short) < 70
    specs = {"Theme": "Anime & Manga", "Franchise": "My Hero Academia",
             "Year Manufactured": "2024", "Character": "Deku"}
    out = pad_title_to_target(short, specs, category="ichibankuji", target_min=70, max_chars=80)
    assert len(out) <= 80
    # Theme は priority に追加されたので挿入される (元は無効だった)
    assert "Anime & Manga" in out


def test_apparel_keys_type_activity_season_pad():
    """Workman: Type / Material / Activity / Season が pad 材料として効く."""
    short = "Field Core Aegis Jacket Workman Japan Limited New"  # 48字
    specs = {"Type": "Jacket", "Material": "Polyester", "Style": "Casual",
             "Activity": "Outdoor", "Season": "Winter"}
    out = pad_title_to_target(short, specs, category="workman", target_min=70, max_chars=80)
    assert 70 <= len(out) <= 80
    assert "Polyester" in out  # Material が挿入された


def test_pad_skips_value_already_in_title():
    """既にタイトルに在る値 (Jacket) は再挿入しない (重複防止)."""
    short = "Field Core Jacket Workman Japan Limited New"
    specs = {"Type": "Jacket", "Material": "Cotton"}
    out = pad_title_to_target(short, specs, category="workman", target_min=70, max_chars=80)
    assert out.count("Jacket") == 1


def test_pad_no_material_no_fabrication():
    """材料が空なら 70未満のまま (捏造しない)."""
    short = "Ichiban Kuji X A Prize Figure New"
    specs = {"Theme": "", "Franchise": "", "Year Manufactured": ""}
    out = pad_title_to_target(short, specs, category="ichibankuji", target_min=70, max_chars=80)
    assert out == short
