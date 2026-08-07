"""ITAJAGA 誤分類の根治テスト (2026-07-25)。

ITAJAGA(カルビースナック封入 食玩プロモ)= Brand "ITAJAGA DRAGON BALL VOL.N" が "DRAGON BALL"
分岐で dragonball_scg に誤分類 → missing_models 汚染(seen×9-10・7/16以来) → gshock監査にも混入。
提案A: detect_game_info が franchise="Itajaga"(out-of-scope) を返す。
提案B: csv_auditor が recurring を project-scoped filter(他プロジェクト由来を除外)。
純関数のみ。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent          # C:/dev/iMak
sys.path.insert(0, str(_ROOT / "iMakTCG"))
sys.path.insert(0, str(_ROOT / "iMakHQ" / "tools"))

from psa_to_csv import detect_game_info                        # 提案A(iMakTCG)
from csv_auditor import filter_recurring_for_project           # 提案B(iMakHQ/tools)


# ---- 提案A: ITAJAGA を dragonball_scg に誤分類しない ----

def test_itajaga_classified_as_out_of_scope_not_dragonball():
    for brand in ("ITAJAGA DRAGON BALL VOL.8", "ITAJAGA DRAGON BALL VOL.7"):
        game, setname, franchise = detect_game_info(brand)
        assert franchise == "Itajaga", f"{brand} → {franchise} (dragonball_scg誤分類の再発)"


def test_real_dragonball_scg_still_classified():
    # 本物の SCG は従来どおり(誤って ITAJAGA 扱いにしない)
    fr = detect_game_info("DRAGON BALL SUPER CARD GAME FUSION WORLD JAPANESE BLAZING AURA")[2]
    assert fr == "Dragon Ball"


def test_dragonball_heroes_still_out_of_scope():
    assert detect_game_info("DRAGON BALL HEROES GALAXY MISSION 10")[2] == "Dragon Ball Heroes"


# ---- 提案B: recurring を project-scoped に絞る(他プロジェクト由来を除外) ----

def test_recurring_drops_other_project_category():
    rec = [{"category": "dragonball_scg", "item_id": "certTCG"},
           {"category": "gshock", "item_id": "certGS"}]
    # gshock 監査: dragonball_scg(TCG) は落とす / gshock は残す
    assert [r["item_id"] for r in filter_recurring_for_project(rec, "gshock")] == ["certGS"]
    # tcg 監査: dragonball_scg は残す
    assert [r["item_id"] for r in filter_recurring_for_project(rec, "tcg")] == ["certTCG"]


def test_recurring_unknown_category_kept_not_hidden():
    # 未知 category / 空 は隠さない(fail-safe: silent drop しない)
    rec = [{"category": "unknown_cat", "item_id": "x"}, {"category": "", "item_id": "y"}]
    assert len(filter_recurring_for_project(rec, "gshock")) == 2


def test_recurring_project_name_as_category_is_scoped():
    """★2026-08-01: pdca には **project名のまま** の category('tcg'/'mercari')が積まれている。

    owner_map に project名 key が無いと `owner=None` → fail-safe で残り、
    **gshock/ichibankuji/mercari の digest に TCG 案件が全部混入**していた
    (実測: `category='tcg' AND status='pending'` が 16件。うち seen_count>=2 の1件が leak 中)。
    未知 category を残す fail-safe は正しいが、**既知の project名を未知扱いにしてはいけない**。
    """
    rec = [{"category": "tcg", "item_id": "certTCG"},
           {"category": "mercari", "item_id": "certMER"},
           {"category": "gshock", "item_id": "certGS"}]
    # gshock 監査: project名 category の tcg / mercari は落とす
    assert [r["item_id"] for r in filter_recurring_for_project(rec, "gshock")] == ["certGS"]
    # tcg 監査: category='tcg' は自分のものなので残す (取りこぼさない)
    assert [r["item_id"] for r in filter_recurring_for_project(rec, "tcg")] == ["certTCG"]
    # mercari 監査: category='mercari' は自分のもの
    assert [r["item_id"] for r in filter_recurring_for_project(rec, "mercari")] == ["certMER"]
