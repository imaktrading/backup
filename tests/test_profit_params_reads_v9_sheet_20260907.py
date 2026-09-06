"""価格の元シートは V9 一枚だけ、を守る回帰テスト (2026-09-07).

背景:
  価格計算 (`pricing_engine`) が読んでいたのは `1P1yf...` = 2026-05-18 に V4 から取った
  **複製**で、人が編集していなかった。一方ユーザーが実際に編集しているのは V9。
  2枚あるので片方だけ直すと価格がズレる (実際にズレていた: 一番くじ / フィギュアの
  送料想定が V9 だけ 3000→4000 に更新され、価格計算は 3000 のまま = $10 低く出していた)。

  = 埋もれた第二 SSOT。1P1yf に戻らないことをテストで固定する。
  経緯: hq/requests/2026-09-03_pricing_sheet_source_1P1yf_vs_v9_ssot_check*.md
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "iMakeBayAPI"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import profit_params  # noqa: E402

V9_SHEET_ID = "1YLnR4aW5cgjquYXUaNPb_hnVwrHegobZyh-eAT6tVM0"
OBSOLETE_COPY_ID = "1P1yfzWogDr3aw4aB8Yy1PkJzp1rEGNt5s_bAeXW5Pl4"


def test_gsheet_url_points_to_v9():
    assert V9_SHEET_ID in profit_params.GSHEET_URL


def test_obsolete_v4_copy_is_not_referenced():
    """複製シートへの参照が復活したら落とす (= 第二 SSOT の再発防止)."""
    assert OBSOLETE_COPY_ID not in profit_params.GSHEET_URL
    src = (SCRIPT_DIR / "profit_params.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert OBSOLETE_COPY_ID not in code
