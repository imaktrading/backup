"""鑑定番号ごとの過去の答えをラベルの記録に移す (2026-10-06 ユーザー「何で移してないの？」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_label_learned as L  # noqa: E402

META = {"1": {"Brand": "ONE PIECE JPN OP09", "CardNumber": "118", "Subject": "LUFFY"},
        "2": {"Brand": "ONE PIECE JPN OP09", "CardNumber": "118", "Subject": "LUFFY"},
        "3": {"Brand": "X", "CardNumber": "1", "Subject": "Y"}}


def test_backfill_moves_ok_and_chosen_only_once():
    vc = {"1": {"choice": "CHOSEN", "product_id": "one_piece:OP09-118"},
          "2": {"choice": "OK", "product_id": "OP09-118"},
          "3": {"choice": "NG", "product_id": "Z"},
          "4": {"choice": "OK", "product_id": "W"}}                    # キャッシュに無い → 移さない
    data = {}
    picks = L.backfill_picks(vc, META.get, lambda b: "one_piece", data)
    assert sorted(c for _, _, c in picks) == ["1", "2"]
    for k, pid, c in picks:
        L.remember(data, k, pid, cert=c)
    k = picks[0][0]
    assert L.learned_pid(data, k) == "OP09-118"
    assert L.backfill_picks(vc, META.get, lambda b: "one_piece", data) == []   # 2回目は何も足さない


def test_split_answers_stay_undecided():
    vc = {"1": {"choice": "OK", "product_id": "A"}, "2": {"choice": "OK", "product_id": "B"}}
    data = {}
    for k, pid, c in L.backfill_picks(vc, META.get, lambda b: "one_piece", data):
        L.remember(data, k, pid, cert=c)
    assert L.learned_pid(data, next(iter(data))) is None              # 割れたら目視で選ぶ
