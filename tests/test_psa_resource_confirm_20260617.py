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
    assert "確定して探索開始" in h


def test_images_are_proxied_to_avoid_hotlink():
    # 画像srcは /img?u= プロキシ経由(referer由来ホットリンク制限を回避: 2026-06-17 onepiece等)
    prc = _load("psa_resource_confirm")
    import urllib.parse
    cands = [{"key": "OP01-016", "image": "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-016.png",
              "label": "ナミ"}]
    h = prc.build_confirm_html([_item(0, cands, resolved="OP01-016", psa="https://i.ebayimg/x.jpg")])
    assert "/img?u=" in h
    # 直URLが src に生で出ていない(プロキシ化されている)
    assert "src='https://" not in h
    assert "/img?u=" + urllib.parse.quote("https://i.ebayimg/x.jpg", safe="") in h
    assert prc._proxied("") == "" and prc._proxied(None) == ""


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


def test_fetch_image_encodes_spaces_in_url(monkeypatch):
    # catalog の "Other Product Card" 等 生スペースURLは urllib が弾く → エンコードして取得(2026-06-17)
    prc = _load("psa_resource_confirm")
    captured = {}

    class _R:
        def read(self):
            return b"IMG"
        headers = {"Content-Type": "image/png"}

    def fake_open(req, timeout=0):
        captured["url"] = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        return _R()

    monkeypatch.setattr(prc.urllib.request, "urlopen", fake_open)
    prc._IMG_CACHE.clear()
    d, ct = prc._fetch_image("https://files.bandai-tcg-plus.com/card_image/OP-EN/Other Product Card/x.png")
    assert d == b"IMG"
    assert " " not in captured["url"] and "%20" in captured["url"]   # スペースが%20に


def test_fix_url_corrects_dbs_dead_path():
    # catalog の dbs-cardgame.com 画像が /fw/jp/images/ で404 → /fw/images/ に補正(2026-06-17)
    prc = _load("psa_resource_confirm")
    bad = "https://www.dbs-cardgame.com/fw/jp/images/cards/card/jp/E01-12.webp"
    good = "https://www.dbs-cardgame.com/fw/images/cards/card/jp/E01-12.webp"
    assert prc._fix_url(bad) == good
    assert prc._fix_url("https://files.bandai-tcg-plus.com/x.png").endswith("x.png")  # 他は不変
    assert prc._fix_url("") == ""


def test_images_have_onerror_fallback():
    # 壊れ画像(404/DNS/ホットリンク何でも)は onerror で「画像なし」に差替え(2026-06-17)
    prc = _load("psa_resource_confirm")
    h = prc.build_confirm_html([_item(0, [{"key": "K", "image": "https://c/a.jpg", "label": "l"}])])
    assert "onerror='imgFail(this,0)'" in h          # 候補
    assert "onerror='imgFail(this,1)'" in h          # 現物
    assert "function imgFail" in h


def test_catalog_variants_excludes_dummy_rows():
    mp = _load("mercari_psa_resource")
    if not os.path.exists(r"C:/dev/iMak_data/catalog/products.sqlite"):
        return
    for cn in ("FS04-01", "SB02-053", "P-053"):
        v = mp.catalog_variants_for_cardno(cn)
        assert all("dummy" not in c["product_id"].lower() for c in v), f"{cn} に dummy 候補が残存"


def test_catalog_variants_return_variant_attrs_for_textual_id():
    # 画像が死んでても variant_type 等で変種を特定できるよう識別属性を返す(2026-06-17 E01-12)
    mp = _load("mercari_psa_resource")
    if not os.path.exists(r"C:/dev/iMak_data/catalog/products.sqlite"):
        return
    v = mp.catalog_variants_for_cardno("E01-12")
    p1 = next((c for c in v if c["product_id"].lower() == "e01-12_p1"), None)
    assert p1 is not None and p1.get("variant_type") == "alt_art"   # ①「ALTERNATE ART」と照合可
    # 全候補に識別属性キーが在る
    assert all("variant_type" in c and "rarity" in c and "get_info" in c for c in v)


def test_gate_label_includes_variant_attrs():
    src = (_TOOLS / "psa_resource_gate.py").read_text(encoding="utf-8")
    # ラベルに variant_type/rarity/set/get_info を出す(画像無しでも特定可能に)
    assert 'c.get("variant_type"' in src and 'c.get("rarity"' in src


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
