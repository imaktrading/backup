"""lookup()['set_name'] の fallback に stored (specs.set_name_ebay) を挟む (2026-08-17).

背景:
    _row_to_dict は 導出 → raw の順で set_name を決めていた。導出が空振りした行では
    **生の日本語セット名** または **None** がそのまま C:Set に流れる。
    stored に正しい eBay 値があるのに使っていなかった (pokemon 8,367 行)。

      - M1L-001: 導出 '拡張パック「メガブレイブ」' (生の日本語) / stored 'Scarlet & Violet—Mega Brave'
      - SVM-001: 導出 None (= C:Set 空)                    / stored 'Scarlet & Violet Promo'

    ★導出と stored が両方非空で食い違う行 (pokemon 7,408) は **触らない**。
      どちらが正かは facet ごとに逆転するため (MC-* は stored が正 / S4a-* は yaml が正)、
      推測で寄せない。従来どおり導出を優先する。
"""
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))

from iMakCatalog import api  # noqa: E402


def _row(**kw):
    """_row_to_dict に渡す sqlite3.Row 相当の dict ラッパ."""
    base = {
        "category": "pokemon_tcg",
        "product_id": "TEST-001",
        "name": "テスト",
        "name_jp": None,
        "name_en": "Test",
        "name_en_source": None,
        "set_name": None,
        "set_name_official": None,
        "card_set_id": None,
        "language": "ja",
        "specs": None,
        "images": None,
        "source": "test",
        "source_url": None,
        "updated_at": None,
        "variants": None,
        "alias_of": None,
    }
    base.update(kw)

    class _R(dict):
        def keys(self):
            return list(super().keys())

    return _R(base)


def test_stored_used_instead_of_raw_japanese():
    """導出が空振りした行で、生の日本語ではなく stored の eBay 値を返す."""
    # ★2026-08-23: 元は 拡張パック「メガブレイブ」 を使っていたが、変換表に行を足した
    #   ので導出が当たるようになった (= このテストの前提から外れた)。
    #   導出が空振りする弾に差し替える。値は stored がそのまま返ることだけを見る。
    d = api._row_to_dict(_row(
        product_id="ZZZ-001",
        set_name_official="拡張パック「変換表に無い弾」",
        specs='{"set_name_ebay": "Some Stored Value"}',
    ))
    assert d["set_name"] == "Some Stored Value"


def test_stored_fills_when_derive_is_none():
    """official が無く導出 None の promo 行でも stored で C:Set が埋まる."""
    d = api._row_to_dict(_row(
        product_id="SVM-001",
        set_name_official=None,
        specs='{"set_name_ebay": "Scarlet & Violet Promo"}',
    ))
    assert d["set_name"] == "Scarlet & Violet Promo"


def test_derive_still_wins_when_both_present():
    """導出と stored が両方非空なら従来どおり導出を優先 (勝手に寄せない)."""
    d = api._row_to_dict(_row(
        category="one_piece_tcg",
        product_id="OP06-022",
        set_name_official="BOOSTER PACK -WINGS OF THE CAPTAIN- [OP-06]",
        specs='{"set_name_ebay": "SOMETHING ELSE"}',
    ))
    assert d["set_name"] == "Wings of the Captain"


def test_falls_back_to_raw_when_no_map_and_no_stored():
    """導出も stored も無ければ raw をそのまま返す (従来どおり)."""
    d = api._row_to_dict(_row(
        category="workman",
        product_id="workman:35345",
        set_name_official="ファンウエア・ペルチェ",
        specs=None,
    ))
    assert d["set_name"] == "ファンウエア・ペルチェ"
