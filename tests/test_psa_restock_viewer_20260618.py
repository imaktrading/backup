"""Regression: 2026-06-18 — POC-A: RESTOCK視覚確証ビューア + V8自動利益判定。

RESTOCK(不可逆=出品復活→売れたら仕入)の前に「① 現物(出品) vs 仕入候補(実際に買う物の画像)」を
視覚一致確認。確定分を「RESTOCK確定」タブへ(eBay書込なし=手動GO)。利益はV8(新規と同じ
pricing_engine)で自動判定。画像はプロキシ(候補の出品URL→mercari CDN/snkrdunk og:image に解決)。
"""
import importlib.util
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"
import sys
sys.path.insert(0, str(_TOOLS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name + "_t", _TOOLS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_build_restock_html_shows_genbutsu_candidates_v8():
    prc = _load("psa_resource_confirm")
    h = prc.build_restock_html([{
        "idx": 0, "title": "PSA10 OP01-016 Nami", "card_no": "OP01-016", "ebay_url": "https://e/1",
        "ref_image": "https://i.ebayimg/x.jpg",
        "candidates": [{"channel": "mercari", "url": "https://jp.mercari.com/item/m123456789", "price": 29400},
                       {"channel": "snkrdunk", "url": "https://snkrdunk.com/trading-cards/9", "price": 31000}],
        "v8": "利益OK V8推奨$45 (現$50)"}])
    assert "RESTOCK確定" in h and "① 現物(出品)" in h and "仕入候補" in h
    assert "/img?u=" in h                      # 画像はプロキシ経由
    assert "src='https://" not in h            # 直URLは src に出さない
    assert "¥29,400" in h
    # 候補ごとに個別チェック(1つ違っても全部NGにならない)= ck が候補数ぶん
    assert h.count("class='ck'") == 2 and "upd(0)" in h
    assert "conf.push({idx:idx, urls:urls})" in h
    assert "imgFail" in h and "data-idx='0'" in h


def test_restock_confirm_and_serve_exist():
    prc = _load("psa_resource_confirm")
    assert hasattr(prc, "restock_confirm") and hasattr(prc, "_serve_confirm")
    # confirm_targets も _serve_confirm 経由に集約されている
    src = (_TOOLS / "psa_resource_confirm.py").read_text(encoding="utf-8")
    assert "_serve_confirm(build_confirm_html" in src
    assert "_serve_confirm(build_restock_html" in src


def test_resolve_image_url_mercari_and_proxy():
    prc = _load("psa_resource_confirm")
    # mercari 出品URL → 静的CDN画像(ネット不要)
    assert prc._resolve_image_url("https://jp.mercari.com/item/m987654321").endswith("m987654321_1.jpg")
    # catalog/eBay画像はそのまま
    assert prc._resolve_image_url("https://files.bandai-tcg-plus.com/x.png").endswith("x.png")


def test_v8_label_costplus_not_loss():
    # コストプラス運用: 出品価格=V8推奨にすれば赤字にならない。判定は「市場で売れるか」(2026-06-18)
    g = _load("psa_resource_gate")
    mp = _load("mercari_psa_resource")
    high = g._v8_label(30000, 80.0, mp)   # 仕入高 → 利益価格が市場超 → 売れにくい
    assert "赤字" not in high              # 「赤字」とは言わない(コストプラス)
    assert "市場で売れにくい" in high and "市場" in high
    low = g._v8_label(3000, 154.0, mp)    # 仕入安 → 市場内
    assert "市場内" in low
    assert g._v8_label(None, 80.0, mp) == "" and g._v8_label(30000, None, mp) == ""


def test_gate_wires_restock_poc_a():
    src = (_TOOLS / "psa_resource_gate.py").read_text(encoding="utf-8")
    assert "restock_cands" in src and "_run_restock_confirm" in src
    assert 'write_rows_to_tab("RESTOCK確定"' in src   # 確定リスト出力
    assert "restock_confirm" in src
    # eBay revise(書込)はPOC-Aでは無い(手動GO)
    assert "ReviseFixedPriceItem" not in src
