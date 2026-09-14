"""status_now の「次にやること」は daily_report の最上段だけから引く (2026-09-14).

最上段に節が無い日に、ずっと下の8月の『いま誰待ちか』表を出していた。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import status_now  # noqa: E402

OLD = "## 2026-08-01 [出品専任] 古い日\n\n## 4. いま誰待ちか\n| 補URL | live PSA 254件 |\n\n---\n"


def test_old_table_below_top_is_not_used():
    text = "## 2026-09-14 [Advisor] 今日\n\n**締めの状態**: 0件\n\n" + OLD
    out = "\n".join(status_now.next_actions_from(text))
    assert "254件" not in out
    assert "節なし" in out


def test_top_entry_section_is_used():
    text = "## 2026-09-14 [Advisor] 今日\n\n## 4. いま誰待ちか\n| 新しい | 行 |\n\n---\n" + OLD
    out = status_now.next_actions_from(text)
    assert any("新しい" in ln for ln in out)
    assert not any("254件" in ln for ln in out)


def test_decision_block_in_top_entry_is_used():
    text = ("## 2026-09-14 [Advisor] 今日\n\n**ユーザー判断待ち**\n- A を決める\n\n**★反省**: x\n\n"
            + OLD)
    out = status_now.next_actions_from(text)
    assert any("A を決める" in ln for ln in out)
    assert not any("反省" in ln for ln in out)
