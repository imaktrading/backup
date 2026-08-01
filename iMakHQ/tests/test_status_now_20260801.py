"""「現在地」の定義が4セッションで揃っていることの回帰テスト (2026-08-01)。

なぜ要るか (実害):
    ユーザーが ALPHA と BRAVO に同じ「現在地は?」を聞いたら **違う答えが返ってきた**。
    状態は動いていなかった (19:40〜19:54 で共有ファイルの変化ゼロ) ので、原因はデータではなく
    **各セッションが「現在地」を自分で定義して作文していたこと**。
    定義が無いものは担当ごとにブレる = 「その時々で判断が変わる」= program ではない。

    → 現在地は `status_now.py` の出力と定めた。**4つの CLAUDE.md 全部に同じ指示が要る**。
      1つでも欠けると、そのセッションだけまた作文を始める。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SESSIONS = ["iMakAdvisor", "iMakHQ", "iMakAlpha", "iMakBravo"]


def _claude_md(name):
    p = os.path.join(ROOT, name, "CLAUDE.md")
    assert os.path.exists(p), f"{name}/CLAUDE.md が無い"
    return io.open(p, encoding="utf-8").read()


def test_every_session_is_told_to_run_status_now():
    for s in SESSIONS:
        t = _claude_md(s)
        assert "status_now.py" in t, f"{s}: 現在地コマンドの指示が無い"


def test_every_session_is_told_not_to_compose():
    """『作文しない / 出力をそのまま示す』が消えていないこと。ここが緩むと再発する。"""
    for s in SESSIONS:
        t = _claude_md(s)
        assert "作文しない" in t, f"{s}: 『作文しない』が無い"
        assert "書き換えない" in t, f"{s}: 『出力自体を書き換えない』が無い"


def test_status_tool_exists_and_is_read_only():
    p = os.path.join(ROOT, "iMakHQ", "tools", "status_now.py")
    assert os.path.exists(p)
    src = io.open(p, encoding="utf-8").read()
    # 現在地を出すだけの道具。**実際に状態を変える操作**を持ち込まない。
    # (節名の「今日の commit」等は文字列として出るので、語ではなく操作で判定する)
    banned = ['"commit"', "'commit'", '"add"', "'add'",      # git 引数としての commit/add
              "--apply", "--commit", "ReviseFixedPriceItem", "RelistFixedPriceItem",
              "UPDATE ", "DELETE ", "INSERT ", "write_keys", "write_rows_to_tab"]
    for b in banned:
        assert b not in src, f"status_now.py に状態を変える操作が混ざっている: {b}"
    # ファイルを書き込みモードで開いていないこと
    assert not re.search(r"open\([^)]*['\"][wa]", src), "status_now.py が書込モードで open している"


def test_status_tool_reports_the_four_sections():
    """節を減らすと『何を現在地と呼ぶか』が担当ごとにブレ始める。"""
    src = io.open(os.path.join(ROOT, "iMakHQ", "tools", "status_now.py"),
                  encoding="utf-8").read()
    for sec in ("各担当の未処理", "出品の数字", "今日の commit", "次にやること"):
        assert sec in src, f"status_now.py に『{sec}』の節が無い"


def test_next_actions_are_quoted_from_daily_report_not_invented():
    """『次にやること』は daily_report の原文を出す (道具が勝手に作らない)。"""
    src = io.open(os.path.join(ROOT, "iMakHQ", "tools", "status_now.py"),
                  encoding="utf-8").read()
    assert "daily_report" in src
    assert re.search(r"いま誰待ちか", src), "daily_report の該当節を引く実装になっていない"
