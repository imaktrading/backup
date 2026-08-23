# -*- coding: utf-8 -*-
"""🔍CSV監査くん を2回押しても、2回目は何もしない (2026-08-23)。

なぜ:
  🤖自動 は **入稿の前に** 監査くんを走らせている。その後で 🔍CSV監査くん を押しても
  同じことの2回目にしかならない。実際 8/20・8/21・8/22・8/23 の4走行とも、自動の直後に
  押されていて、4回とも新しい指摘は出ていない (裏の自動対応も「もう走っている」で空振り)。

  ただしボタン自体は消せない。ガチャ・一番くじ・G-shock の生成器は自分で監査を呼ばないので、
  あのボタンがそれらの唯一の入稿前チェックになっている。
  → 「押すな」ではなく「押す必要が無い時は機械が言う」。

見るのは **中身 (バイト列)**。ファイル名でも時刻でもないので、1行でも直せば必ず見直す。
"""
import json
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(HQ, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(HQ, "tools"))

import csv_auditor as A  # noqa: E402


def _csv(tmp_path, body="a,b\n1,2\n", name="tcg_upload_x.csv"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_first_time_is_not_audited(tmp_path):
    memo = str(tmp_path / "memo.json")
    assert A.already_audited(_csv(tmp_path), memo) == ""


def test_remembers_and_reports_same_content(tmp_path):
    memo = str(tmp_path / "memo.json")
    p = _csv(tmp_path)
    assert A.remember_audited(p, memo) is True
    assert A.already_audited(p, memo)          # 時刻文字列が返る


def test_one_character_change_makes_it_look_again(tmp_path):
    """1文字でも変わったら「もう見た」と言わない (見落としを作らない)。"""
    memo = str(tmp_path / "memo.json")
    p = _csv(tmp_path, "a,b\n1,2\n")
    A.remember_audited(p, memo)
    assert A.already_audited(p, memo)
    with open(p, "a", encoding="utf-8") as f:
        f.write("3,4\n")
    assert A.already_audited(p, memo) == "", "中身が変わったのに素通りしている"


def test_different_csv_is_independent(tmp_path):
    memo = str(tmp_path / "memo.json")
    a = _csv(tmp_path, name="tcg_upload_a.csv")
    b = _csv(tmp_path, body="x,y\n9,9\n", name="tcg_upload_b.csv")
    A.remember_audited(a, memo)
    assert A.already_audited(b, memo) == ""


def test_unreadable_file_is_never_remembered(tmp_path):
    """読めないものを「見た」ことにしない (fail-closed)。"""
    memo = str(tmp_path / "memo.json")
    missing = str(tmp_path / "no_such.csv")
    assert A.csv_fingerprint(missing) == ""
    assert A.remember_audited(missing, memo) is False
    assert A.already_audited(missing, memo) == ""


def test_memo_does_not_grow_forever(tmp_path):
    memo = str(tmp_path / "memo.json")
    for i in range(A._AUDITED_KEEP + 10):
        A.remember_audited(_csv(tmp_path, body=f"a\n{i}\n", name=f"c{i:03}.csv"), memo)
    assert len(json.load(open(memo, encoding="utf-8"))) <= A._AUDITED_KEEP


def test_broken_memo_file_does_not_crash(tmp_path):
    memo = str(tmp_path / "memo.json")
    open(memo, "w", encoding="utf-8").write("{ こわれている")
    assert A.already_audited(_csv(tmp_path), memo) == ""


# ── ボタンを押した時の動き ────────────────────────────────────────
def test_second_press_does_not_run_the_audit(tmp_path, monkeypatch, capsys):
    p = _csv(tmp_path)
    monkeypatch.setattr(A, "_AUDITED_MEMO", str(tmp_path / "memo.json"))
    ran = []
    monkeypatch.setattr(A, "audit", lambda *a, **k: ran.append(1) or 0)

    assert A.main(["--csv", p]) == 0
    assert len(ran) == 1                       # 1回目は普通に監査する

    assert A.main(["--csv", p]) == 0
    assert len(ran) == 1, "2回目も監査してしまっている"
    assert "もう見ています" in capsys.readouterr().out


def test_force_runs_anyway(tmp_path, monkeypatch):
    p = _csv(tmp_path)
    monkeypatch.setattr(A, "_AUDITED_MEMO", str(tmp_path / "memo.json"))
    ran = []
    monkeypatch.setattr(A, "audit", lambda *a, **k: ran.append(1) or 0)
    A.main(["--csv", p])
    A.main(["--csv", p, "--force"])
    assert len(ran) == 2


def test_content_change_runs_again(tmp_path, monkeypatch):
    """裏の自動対応が行を落とした後などは、ちゃんともう一度見る。"""
    p = _csv(tmp_path)
    monkeypatch.setattr(A, "_AUDITED_MEMO", str(tmp_path / "memo.json"))
    ran = []
    monkeypatch.setattr(A, "audit", lambda *a, **k: ran.append(1) or 0)
    A.main(["--csv", p])
    with open(p, "a", encoding="utf-8") as f:
        f.write("5,6\n")
    A.main(["--csv", p])
    assert len(ran) == 2


def test_dry_run_never_remembers(tmp_path, monkeypatch):
    """下見 (dry-run) は「見た」ことにしない。本番の監査を飛ばさせない。"""
    p = _csv(tmp_path)
    monkeypatch.setattr(A, "_AUDITED_MEMO", str(tmp_path / "memo.json"))
    ran = []
    monkeypatch.setattr(A, "audit", lambda *a, **k: ran.append(1) or 0)
    A.main(["--csv", p, "--dry-run"])
    A.main(["--csv", p])
    assert len(ran) == 2, "dry-run が本番の監査を飛ばしている"
