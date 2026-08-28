# -*- coding: utf-8 -*-
"""多変種プロモの変種取り違え(「違う」連打)を fail-closed で防ぐ回帰テスト (2026-07-24)。

ユーザー指摘: P-066(Boa Hancock,3変種)/P-041(Luffy,8変種)等の多変種プロモで、市場に別変種が
1件だけある/kw確証できない時、番号一致だけで別変種を掴んでいた(視覚確証で「違う」を連打)。
対策: 多変種カードは「番号一致だけの単一候補」を採用しない(変種hint確証必須)。
- SNKRDUNK _match_item: multi_variant+単一一致でhint未確証 → None。
- Mercari: 多変種×kw未確証 → 画像検索(番号のみ検証)を使わず候補出さない。
"""
import importlib.util
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"


def _load(name):
    spec = importlib.util.spec_from_file_location(name + "_t", _TOOLS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _data(*names):
    return {"tradingCards": [{"id": i, "name": n, "productNumber": ""} for i, n in enumerate(names)]}


def test_snkrdunk_single_match_multivariant_needs_hint():
    """★本命: 多変種で市場に1件(別変種)だけ→hint未確証なら None(誤variant掴まない)。"""
    sp = _load("snkrdunk_psa_resource")
    # 市場の1件は「最強ジャンプ付録」版、hint は「プロモパックEX Vol.2」→ 未確証
    data = _data("[P-066] ボア・ハンコック 最強ジャンプ付録 PSA10")
    hint = ["", "プロモーションパックEX Vol.2", "Promotion Pack EX Vol.2", "promo", "", "ボア・ハンコック"]
    got = sp._match_item(data, "P-066", variant_hint=hint, multi_variant=True)
    assert got is None, "多変種で変種未確証の単一候補を掴んではいけない"


def test_snkrdunk_single_match_singlevariant_now_needs_hint_too():
    """★2026-08-28 改訂: 単一変種カードでも **番号一致だけでは採らない**。

    旧挙動は「catalog に1変種しか無い番号なら hint 不問で確定」。だが catalog の変種数は
    市場に何が並ぶかを保証しない (SNKRDUNK 実測 2026-08-28: OP08-106 に9件、SB02-053 に5件)。
    set を確証できた時だけ採る = 別セットの同番号を掴まない。
    依頼書: hq/requests/2026-08-28_restock_search_returned_wrong_cards.md
    """
    sp = _load("snkrdunk_psa_resource")
    hint = ["BOOSTER -A FIST OF DIVINE SPEED- [OP-13]", "", "A Fist of Divine Speed",
            "", "R", "サボ"]
    assert sp._match_item(_data("[OP13-004] サボ PSA10"), "OP13-004",
                          variant_hint=None, multi_variant=False) is None
    assert sp._match_item(_data("[OP13-004] サボ PSA10"), "OP13-004",
                          variant_hint=hint, multi_variant=False) is None
    ok = sp._match_item(_data('[OP13-004] サボ (Booster Pack "A Fist of Divine Speed") PSA10'),
                        "OP13-004", variant_hint=hint, multi_variant=False)
    assert ok is not None and ok["name"].startswith("[OP13-004]")


def test_snkrdunk_single_match_multivariant_hint_confirmed():
    """多変種でも hint(入手元set)が候補名に在れば確証OK=採用。"""
    sp = _load("snkrdunk_psa_resource")
    data = _data("[P-066] ボア・ハンコック プロモーションパックEX Vol.2 PSA10")
    hint = ["", "プロモーションパックEX Vol.2", "", "promo", "", "ボア・ハンコック"]
    got = sp._match_item(data, "P-066", variant_hint=hint, multi_variant=True)
    assert got is not None, "hint確証できる正変種は採用する"


def test_mercari_multivariant_flag_in_card_query():
    """build_card_query が多変種フラグを持つ(画像検索fail-closedの根拠)。"""
    mp = _load("mercari_psa_resource")
    # 実catalog依存: P-066は多変種、OP13-004は単一
    assert mp._is_multi_variant("P-066") is True
    assert mp._is_multi_variant("OP13-004") is False
