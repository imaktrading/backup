"""Regression: 2026-06-17 — PSA再仕入れ pre-search 目視確認ゲート v2(②候補ピッカー)。

探索前に確定: ① 現物(eBay出品画像=GetItem、cert→psa_cache フォールバック)と
② 候補(card番号の catalog 変種をラジオ表示)を並べ、同じ変種を選んで ON。
選んだKEYが探索対象＋商品管理シートAI列へ書戻し(目視の資産化)。不一致は原因タグ→PDCA。

build_confirm_html / psa_image_for_cert / catalog_variants_for_cardno を固定 + gate配線。
"""
import importlib.util
import os
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"


def _load(name):
    p = _TOOLS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name + "_t", p)
    import sys
    sys.path.insert(0, str(_TOOLS))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _item(idx, cands, resolved=None, psa="https://i.ebayimg/x.jpg", no_image=False):
    return {"idx": idx, "title": "PSA10 P-041 Luffy", "card_no": "P-041", "psa_image": psa,
            "candidates": cands, "resolved_key": resolved, "ebay_url": "https://e/1", "no_image": no_image}


def test_v2_candidate_radio_and_default_selection():
    prc = _load("psa_resource_confirm")
    cands = [{"key": "P-041", "image": "https://c/a.jpg", "label": "[P-041] ルフィ / Promo"},
             {"key": "P-041_D", "image": "https://c/b.jpg", "label": "[P-041_D] ルフィ / Promo"}]
    h = prc.build_confirm_html([_item(0, cands, resolved="P-041_D")])
    assert "① 現物(出品PSA)" in h and "② 候補(正しい変種を選択)" in h
    assert "name='pick0'" in h                       # 候補ラジオ
    assert "value='P-041_D' checked" in h            # 解決済KEYが既定選択
    assert "i.ebayimg/x.jpg" in h                    # ①現物=eBay画像
    assert "確定して探索開始" in h


def test_v2_no_candidates_defaults_off_and_placeholder():
    prc = _load("psa_resource_confirm")
    h = prc.build_confirm_html([_item(0, [], no_image=True)])
    assert "catalog候補なし" in h                     # 候補なしプレースホルダ
    assert "card noimg off" in h or "off'" in h       # 既定OFF
    # 既定OFF = checkbox に checked が付かない
    assert "type='checkbox'  onchange" in h or "type='checkbox' onchange" in h


def test_v2_single_candidate_autoselected():
    prc = _load("psa_resource_confirm")
    h = prc.build_confirm_html([_item(0, [{"key": "OP11-106", "image": "https://c/o.jpg",
                                           "label": "[OP11-106] ゼウス"}], resolved=None)])
    assert "value='OP11-106' checked" in h           # 候補1つなら自動選択


def test_v2_go_returns_selected_key_and_reason():
    prc = _load("psa_resource_confirm")
    h = prc.build_confirm_html([_item(0, [{"key": "P-041", "image": "i", "label": "l"}])])
    assert "input[type=radio]:checked" in h          # 選択KEYを拾う
    assert "conf.push({idx:i, key:pick.value})" in h
    assert "rejected:rej" in h
    assert "setAll(true)" in h and "onclick='all(" not in h   # document.all 衝突回避


def test_v2_handles_list_label_and_none():
    prc = _load("psa_resource_confirm")
    h = prc.build_confirm_html([_item(0, [{"key": "K", "image": "", "label": ["a", "b"]}])])  # 落ちない
    assert "a / b" in h


def test_psa_image_for_cert_uses_cardimageurl():
    prc = _load("psa_resource_confirm")
    prc._PSA_CACHE = {"142490884": {"CardImageUrl": "https://cdn/cert/x/small/y.jpg"}}
    assert prc.psa_image_for_cert("142490884").startswith("https://cdn/")
    assert prc.psa_image_for_cert("000") == "" and prc.psa_image_for_cert("") == ""


def test_catalog_variants_for_cardno_exact_first():
    mp = _load("mercari_psa_resource")
    if not os.path.exists(r"C:/dev/iMak_data/catalog/products.sqlite"):
        return  # DB無環境では skip
    v = mp.catalog_variants_for_cardno("P-041")
    assert len(v) >= 1
    assert v[0]["product_id"] == "P-041"             # 完全一致が先頭
    assert all(c["product_id"] == "P-041" or c["product_id"].startswith("P-041_") for c in v)
    assert mp.catalog_variants_for_cardno("") == []


def test_catalog_variants_nocase_matches_lowercase_product_id():
    mp = _load("mercari_psa_resource")
    if not os.path.exists(r"C:/dev/iMak_data/catalog/products.sqlite"):
        return
    # KEYは大文字化されるが catalog product_id は 'S8a-004' 等 小文字混じり → NOCASE で拾う
    v = mp.catalog_variants_for_cardno("S8A-004")
    assert any(c["product_id"].lower() == "s8a-004" for c in v), "NOCASEでヒットしていない"


def test_card_number_regex_covers_dbs_gundam():
    g = _load("psa_resource_gate")
    assert g._resource_card_number("PSA 10 Frieza SB02-053 Alt Art", None) == "SB02-053"
    assert g._resource_card_number("Gundam CCG #GD02-069 Zeta", None) == "GD02-069"
    assert g._resource_card_number("One Piece OP11-106 Zeus", None) == "OP11-106"


def test_gate_includes_resolved_key_as_candidate():
    src = (_TOOLS / "psa_resource_gate.py").read_text(encoding="utf-8")
    # 解決済KEYは card番号ヒット漏れでも②候補に必ず入れる(KEY自身のcatalog画像)
    assert "解決済KEY自身は必ず候補に含める" in src
    assert "card_meta_for_key(rk)" in src


def test_build_cert_map_reads_column_I():
    sio = _load("sheet_io")
    rows = [["url", "itemID"] + ["x"] * 6 + ["cert"],
            ["u1", "111"] + [""] * 6 + ["142490884"],
            ["u2", "222"] + [""] * 6 + [""],
            ["u3", ""] + [""] * 6 + ["999"]]
    assert sio.build_cert_map(rows) == {"111": "142490884"}


def test_gate_v2_wiring():
    src = (_TOOLS / "psa_resource_gate.py").read_text(encoding="utf-8")
    i_confirm = src.index("confirm_targets")
    i_mercari = src.index("メルカリ最安取得中")
    assert i_confirm < i_mercari, "確認ゲートが探索より後(無意味)"
    assert "ebay_listing_image" in src               # ①現物=eBay画像
    assert "catalog_variants_for_cardno" in src       # ②候補
    assert "write_keys" in src                        # 選択KEYをスプシ書戻し
    assert "_run_mismatch_pdca" in src and "PSA不一致台帳" in src   # 不一致PDCA
    assert "OUT_DIR = mp.DESK" in src
    assert "--no-confirm" in src
