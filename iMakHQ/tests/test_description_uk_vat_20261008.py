# -*- coding: utf-8 -*-
"""説明文のテンプレート全部に英国の VAT の1行がある (2026-10-08)。

英国バイヤーが £140 の注文で受け取り時に VAT を請求され、「関税を払っていない」と返金を求めた
(注文 18-15195-45996)。DDU の記載はあったが英国の名前が無かった → 新規の出品から英国の項を足す。
"""
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES = ["iMakeBayAPI/tmpl.html", "iMakG-shock/GSHOCK.txt", "iMakHQ/GACHA.txt",
             "iMakMercari/NEW.txt", "iMakMercari/NEW_workman.txt", "iMakMercari/USED.txt",
             "iMakTCG/PSA10_snkrdunk.txt", "iMak_ichibankuji/ICHIBANKUJI.txt"]


@pytest.mark.parametrize("rel", TEMPLATES)
def test_uk_vat_section_before_ddu(rel):
    s = open(os.path.join(ROOT, rel), encoding="utf-8-sig").read()
    uk = s.find("For UK Buyers")
    ddu = s.find("For Buyers in All Other Countries")
    assert uk != -1 and ddu != -1 and uk < ddu
    assert "&pound;135" in s and "Royal Mail" not in s[uk:ddu]   # 運ぶ会社を問わない書き方


def test_templates_used_on_kagoya_are_sent():
    # KAGOYA で動く生成 (PSA 自動・ガチャ・Tシャツ/モンベル/ワークマン) の説明文は KAGOYA へ送る一覧に入っている
    import sys
    sys.path.insert(0, os.path.join(ROOT, "iMakHQ", "tools"))
    import kagoya_offload as K
    sent = {p.replace("\\", "/") for p in K._code_files()}
    for rel in ("iMakHQ/GACHA.txt", "iMakTCG/PSA10_snkrdunk.txt", "iMakMercari/NEW.txt",
                "iMakMercari/NEW_workman.txt", "iMakMercari/USED.txt"):
        assert rel in sent, rel
