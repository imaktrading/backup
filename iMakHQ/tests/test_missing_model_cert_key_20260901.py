# -*- coding: utf-8 -*-
"""missing_models.csv の model 書式に cert を埋め込み、cert 有り/無しの2書式に割れない
ようにする (2026-09-01)。

何が起きていたか: `psa_to_csv.py` の catalog_misses は `f"{brand}-{card_number}"` (cert 無し)
で missing_models.csv に書いていた。一方 `post_psa_review._route_none_to_catalog` は
`cert{N} {brand} [{subject}] #{cardno} (...)` (cert 有り) で書く。同じカードでも書き手が
違うと `pdca_store.normalize_item_key` の cert 抽出が片方でしか効かず、dkey が割れて
2行に分かれた (queue 590=cert84299672 done / queue 622=ブランド文字列 pending の実例)。
片方を close してももう片方が翌日また Catalog に届く。

直し方: `psa_to_csv.missing_model_text` で post_psa_review と同じ書式に統一する。
これで `normalize_item_key` の cert 抽出と `parse_missing_model_identity` の identity 抽出が
両方の書き手で効くようになり、同じカードは常に同じ dkey に畳まれる。

出典: hq/requests/2026-09-01_act_code_proposals_tcg_response.md 提案2
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "tools")))
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "..", "iMakTCG")))

import pdca_store as ps         # noqa: E402
from psa_to_csv import missing_model_text  # noqa: E402


def test_missing_model_text_embeds_cert_in_post_psa_review_format():
    model = missing_model_text("84299672", "ONE PIECE JAPANESE FILM RED", "New Genesis", "004")
    assert model.startswith("cert84299672 ONE PIECE JAPANESE FILM RED [New Genesis] #004")


def test_normalize_item_key_folds_psa_to_csv_and_resolver_drop_to_same_cert():
    """psa_to_csv 由来 (missing_model_text) と `_queue_resolver_drop` 由来 (f"cert{N}") が
    同じ cert キーに畳まれる (= 実例 queue 590/622 の再発防止)。"""
    from_psa_to_csv = missing_model_text("84299672", "ONE PIECE JAPANESE FILM RED",
                                         "New Genesis", "004")
    from_resolver_drop = "cert84299672"
    assert ps.normalize_item_key(from_psa_to_csv) == ps.normalize_item_key(from_resolver_drop)
    assert ps.normalize_item_key(from_psa_to_csv) == "cert84299672"


def test_dedup_key_is_identical_across_both_writers():
    a = ps.dedup_key("one_piece_tcg",
                     missing_model_text("84299672", "ONE PIECE JAPANESE FILM RED",
                                        "New Genesis", "004"),
                     "catalog_add", "")
    b = ps.dedup_key("one_piece_tcg", "cert84299672", "catalog_add", "")
    assert a == b


def test_parse_missing_model_identity_now_extracts_identity():
    """従来書式 (`f"{brand}-{card_number}"`) は identity 抽出が空だった。新書式は非空になる。"""
    model = missing_model_text("84299672", "ONE PIECE JAPANESE FILM RED", "New Genesis", "004")
    ident = ps.parse_missing_model_identity(model)
    assert ident, "cert埋め込み後も identity が空のまま (parse_missing_model_identity が変わった?)"
    assert "New Genesis" in ident
    assert "004" in ident


def test_partition_by_identity_sends_it_now_that_identity_is_filled():
    """従来は identity 空 + item_id が opaque でない(brand文字列)ため送られていたが、
    identity は空のまま `(不明=要調査)` 扱いだった。新書式では identity が実値で埋まる。"""
    model = missing_model_text("84299672", "ONE PIECE JAPANESE FILM RED", "New Genesis", "004")
    ident = ps.parse_missing_model_identity(model)
    row = {"item_id": model, "identity": ident}
    sendable, held = ps.partition_by_identity([row])
    assert sendable == [row]
    assert held == []
    assert row["identity"] != ""


def test_old_bare_format_still_normalizes_unchanged_but_has_no_identity():
    """回帰確認: 旧書式 (`brand-cardnumber`, cert 無し) は今までどおり cert を抽出できない
    (= 新書式へ切替える理由そのもの)。"""
    old = "ONE PIECE JAPANESE FILM RED: ENCORE PACK-004"
    assert ps.normalize_item_key(old) == old
    assert ps.parse_missing_model_identity(old) == ""


def test_all_five_franchise_branches_use_the_unified_helper():
    """5franchise (one_piece/pokemon/dragonball/gundam/yugioh) の catalog_misses.append が
    全部 `missing_model_text` 経由になっている (どれか1つだけ旧書式に戻す回帰を防ぐ)。"""
    src_path = os.path.normpath(os.path.join(_HERE, "..", "..", "iMakTCG", "psa_to_csv.py"))
    src = open(src_path, encoding="utf-8").read()
    assert src.count("missing_model_text(cert_number, brand, subject, card_number)") == 6, (
        "5箇所の catalog_misses.append + 1箇所の def。件数が減っていたら旧書式に戻った箇所がある")
