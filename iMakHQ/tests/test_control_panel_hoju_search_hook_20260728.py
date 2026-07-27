"""入稿直後の「当日出品分 補URL候補検索」フックの回帰テスト (2026-07-28).

出品直後は補URL 0本で一番死にやすい。夜間 search を待たず入稿直後に slice2 を回すフックを
control_panel に入れた。壊れやすいのは以下2点なので固定する:
  1. 未 import の名前 (datetime 等) を使って NameError で落ちる
  2. 書込系 (confirm/--write) を誤って自動実行する = 有人確証を飛ばす fail-open
"""
import os
import re

CP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control_panel.py")


def _hook_src():
    src = open(CP, encoding="utf-8").read()
    i = src.index("# Step 4d:")
    j = src.index("def _runs_new_listing_dedupe", i)
    return src[i:j]


def test_hook_exists_and_runs_search_only():
    h = _hook_src()
    assert "psa_hoju_fill.py" in h
    assert '"search"' in h
    # ★書込系を自動実行しない (補URL 書込は slice3=有人確証のまま)
    assert '"confirm"' not in h
    assert "--write" not in h


def test_hook_is_background_and_non_fatal():
    """listing フローを待たせない/失敗しても出品を壊さない。"""
    h = _hook_src()
    assert "Popen" in h            # 待たない
    assert "subprocess.run" not in h
    assert "except Exception" in h  # 失敗しても続行


def test_hook_uses_only_imported_names():
    """control_panel は `import datetime` していない (関数内で from datetime import datetime)。
    トップレベル import 済みの名前だけを使うこと。"""
    h = _hook_src()
    assert "datetime." not in h
    src = open(CP, encoding="utf-8").read()
    top = src[:src.index("def ")]
    for name in re.findall(r"\b(os|sys|subprocess|time)\.", h):
        assert re.search(rf"^import {name}$", top, re.M), f"{name} が top-level import されていない"


def test_hook_has_a_limit():
    """無制限に走らせると BAN リスク/長時間化。件数上限を必ず付ける。"""
    assert re.search(r"--limit=\d+", _hook_src())
