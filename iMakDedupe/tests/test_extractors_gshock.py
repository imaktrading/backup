"""G-shock extractor unit tests (offline)."""

import pytest

from dedupe.extractors.gshock import extract_gshock_model

pytestmark = pytest.mark.offline


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Casio G-Shock DW-5600-1JF Wristwatch", "DW-5600-1JF"),
        ("GA-2100-1A カシオーク", "GA-2100-1A"),
        ("GW-B5600BC-1JF 電波ソーラー", "GW-B5600BC-1JF"),
        ("MTG-B3000B-1A MT-G Bluetooth", "MTG-B3000B-1A"),
        ("GST-B400-1AJF G-STEEL", "GST-B400-1AJF"),
        ("gma-s2100-4a 小文字 mix", "GMA-S2100-4A"),
    ],
)
def test_hit(title, expected):
    assert extract_gshock_model(title) == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        # 2026-05-29 拡張 prefix 群 (= catalog 内訳から取扱判定)
        ("Casio G-Shock GM-110-1A", "GM-110-1A"),
        ("GWG-100-1AJF MUDMASTER", "GWG-100-1AJF"),
        ("GAW-100-1A 電波ソーラー", "GAW-100-1A"),
        ("GWN-1000-2A GULFMASTER", "GWN-1000-2A"),
        ("GBD-200-1A1 G-SQUAD", "GBD-200-1A1"),
        ("GBX-100-1JF G-LIDE", "GBX-100-1JF"),
        ("GD-010-1JF 旧型番", "GD-010-1JF"),
        ("GLX-5600-1JF G-LIDE", "GLX-5600-1JF"),
        ("AWG-M100-1AJF 旧電波ソーラー", "AWG-M100-1AJF"),
        ("GG-1000-1A MUDMASTER", "GG-1000-1A"),
        ("AW-500BB-1E 復刻", "AW-500BB-1E"),
        ("GWX-5600-1JF G-LIDE", "GWX-5600-1JF"),
        ("DWE-5600JB-1A9 DIGITAL EDIT", "DWE-5600JB-1A9"),
        ("GX-56BBR-1JF 56 派生", "GX-56BBR-1JF"),
        ("MRG-B2000BG-3AJR MR-G", "MRG-B2000BG-3AJR"),
        ("GAE-2100GC-7AJR GA-2100 限定派生", "GAE-2100GC-7AJR"),
        ("GMD-B300-2JF MID-SIZE", "GMD-B300-2JF"),
        ("GBM-2100-1AJF G-SQUAD", "GBM-2100-1AJF"),
        ("GR-B300-1AJF", "GR-B300-1AJF"),
        ("GXW-56-1AJF", "GXW-56-1AJF"),
        # G 単独 (= 最古型番 Born In Gold 系)
        ("G-5600BG-5JR Born In Gold", "G-5600BG-5JR"),
    ],
)
def test_hit_extended_prefixes(title, expected):
    """2026-05-29 拡張 prefix 群 hit verify."""
    assert extract_gshock_model(title) == expected


@pytest.mark.parametrize(
    "title,expected",
    [
        # 長 prefix と短 prefix の衝突回避 (= alternation 最左最長一致)
        ("GMW-B5000D-1JF METAL", "GMW-B5000D-1JF"),  # GM ではなく GMW
        ("GWG-100-1AJF MUDMASTER", "GWG-100-1AJF"),  # GW ではなく GWG
        ("GAE-2100GC-7AJR", "GAE-2100GC-7AJR"),  # GA ではなく GAE
        ("GMA-S2100-4A", "GMA-S2100-4A"),  # GM ではなく GMA
        ("GXW-56-1AJF", "GXW-56-1AJF"),  # GX ではなく GXW
        ("MRG-B2000BG-3AJR", "MRG-B2000BG-3AJR"),  # MTG ではなく MRG
    ],
)
def test_prefix_collision_avoidance(title, expected):
    """alternation 順序 (= 長 prefix 優先) 検証."""
    assert extract_gshock_model(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        "",
        "Casio G-Shock デジタル腕時計",  # 数字なし → "G-SHOCK" 除外 logic 担保
    ],
)
def test_fail_closed(title):
    """型番形式 hit せず → None (= 推測 NG)."""
    assert extract_gshock_model(title) is None


