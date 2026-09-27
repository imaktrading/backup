"""出品くん Console の後処理ログをファイルにも残す (2026-09-27, 残務 №365)。

画面だけだと 9/22 の書き戻し失敗の理由を後から追えなかった。run log 本体に書くと後処理の入力に
混ざる (NO-GO 行の二重拾い) ので別ファイル。*.log にすると「一番新しい走行ログ」の拾い方に混ざる。
"""
import os

SRC = open(os.path.join(os.path.dirname(__file__), "..", "console", "server.py"), encoding="utf-8").read()


def test_after_log_goes_to_separate_txt():
    i = SRC.index("def _to_log(text):")
    body = SRC[i:i + 1500]
    assert 'path + ".after.txt"' in body
    assert "fh.write" not in body            # run log 本体には書かない
