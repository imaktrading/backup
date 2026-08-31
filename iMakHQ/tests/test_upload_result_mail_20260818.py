# -*- coding: utf-8 -*-
"""自動出品の結果メールが実際に飛ぶこと (2026-08-18).

実害:
  `ebay_upload_csv.py` は `--result-json` を **受け取るだけで一度も書いていなかった**。
  結果ファイルが無いと `control_panel._mail_upload_result` が黙って return するので、
  **自動出品のメールが一度も飛ばない**。人は「まだ動いている」と思って待ち続ける
  (2026-08-18 の初走行で実際に 19分 待った)。

守りたいこと:
  1. 出品結果を **必ず** 書く (0件でも失敗でも)。
  2. 結果ファイルが無い時は **黙らない**。
  3. 前回の結果を今回の結果としてメールしない (走行前に消す)。
  4. 0件でもメールは出す。「走ったが0件」と「走らなかった」を区別できるのが用途。
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import ebay_upload_csv as up  # noqa: E402

CP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "control_panel.py")


def _cp_src():
    return io.open(CP, encoding="utf-8").read()


def _cp_func(name):
    """control_panel は tkinter を import するので純関数だけ切り出して評価する."""
    src = _cp_src()
    i = src.index(f"def {name}")
    ns = {}
    exec(src[i:src.index("\ndef ", i + 1)], ns)          # noqa: S102
    return ns[name]


class TestResultIsAlwaysWritten:
    def test_writes_listed_items(self, tmp_path):
        p = tmp_path / "last_upload_result.json"
        r = up.build_result("tcg_upload_1.csv", True, 2, 0,
                            [("PSA10-1", "820013549916"), ("PSA10-2", "820013549917")], [])
        assert up.write_result(str(p), r) is True
        got = json.loads(p.read_text(encoding="utf-8"))
        assert got["ok"] == 2 and got["ng"] == 0 and got["write"] is True
        assert got["listed"][0] == {"label": "PSA10-1", "item_id": "820013549916"}

    def test_writes_even_when_nothing_listed(self, tmp_path):
        """0件でも書く。書かないと『走らなかった』と区別が付かない."""
        p = tmp_path / "r.json"
        assert up.write_result(str(p), up.build_result("x.csv", True, 0, 0, [], [])) is True
        assert json.loads(p.read_text(encoding="utf-8"))["listed"] == []

    def test_records_failures_and_early_stop(self, tmp_path):
        p = tmp_path / "r.json"
        r = up.build_result("x.csv", True, 0, 1, [], [("PSA10-9", "Failure: 送料ポリシー無し")],
                            stopped_early=True)
        up.write_result(str(p), r)
        got = json.loads(p.read_text(encoding="utf-8"))
        assert got["stopped_early"] is True
        assert got["failed"][0]["error"].startswith("Failure")

    def test_verify_only_is_recorded(self):
        assert up.build_result("x.csv", False, 3, 0, [], [])["write"] is False

    def test_no_path_is_not_an_error(self):
        assert up.write_result("", up.build_result("x.csv", True, 0, 0, [], [])) is False

    def test_main_writes_the_result(self):
        src = io.open(os.path.join(os.path.dirname(__file__), "..", "tools",
                                   "ebay_upload_csv.py"), encoding="utf-8").read()
        # 2026-08-27: one path -> every path returned by result_paths().
        # Same invariant: never accept --result-json without writing it.
        assert "if write_result(_p, _res):" in src
        assert "for _p in result_paths(a.result_json, a.csv):" in src, \
            "--result-json を受け取るだけで書いていない (メールが飛ばない)"


class TestMailIsSentEvenForZero:
    def test_zero_listing_still_produces_a_mail(self):
        subject, body = _cp_func("build_upload_mail")({"listed": [], "ng": 0, "write": True})
        assert "0件" in subject and "自動出品 0件" in body

    def test_verify_only_is_visible_in_the_mail(self):
        subject, body = _cp_func("build_upload_mail")({"listed": [], "ng": 0, "write": False})
        assert "検証のみ" in subject and "出品していません" in body

    def test_failures_are_listed_in_the_body(self):
        _, body = _cp_func("build_upload_mail")({
            "listed": [], "ng": 1, "write": True,
            "failed": [{"label": "PSA10-9", "error": "Failure: 送料ポリシー無し"}]})
        assert "PSA10-9" in body and "送料ポリシー無し" in body

    def test_early_stop_is_visible(self):
        _, body = _cp_func("build_upload_mail")({
            "listed": [], "ng": 1, "write": True, "stopped_early": True})
        assert "途中停止" in body

    def test_mailer_no_longer_returns_silently_on_empty(self):
        src = _cp_src()
        i = src.index("def _mail_upload_result")
        body = src[i:src.index("\ndef ", i + 1)]
        assert 'if not (result.get("listed") or result.get("ng")):' not in body, \
            "0件で黙ると『走ったのか分からない』が残る"


class TestStaleResultIsNotMailed:
    def test_tail_removes_the_previous_result_first(self):
        src = _cp_src()
        i = src.index("def _run_auto_full_tail")
        body = src[i:src.index("\ndef ", i + 1)]
        assert "os.remove(result_json)" in body, \
            "前回の結果が残っていると、今回失敗しても前回の成功をメールしてしまう"
        assert body.index("os.remove(result_json)") < body.index("ebay_upload_csv.py")

    def test_missing_result_is_reported_not_swallowed(self):
        src = _cp_src()
        i = src.index("def _mail_upload_result")
        body = src[i:src.index("\ndef ", i + 1)]
        assert "出品結果ファイルが無い" in body
