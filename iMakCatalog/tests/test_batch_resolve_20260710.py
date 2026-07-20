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


def test_cruel_traitor_yveltal_break_rekeyed_xy11():
    # 2026-07-12: XY11 冷酷の反逆者 #034 Yveltal BREAK は cardID-32100 fallback key で入っていた
    #   → XY11-034 に re-key (CRUEL TRAITOR→XY11 mapping は既存)。
    assert _pk("POKEMON JAPANESE XY CRUEL TRAITOR", "034", "YVELTAL BREAK") == "XY11-034"


def test_ex_battle_boost_mewtwo_added():
    # 2026-07-14: EXバトルブースト(EBB, BW期)#045 Mewtwo EX を追加 + EX BATTLE BOOST→EBB mapping
    assert _pk("POKEMON JAPANESE BLACK & WHITE EX BATTLE BOOST", "045", "MEWTWO EX") == "EBB-045"


def test_night_unison_067_hyper_rare_added():
    # 2026-07-16: SM9a Night Unison #067 Gardevoir & Sylveon-GX HR (secret rare) 追加
    assert _pk("POKEMON JAPANESE SUN & MOON STRENGTH EXPANSION PACK NIGHT UNISON",
               "067", "GARDEVOIR SYLVEON GX") == "SM9a-067"


def test_miracle_twins_112_hyper_rare_added():
    # 2026-07-16: SM11 Miracle Twin #112 Dragonite-GX HR (secret rare) 追加
    assert _pk("POKEMON JAPANESE SUN & MOON MIRACLE TWINS", "112", "DRAGONITE GX") == "SM11-112"


def test_family_pokemon_card_game_maps_sh():
    # 2026-07-16: SwSh ファミリーポケモンカードゲーム #014 = 既存 SH-014 (ゲッコウガV)
    assert _pk("POKEMON JAPANESE SWORD & SHIELD FAMILY POKEMON CARD GAME",
               "014", "GRENINJA V") == "SH-014"


def test_black_deck_kit_added_bdk():
    # 2026-07-16: 2004 PCG ロケット団ハーフデッキ-black- (synthetic BDK) #005/#006 追加
    assert _pk("POKEMON JAPANESE BLACK DECK KIT", "005", "DARK MAGCARGO") == "BDK-005"
    assert _pk("POKEMON JAPANESE BLACK DECK KIT", "006", "DARK HOUNDOOM") == "BDK-006"


def test_clk_classic_blastoise_suicune_lapras_added():
    # 2026-07-18: ポケカ クラシック カメックス&スイクンexデッキ #008 Lapras (CLK-008) 追加。
    #   deck名 'BLASTOISE & SUICUNE' で限定 (他Classicデッキと非衝突)。
    assert _pk("POKEMON JAPANESE CLK-TRADING CARD GAME CLASSIC BLASTOISE & SUICUNE EX DECK",
               "008", "LAPRAS") == "CLK-008"


def test_classic_decks_have_no_printed_rarity():
    # 2026-07-20 訂正: ポケカ Classic (CLK/CLF) は printed rarity 記号を持たない(retailer【-】)。
    #   CLK-008 に一度入れた 'Rare Holo' は誤りだったので空へ訂正。CP4 と同型の扱い。
    for brand, num, subj in (
        ("POKEMON JAPANESE CLK-TRADING CARD GAME CLASSIC BLASTOISE & SUICUNE EX DECK", "008", "LAPRAS"),
        ("POKEMON JAPANESE CLF-TRADING CARD GAME CLASSIC VENUSAUR & LUGIA EX DECK", "002", "IVYSAUR"),
    ):
        r = P.lookup_pokemon(brand, num, subj, verbose=False)
        assert r is not None
        assert not r.get("rarity"), f"{r['card_id']} は Classic なので rarity 空が正"


def test_clf_venusaur_lugia_deck_added():
    # 2026-07-20: ポケカ クラシック フシギバナ&ルギアexデッキ (CLF, JP /032) #002/#015 追加
    assert _pk("POKEMON JAPANESE CLF-TRADING CARD GAME CLASSIC VENUSAUR & LUGIA EX DECK",
               "002", "IVYSAUR") == "CLF-002"
    assert _pk("POKEMON JAPANESE CLF-TRADING CARD GAME CLASSIC VENUSAUR & LUGIA EX DECK",
               "015", "CHANSEY") == "CLF-015"


def test_plasma_gale_maps_bw7b():
    # 2026-07-19: BLACK & WHITE PLASMA GALE #035 = 既存 BW7-B-035 (ギラティナ)
    assert _pk("POKEMON JAPANESE BLACK & WHITE PLASMA GALE", "035", "GIRATINA") == "BW7-B-035"


def test_cp4_075_m_lucario_ex_added():
    # 2026-07-20: CP4 Premium Champion Pack #075 メガルカリオEX 追加。
    #   CP4 は printed rarity 無し(全リバースミラーホロ)= C:Rarity 空が正 (HQ 2026-07-02 確定)。
    r = P.lookup_pokemon("POKEMON JAPANESE PREMIUM CHAMPION PACK", "075", "M LUCARIO EX", verbose=False)
    assert r is not None and r["card_id"] == "CP4-075"
    assert r.get("set_name_ebay") == "Premium Champion Pack"
    assert not r.get("rarity")  # CP4 は rarity 記号を持たない


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
