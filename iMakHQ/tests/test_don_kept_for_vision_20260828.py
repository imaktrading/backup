# -*- coding: utf-8 -*-
"""番号なし DON!! を Vision の前に落とさない (2026-08-28)。

依頼書: hq/requests/2026-08-28_act_code_proposals_tcg.md 提案3
回答書: 同 _response.md 提案3 GO

実測: `lookup_don(brand,'DON!! CARD')` → 一意特定不能 (score=0 / 候補267件)。
PSA が番号もキャラ名も出さないので **文字情報だけでは原理的に決まらない**。
ただし cert156843873 は PSA 写真が在るので Vision なら色とキャラが読める
(`lookup_don(vision_character=...)` の経路は既に実装済 psa_to_csv:2276)。
今までは Vision に届く前に preflight で落ちていた。
"""
from __future__ import annotations

import sys

sys.path.insert(0, r"C:\dev\iMak\iMakTCG")
import psa_to_csv as T  # noqa: E402

_PHOTO = {"CardImageUrl": "https://d1htnxwo4o0jhw.cloudfront.net/cert/x/large/y.jpg"}
_NOPHOTO = {"Subject": "DON!! CARD"}


def _gap(subject="DON!! CARD", num=None):
    return {"status": "GAP", "subject": subject, "num": num,
            "brand": "ONE PIECE JAPANESE PREMIUM CARD COLLECTION -ONE PIECE DAY'24-"}


def test_numberless_don_with_photo_is_kept():
    assert T.keep_for_vision(_gap(), _PHOTO) is True


def test_numberless_don_without_photo_is_dropped():
    """写真が無ければ Vision も使えない → 従来どおり落とす (fail-closed)。"""
    assert T.keep_for_vision(_gap(), _NOPHOTO) is False
    assert T.keep_for_vision(_gap(), None) is False


def test_don_with_card_number_is_not_special():
    """番号が在る DON は普通に引けるので、この救済の対象ではない。"""
    assert T.keep_for_vision(_gap(num="027"), _PHOTO) is False


def test_non_don_gap_is_still_dropped():
    assert T.keep_for_vision(_gap(subject="BOA HANCOCK"), _PHOTO) is False


def test_only_gap_is_rescued():
    """OUT-OF-SCOPE (参入しないゲーム) は写真があっても残さない。"""
    r = _gap()
    r["status"] = "OUT-OF-SCOPE"
    assert T.keep_for_vision(r, _PHOTO) is False


def test_preflight_block_keeps_it_before_queueing():
    """枠前除外の分岐が Vision 救済を **queue に積む前** に見ていること (回帰)。"""
    src = open(T.__file__, encoding="utf-8").read()
    i = src.find('if _st in ("GAP", "OUT-OF-SCOPE"):')
    assert i > 0
    block = src[i:i + 1200]
    assert "keep_for_vision(_r, _meta)" in block
    assert block.index("keep_for_vision") < block.index("_queue_finding"), \
        "先に落としてから救済しても Vision には届かない"
