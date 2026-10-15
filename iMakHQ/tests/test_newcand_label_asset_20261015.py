# -*- coding: utf-8 -*-
"""新規出品の種で決めたカードも、ラベルの記録 (カード単位) と鑑定番号の記録に残す
(2026-10-15 ユーザー「目視系は全部資産化するように指示したはず」)。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import newcand_confirm as N  # noqa: E402


class _PLL:
    def __init__(self):
        self.lab, self.certs = [], []

    def category_of(self, pid):
        return "pokemon"

    def key_for_psa(self, cat, meta):
        return f"{cat}|{meta['Brand']}|{meta['CardNumber']}"

    def record_picks(self, picks):
        self.lab += picks
        return len(picks)

    def remember_cert_pids(self, pairs):
        self.certs += pairs
        return len(pairs)


def _row(cert, pid):
    return ["", "", "https://jp.mercari.com/item/m1", "t", "", cert, "TCG", f"pokemon:{pid}", pid, "", "2026-10-15"]


def test_label_recorded_when_psa_record_exists_and_cert_always():
    p = _PLL()
    n_lab, n_cert = N.label_and_cert_records(
        [_row("111", "SV1s-083"), _row("222", "XY4-089"), _row("", "X")],
        {"111": {"Brand": "POKEMON JAPANESE", "CardNumber": "083"}}, p)
    assert (n_lab, n_cert) == (1, 2)
    assert p.lab == [("pokemon|POKEMON JAPANESE|083", "SV1s-083", "111")]
