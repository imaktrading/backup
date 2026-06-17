"""Regression: 2026-06-17 — PSA再仕入れ pre-search 目視確認ゲート。

探索の前に「正しいカードか」を目視確定 → 確定分だけ探索する。各カードは
① 現物(出品に使ったPSA画像: cert#→psa_cache.json) と ② 解決先(catalog 正カード) を
並べ、同じカード・同じ変種かを目視する。番号一致では弾けない変種取り違え(CHR/VMAX・
JP/Asia)や KEY未解決を、探索に時間を使う前に人手で確定する(verify→build と同じ思想)。

併せて: psa_resource_gate が確認ゲートを「探索の前」に配線し、OUT_DIR 未定義の NameError
(post-search HTML が一度も出てなかった bug)が解消されていることを source 固定。
"""
import importlib.util
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"


def _load(name):
    p = _TOOLS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name + "_t", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_build_confirm_html_shows_two_images_and_flags_missing_genbutsu():
    prc = _load("psa_resource_confirm")
    items = [
        {"idx": 0, "title": "PSA10 OP11-106 Luffy", "card_no": "OP11-106",
         "psa_image": "https://p/a.jpg", "ref_image": "https://c/b.jpg",
         "ref_label": "OP11 SR", "ebay_url": "https://e/1", "no_image": False},
        {"idx": 1, "title": "PSA10 Charizard", "card_no": "SV-P-291",
         "psa_image": "", "ref_image": "https://c/x.jpg",
         "ref_label": "", "ebay_url": "https://e/2", "no_image": True},
    ]
    h = prc.build_confirm_html(items)
    assert "type='checkbox' checked" in h            # 既定ON
    assert "確定して探索開始" in h                    # 確定ボタン
    assert "現物(出品PSA)" in h and "解決先(catalog)" in h  # 2画像の見出し
    assert "p/a.jpg" in h and "c/b.jpg" in h          # ①現物 + ②catalog 両方描画
    assert "OP11-106" in h and "data-idx='1'" in h    # 各カード
    assert "card noimg" in h and "現物PSA画像なし" in h  # 現物なしは赤枠フラグ
    assert "/confirm" in h                            # POST先


def test_build_cert_map_reads_column_I():
    sio = _load("sheet_io")
    # B列(1)=itemID, I列(8)=cert#
    rows = [["url", "itemID"] + ["x"] * 6 + ["cert"],
            ["u1", "111"] + [""] * 6 + ["142490884"],
            ["u2", "222"] + [""] * 6 + [""],        # cert空 → 除外
            ["u3", ""] + [""] * 6 + ["999"]]         # itemID空 → 除外
    cm = sio.build_cert_map(rows)
    assert cm == {"111": "142490884"}


def test_psa_image_for_cert_uses_cardimageurl():
    prc = _load("psa_resource_confirm")
    prc._PSA_CACHE = {"142490884": {"CardImageUrl": "https://cdn/cert/x/small/y.jpg"}}
    assert prc.psa_image_for_cert("142490884").startswith("https://cdn/")
    assert prc.psa_image_for_cert("000") == ""   # 未登録cert
    assert prc.psa_image_for_cert("") == ""       # cert無し


def test_gate_confirms_before_search_with_genbutsu_and_defines_out_dir():
    src = (_TOOLS / "psa_resource_gate.py").read_text(encoding="utf-8")
    i_confirm = src.index("confirm_targets")
    i_mercari = src.index("メルカリ最安取得中")
    assert i_confirm < i_mercari, "確認ゲートが探索より後にある(無意味)"
    assert "psa_image_for_cert" in src, "現物PSA画像(cert→psa_cache)が確認ゲートに渡っていない"
    assert "cert_map" in src
    assert "OUT_DIR = mp.DESK" in src             # post-search HTML の NameError 回帰防止
    assert "--no-confirm" in src
