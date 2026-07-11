"""2026-07-10 一括 resolver 解消の回帰アンカー (ユーザー「全部解決」依頼).

いずれも catalog に record 実在(or 追加済)で、brand→set mapping / edition照合 /
premium goods variant を配線した。fail-closed(誤 set 解決しない)を維持。
共有DB(products.sqlite)依存。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "integrations"))
import psa_to_csv as P  # noqa: E402


def _pk(brand, num, subj):
    r = P.lookup_pokemon(brand, num, subj, verbose=False)
    return r.get("card_id") if r else None


def _op(brand, num, subj):
    r = P.lookup_one_piece(brand=brand, card_number=num, subject=subj, verbose=False)
    return r.get("card_id") if r else None


def _gd(brand, num, subj):
    r = P.lookup_gundam(brand=brand, card_number=num, subject=subj, verbose=False)
    return r.get("card_id") if r else None


# --- Pokemon set-name → set-code mapping (record 実在) ---
def test_soulsilver_collection_maps_l1bss():
    assert _pk("POKEMON JAPANESE SOULSILVER COLLECTION", "021", "POLITOED") == "L1-Bss-021"


def test_pokekyun_collection_maps_cp3():
    assert _pk("POKEMON JAPANESE XY POKEKYUN COLLECTION", "032", "WALLY") == "CP3-032"


def test_dream_shine_collection_maps_cp5():
    assert _pk("POKEMON JAPANESE MYTHICAL & LEGENDARY DREAM SHINE COLLECTION",
               "014", "KELDEO") == "CP5-014"


def test_super_burst_impact_maps_sm8():
    # 2026-07-11: SUPER-BURST IMPACT #058 = 既存 SM8-058 (ブラッキー)
    assert _pk("POKEMON JAPANESE SUN & MOON SUPER-BURST IMPACT", "058", "UMBREON") == "SM8-058"


def test_sm12a_214_jirachi_hyper_rare_added():
    # 2026-07-11: SM12a Tag All Stars #214 Jirachi-GX HR (secret rare, resultAPI非掲載→追加)
    assert _pk("POKEMON JAPANESE SUN & MOON TAG TEAM GX ALL STARS",
               "214", "JIRACHI GX") == "SM12a-214"


def test_sm12_112_hyper_rare_added():
    assert _pk("POKEMON JAPANESE SUN & MOON ALTER GENESIS", "112", "ARCS DLGA PALKIA GX") == "SM12-112"


# --- One Piece: Girls Edition parallel (edition照合) ---
def test_girls_edition_pudding_resolves_ge():
    assert _op("ONE PIECE JAPANESE PREMIUM CARD COLLECTION -GIRLS EDITION-",
               "008", "CHARLOTTE PUDDING") == "ST07-008_GE"


def test_op_emotion_luffy_resolves_p041():
    assert _op("ONE PIECE JAPANESE PROMOS", "041", "MONKEY D LUFFY ONE PIECE EMOTION") == "P-041"


# --- Gundam: PB01 premium goods parallel ---
def test_pb01_premium_goods_heero_resolves_variant():
    assert _gd("GUNDAM JAPANESE PB01-PREMIUM GOODS SET -MOBILE SUIT GUNDAM WING-",
               "010", "HEERO YUY") == "ST02-010_PB01"


def test_gundam_normal_st02_still_base():
    # 非 premium goods の ST02 は base のまま(PB01 preference が暴発しない)
    assert _gd("GUNDAM JAPANESE ST02-WINGS OF ADVANCE", "010", "HEERO YUY") == "ST02-010"
