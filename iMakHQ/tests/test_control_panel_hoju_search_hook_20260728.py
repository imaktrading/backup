"""出品直後の補URL候補検索は「自動」ではなく「ボタン」であること (2026-07-28).

経緯: 当初 CSV生成直後の後処理チェーンに自動実行(Step 4d)を入れたが、補URL検索の対象条件は
**itemID が入っている(=出品済)**行なので、その時点の新規カードは itemID が無く拾えなかった。
itemID を書き終えた時点は人しか知らないため、自動化をやめてボタンにした(ユーザー提案)。

守るべき性質:
  1. 役に立たない位置の自動実行が復活していない
  2. ボタンは検索(slice2)だけ。書込系(confirm/--write)を混ぜない = 有人確証を飛ばさない
  3. 件数上限がある(無制限に走らせると BAN リスク/長時間化)
"""
import os
import re

CP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control_panel.py")


def _src():
    return open(CP, encoding="utf-8").read()


def _button_block():
    s = _src()
    i = s.index("🆕 PSA 補URL ① 当日分")
    return s[i - 400:i + 400]


def test_auto_hook_is_not_reintroduced():
    """CSV生成直後の自動実行は当日分に効かない。復活させない。"""
    assert "Step 4d" not in _src()


def test_button_exists():
    assert "🆕 PSA 補URL ① 当日分" in _src()


def test_button_runs_search_only():
    b = _button_block()
    assert "psa_hoju_fill.py" in b
    assert '"search"' in b
    assert '"confirm"' not in b
    assert "--write" not in b


def test_button_has_a_limit():
    assert re.search(r'"--limit=\d+"', _button_block())


def test_button_skips_postprocess():
    """ユーティリティなので新規出品用の後処理チェーンを回さない。"""
    assert '"skip_postprocess": True' in _button_block()