@pytest.mark.parametrize(
    "title,expected",
    [
        # 2026-06-12 仕様変更: prefix 固定 whitelist 廃止 (= 出品くん regex 整合).
        # 取扱外 prefix も extract レベルでは hit、 catalog 解決層で「取扱外なら None」 で fail-closed.
        ("BABY-G BGD-565-1JF (= baby-g prefix 取扱外)", "BGD-565-1JF"),
        ("PRO TREK PRG-330-1JR (= ProTrek 取扱外)", "PRG-330-1JR"),
        ("BA-110AH-4A Baby-G", "BA-110AH-4A"),
        ("BGD-100-1B Baby-G", "BGD-100-1B"),
        ("W-218H-1BJF CASIO スタンダード", "W-218H-1BJF"),
    ],
)
def test_excluded_categories_extract_but_catalog_resolves_fail_closed(title, expected):
    """取扱外 prefix (= Baby-G / ProTrek / CASIO 標準) も extract では hit する.

    2026-06-12 仕様変更: 旧 prefix 固定 whitelist 廃止 (= GMC 等の取りこぼし発覚で撤回).
    出品くん regex と整合のため取扱外も形式的に hit させ、 catalog lookup_gshock 側で
    「取扱外 = None 返却」 で fail-closed する設計 (= 解決層に責務集約).
    """
    assert extract_gshock_model(title) == expected


@pytest.mark.parametrize(
    "title",
    [
        # 依頼書 §3 「TCG 誤検出ゼロ」 担保: 遊戯王 EN/JP 系は extract で除外
        "Yu-Gi-Oh LIOV-EN042 Pot of Prosperity",  # YGO EN 系
        "遊戯王 RA01-JP001",  # YGO JP 系
        "ETCO-JP021 蘇宝の使徒",  # YGO JP 系
        # 一般 TCG (= prefix に数字含むため形式的に hit しない)
        "ONE PIECE OP10-049 Sabo",  # prefix "OP10" = 数字含む → [A-Z]{1,4} alpha-only に不一致
        "Pokemon SV1V-086 Drowzee",  # prefix "SV1V" = 数字含む → 同上
    ],
)
def test_tcg_card_id_excluded(title):
    """TCG card_id 形式 (= 特に遊戯王 EN/JP 系) は extract_gshock_model で None.

    一般 TCG (= OP10-049 / SV1V-086) は prefix `[A-Z]{1,4}` (= alphabet only)
    制約で hit しない (= prefix に数字含むため不一致)。 遊戯王 (= LIOV-EN042) のみ
    prefix alpha のみ + 後段 EN/JP 始まりで形式的に hit するため明示除外.

    注意: 古い遊戯王 (= LOB-001 等の純数字 suffix) や DBSCG (FS04-03 等) は EN/JP 形式
    でないため extract で hit する (= 仕様)。 これは catalog lookup_gshock 側の
    fail-closed (= 取扱外なら None) で解決層に責務集約。
    """
    assert extract_gshock_model(title) is None


@pytest.mark.parametrize(
    "title,expected",
    [
        # 依頼書 §「prefix `[A-Z]{1,4}` = DW/GW/GA/GMC/GM/GR/MR/GBD/ECB/EQB/AW/AE… 何でもカバー」
        ("CASIO G-Shock GMC-B2100Y-1A Mens Watch", "GMC-B2100Y-1A"),  # 6/12 取りこぼし真因
        ("CASIO G-Shock GMC-B2100Y-1AJF Mens Watch JF 国内", "GMC-B2100Y-1AJF"),
        ("CASIO ECB-2200D-1AJF Edifice", "ECB-2200D-1AJF"),  # Edifice 系
        ("CASIO EQB-2200BD-1AJF Solar", "EQB-2200BD-1AJF"),
    ],
)
def test_listing_regex_coverage_gmc_etc(title, expected):
    """6/12 依頼書 §完了基準 #2 「出品くんが catalog hit する型番は dedupe も必ず抽出+解決できる」 verify."""
    assert extract_gshock_model(title) == expected
