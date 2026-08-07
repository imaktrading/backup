"""verify→build の確定パース回帰テスト (2026-06-15)。

固定する不変条件 (ユーザー指摘「10対象→HTMLで6確定→以降6件」):
  - HTML で OK/CHOSEN した cert **だけ** が build 対象 (confirmed) になる。
  - NONE/NG/PENDING/未回答 は confirmed に入らない (= 出品しない、fail-closed)。
  - = 確認した数がそのまま以降の処理対象 (10件中6件確認なら6件)。
"""
import os
import sys

_TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from post_psa_review import parse_confirmations  # noqa: E402


def test_only_confirmed_proceed_6_of_10():
    # 10件中: OK 4 + CHOSEN 2 = 6 確定 / NONE 2 + NG 1 + PENDING 1 = 4 除外
    results = [
        {"cert": "c1", "choice": "OK", "expected": "S1-001"},
        {"cert": "c2", "choice": "OK", "expected": "S1-002"},
        {"cert": "c3", "choice": "OK", "expected": "S1-003"},
        {"cert": "c4", "choice": "OK", "expected": "S1-004"},
        {"cert": "c5", "choice": "CHOSEN", "selected_pid": "S1-099"},
        {"cert": "c6", "choice": "CHOSEN", "selected_pid": "S1-100"},
        {"cert": "c7", "choice": "NONE"},
        {"cert": "c8", "choice": "NONE"},
        {"cert": "c9", "choice": "NG", "expected": "S1-009"},
        {"cert": "c10", "choice": "PENDING"},
    ]
    confirmed, none_records = parse_confirmations(results)
    assert len(confirmed) == 6                       # ★確認した6件だけ
    assert set(confirmed) == {"c1", "c2", "c3", "c4", "c5", "c6"}
    assert confirmed["c5"] == "S1-099"               # CHOSEN は選び直し pid
    assert confirmed["c6"] == "S1-100"
    assert "c7" not in confirmed and "c10" not in confirmed
    # NONE/NG は catalog 宿題候補に
    assert {r["cert"] for r in none_records} == {"c7", "c8", "c9"}


def test_chosen_without_pid_excluded():
    # CHOSEN なのに selected_pid 欠落 → 確定にしない (fail-closed)
    confirmed, _ = parse_confirmations([{"cert": "x", "choice": "CHOSEN"}])
    assert confirmed == {}


def test_empty_and_missing_cert():
    confirmed, none = parse_confirmations([{"choice": "OK", "expected": "X"}, {}])
    assert confirmed == {} and none == []
