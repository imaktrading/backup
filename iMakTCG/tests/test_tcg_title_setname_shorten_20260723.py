# -*- coding: utf-8 -*-
"""タイトル80字調整の「カード名死守・Set名短縮」回帰テスト (2026-07-23)。

バグ: core だけで80字超の場合、旧実装は末尾語 pop で truncate → カード名(Character)が
途中で切れる。実害: 'PSA 10 Pokemon Japanese Sun & Moon—Unbroken Bonds #007/095 Reshiram &'
(Charizard-GX 欠落・69字) が生成され check_csv AI レビューが最優先指摘 (2026-07-23 run)。
対策: 任意要素 drop → Set 名短縮 (ダッシュ後半→前方語落とし) の順で吸収、Character/番号は不可侵。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcg_listing_fields import build_title_from_fields


def _fields(**kw):
    base = {
        "C:Game": "Pokemon",
        "C:Language": "Japanese",
        "C:Set": "",
        "C:Card Number": "",
        "C:Character": "",
    }
    base.update(kw)
    return base


def test_long_set_shortened_card_name_intact():
    """★本命: 実害ケース。Set をダッシュ後半に短縮してカード名全体+Year を残す。"""
    f = _fields(**{"C:Set": "Sun & Moon—Unbroken Bonds",
                   "C:Card Number": "007/095",
                   "C:Character": "Reshiram & Charizard-GX",
                   "C:Year Manufactured": "2019"})
    title = build_title_from_fields(f)
    assert title == ("PSA 10 Pokemon Japanese Unbroken Bonds #007/095 "
                     "Reshiram & Charizard-GX 2019")
    assert len(title) <= 80


def test_short_set_fits_unchanged():
    """80字に収まる通常ケースは従来どおりフル Set + 全要素。"""
    f = _fields(**{"C:Set": "Unbroken Bonds",
                   "C:Card Number": "007/095",
                   "C:Character": "Pikachu",
                   "C:Year Manufactured": "2019"})
    title = build_title_from_fields(f)
    assert title == "PSA 10 Pokemon Japanese Unbroken Bonds #007/095 Pikachu 2019"


def test_character_never_cut_even_without_dash():
    """ダッシュ無しの長い Set は前方の語から落とす。カード名は必ず全体が残る。"""
    chara = "Reshiram & Charizard-GX"
    f = _fields(**{"C:Set": "Super Ultra Mega Extended Premium Collection Booster Box Set",
                   "C:Card Number": "123/456",
                   "C:Character": chara})
    title = build_title_from_fields(f)
    assert chara in title, f"カード名が切れた: {title!r}"
    assert "#123/456" in title
    assert len(title) <= 80


def test_last_resort_truncate_no_crash():
    """Set 最短化でも超過する極端ケースは従来 truncate (例外を出さない)。"""
    f = _fields(**{"C:Set": "X",
                   "C:Card Number": "1",
                   "C:Character": "A" * 100})
    title = build_title_from_fields(f)
    assert len(title) <= 80
