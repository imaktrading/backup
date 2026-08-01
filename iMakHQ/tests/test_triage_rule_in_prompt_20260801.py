"""「1丁目1番地」の判定手順が **全 worktree の起動プロンプトに必ず載る** ことの回帰テスト。

2026-08-01 ユーザー確定:
    「セッションが変わっても、誰が担当になっても」効かせること。
    グローバル CLAUDE.md にも同文を置いているが、headless セッションは **起動プロンプトが
    行動を支配する**ので、そこに載っていなければ守られない。
    このテストは「誰かがプロンプトを整理した拍子に手順が落ちる」ことを防ぐ唯一の砦。

手順そのもの (文言を変えないこと。変えると担当ごとに解釈が割れる):
    ① カタログのデータは正しいのか
    ② 出品くんの引き方は正しいのか
    ①正→②を修正 / ②正→①を修正 / 両方誤→両方 / 両方正→直すものは無い
"""
import os
import sys

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import dispatch_worktree as dw  # noqa: E402

MUST_APPEAR = [
    "カタログのデータは正しいのか",
    "出品くんの引き方は正しいのか",
    "①が正しいなら → ②を修正",
    "②が正しいなら → ①を修正",
    "①②とも誤りなら → 両方直す",
    "①②とも正しいなら → 直すものは無い",
    "5つ目は存在しない",
    "canonical KEY だけ",
]


def _prompts():
    from pathlib import Path
    wt = next(iter(dw.TARGETS))
    return {
        "draft": dw._build_prompt(wt, [Path("x/2026-08-01_dummy.md")]),
        "implement": dw._build_implement_prompt(wt, [Path("x/2026-08-01_dummy_response.md")]),
    }


def test_triage_rule_is_in_every_prompt():
    for mode, p in _prompts().items():
        for phrase in MUST_APPEAR:
            assert phrase in p, f"{mode} プロンプトに『{phrase}』が無い"


def test_rule_comes_before_the_task_list():
    """手順は**作業指示より前**に置く。後ろに置くと読み飛ばされる。"""
    for mode, p in _prompts().items():
        i_rule = p.index("カタログのデータは正しいのか")
        i_task = p.index("【やること】")
        assert i_rule < i_task, f"{mode}: 手順が【やること】より後ろにある"


def test_rule_says_do_not_add_conditions():
    """条件・例外を足すのを禁じる一文が消えていないこと (ユーザーが明示的に拒否した)。"""
    for mode, p in _prompts().items():
        assert "条件や例外を足さない" in p, mode


def test_rule_routes_lookup_defects_away_from_catalog():
    """②が原因の件をカタログに投げない、が残っていること (堂々巡りの直接原因)。"""
    for mode, p in _prompts().items():
        assert "②が原因ならカタログに依頼を出さず" in p, mode
