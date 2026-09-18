"""補URL 目視: 前に出した順で回す / 補3本以下は今の仕入値の1.5倍まで (2026-09-19)。

ユーザー確定:
- 「目視画面にも『前に出した順』の回転を入れたい。全部に順番が回るように」
  並びが毎回同じ (ウォッチ多い順 → 補が少ない順) で、1回に見る件数を超えた分は
  毎回 同じ顔ぶれしか目に入っていなかった (実測: 対象190件)。
- 「今の仕入値以下なら出す → 今の仕入値の1.5倍までにしよう」
  (¥70,000 の上限は candidate を作る段で別に効く: global.yaml cost_sanity)
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import psa_hoju_fill as H


def test_一度も出していない物が先():
    t = [{"itemID": "A"}, {"itemID": "B"}, {"itemID": "C"}]
    got = H.rotate_by_last_shown(t, {"A": "2026-09-19", "B": "2026-09-10"})
    assert [x["itemID"] for x in got] == ["C", "B", "A"]


def test_同じ日付なら今までの並びのまま():
    t = [{"itemID": "A"}, {"itemID": "B"}]
    got = H.rotate_by_last_shown(t, {"A": "2026-09-10", "B": "2026-09-10"})
    assert [x["itemID"] for x in got] == ["A", "B"]      # 安定ソート


def test_台帳が空でも並びを壊さない():
    t = [{"itemID": "A"}, {"itemID": "B"}]
    assert H.rotate_by_last_shown(t, {}) == t


def test_補充は1点5倍まで():
    now = 34444
    assert H.candidate_cost_conflicts(int(now * 1.4), now, False, 0) is False
    assert H.candidate_cost_conflicts(int(now * 1.6), now, False, 0) is True


def test_入れ替えは1000円以上安い物だけ():
    now = 34444
    assert H.candidate_cost_conflicts(now - 1500, now, False, H.SWAP_MIN_GAIN) is False
    assert H.candidate_cost_conflicts(now - 500, now, False, H.SWAP_MIN_GAIN) is True
