"""神風のボタンを KAGOYA で動かす時の取り込み (2026-10-02)。

ボタンの間に家でも書かれた分を消さない / KAGOYA で変わった所だけを当てる。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import kagoya_button as B  # noqa: E402


def test_dict_keeps_home_writes_and_applies_server_changes():
    base = {"a": 1, "b": 2, "c": 3}
    srv = {"a": 1, "b": 20, "c": 3, "d": 4}          # KAGOYA: b を変え d を足した
    home = {"a": 1, "b": 2, "c": 3, "e": 5}          # 家: ボタンの間に e が足された (急ぎの探索の取り込み等)
    out, n, c = B.merge_dict(base, srv, home)
    assert out == {"a": 1, "b": 20, "c": 3, "d": 4, "e": 5}
    assert n == 2 and c == 0


def test_dict_delete_only_when_home_untouched():
    base = {"a": 1, "b": 2}
    srv = {}                                        # KAGOYA で両方消した (候補を使い切った等)
    home = {"a": 1, "b": 99}                        # 家で b を書き換えていた
    out, _n, _c = B.merge_dict(base, srv, home)
    assert out == {"b": 99}


def test_dict_conflict_prefers_server_and_counts():
    out, _n, c = B.merge_dict({"a": 1}, {"a": 2}, {"a": 3})
    assert out == {"a": 2} and c == 1


def test_jsonl_appends_only_new_lines():
    base = b'{"x":1}\n'
    srv = b'{"x":1}\n{"x":2}\n'
    home = b'{"x":1}\n{"y":9}\n'                    # 家でも1行足されていた
    out, c = B.merge_jsonl(base, srv, home)
    assert out == b'{"x":1}\n{"y":9}\n{"x":2}\n' and not c


def test_whole_file_rules():
    assert B.merge_bytes(b"a", b"a", b"z") == (None, False)       # KAGOYA で変わらず → 家のまま
    assert B.merge_bytes(b"a", b"b", b"a") == (b"b", False)       # 家が送った時のまま → KAGOYA
    assert B.merge_bytes(None, b"b", None) == (b"b", False)       # KAGOYA で新しくできた
    assert B.merge_bytes(b"a", b"b", b"c") == (b"b", True)        # 両方変わった → KAGOYA・ぶつかり


def test_merge_file_json_dict_roundtrip():
    base = json.dumps({"k": 1}).encode()
    srv = json.dumps({"k": 1, "n": 2}).encode()
    home = json.dumps({"k": 1, "h": 3}).encode()
    out, how, c = B.merge_file("x.json", base, srv, home)
    assert json.loads(out) == {"k": 1, "n": 2, "h": 3} and not c


def test_merge_file_json_unchanged_on_server_is_noop():
    b = json.dumps({"k": 1}).encode()
    out, how, c = B.merge_file("x.json", b, b, json.dumps({"k": 1, "h": 2}).encode())
    assert out is None and not c


def test_remote_cmd_relays_review_port_and_quotes():
    cfg = {"key": "k", "user": "u", "host": "h"}
    cmd = B.remote_ssh_cmd(cfg, "C:/dev/iMak/iMakHQ/tools", ["A=1"], ["psa_hoju_fill.py", "it's"])
    assert "18765:127.0.0.1:18765" in cmd
    assert "remote-run" in cmd[-1] and "'it''s'" in cmd[-1] and "--env 'A=1'" in cmd[-1]


def test_mirror_sends_only_new_or_changed():
    assert B.mirror_todo({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}) == ["b", "c"]


def test_carry_name_roundtrip_inside_and_outside_dev():
    a = r"C:\dev\iMak_data\hq\x.json"
    b = r"C:\Users\imax2\OneDrive\デスクトップ\03_PSA再仕入れ候補_20261002.csv"
    assert B.carry_name(a) == "iMak_data/hq/x.json"
    assert B.carry_name(b).startswith("ABS/C/Users/")
    assert os.path.normcase(B.home_path(B.carry_name(a))) == os.path.normcase(a)
    assert os.path.normcase(B.home_path(B.carry_name(b))) == os.path.normcase(b)


def test_prune_keeps_newest(tmp_path):
    for n in ["20261002_100000", "20261002_110000", "20261002_120000"]:
        (tmp_path / n).mkdir()
    B.prune_runs(str(tmp_path), keep=2)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["20261002_110000", "20261002_120000"]


def test_token_fingerprint_changes_only_with_reauthorization():
    a = json.dumps({"access_token": "x1", "refresh_token": "R"}).encode()
    b = json.dumps({"access_token": "x2", "refresh_token": "R"}).encode()     # 2時間ごとの取り直し
    c = json.dumps({"access_token": "x3", "refresh_token": "R2"}).encode()    # 認可のやり直し
    assert B.token_fingerprint(a) == B.token_fingerprint(b) != B.token_fingerprint(c)
    assert B.token_fingerprint(b"broken") is None


def test_jsonl_rewritten_on_server_is_labeled_whole_file():
    out, how, c = B.merge_file("x.jsonl", b"a\nb\n", b"b\n", b"a\nb\n")
    assert out == b"b\n" and how == "丸ごと" and not c
    out, how, c = B.merge_file("x.jsonl", b"a\n", b"a\nb\n", b"a\n")
    assert out == b"a\nb\n" and how == "追記"


def test_remote_exit_code_reaches_home():
    """★2026-10-03: PowerShell が python の終了コードを返さず、「席が取れない (75)」が家に届かなかった
    → 家で動かす代わりに失敗で止まった。remote のコマンドは終了コードを明示して返す。"""
    cmd = B.remote_ssh_cmd({"key": "k", "user": "u", "host": "h"}, r"C:/dev/x", [], ["a.py"])
    assert cmd[-1].rstrip().endswith("exit $LASTEXITCODE")
