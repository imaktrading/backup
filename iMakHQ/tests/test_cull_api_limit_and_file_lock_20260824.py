"""2026-08-24 に実際に踏んだ2つを固定する。

1. 確認用一覧が開きっぱなしだと PermissionError で落ち、**送信まで巻き添え**になった。
   一覧は おまけ なので、書けなくても本処理は続ける。
2. GetItem が ErrorCode 518 (1日の上限超過) で全滅し、200件中149件が「状態を取れない」に
   落ちた。そのまま送ると **確認できた少数だけ**を送る形になり、判断の母数が壊れる。
   半数以上取れなければ中止する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

SRC = os.path.join(os.path.dirname(__file__), "..", "tools", "cull_end.py")


def _src():
    return open(SRC, encoding="utf-8").read()


def test_candidate_list_failure_is_not_fatal():
    """★一覧が書けなくても落ちない (開きっぱなしで PermissionError を踏んだ)."""
    src = _src()
    i = src.find("確認用一覧は **おまけ**")
    assert i > 0, "おまけである旨の記録が無い"
    body = src[i:i + 1200]
    assert "except OSError" in body
    assert "一覧なしで続行" in body


def test_candidate_list_has_fallback_path():
    """デスクトップが書けない時は別の場所に出す (黙って消さない)."""
    src = _src()
    assert "CULL候補_" in src


def test_stops_when_most_states_unavailable():
    """★半数以上の状態が取れなければ中止する (母数が壊れたまま送らない)."""
    src = _src()
    assert "1日の上限" in src
    i = src.find("半数以上が取れていません")
    assert i > 0
    assert "return" in src[i:i + 400], "警告するだけで続行している"


def test_limit_message_tells_when_to_retry():
    """いつ戻るかを書く (待てば直ると分かるようにする)."""
    assert "16時" in _src()


def test_send_happens_after_the_limit_guard():
    """上限ガードは送信より前 (後ろだと意味がない)."""
    src = _src()
    i_guard = src.find("半数以上が取れていません")
    i_send = src.find("end_on_ebay(picked)")
    assert 0 < i_guard < i_send
