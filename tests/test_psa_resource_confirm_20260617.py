"""Regression: 2026-06-17 — PSA再仕入れ pre-search 目視確認ゲート。

探索の前に「正しいカードか」を catalog 正カード画像で確定 → 確定分だけ探索する。
番号一致では弾けない変種取り違え(CHR/VMAX・JP/Asia)や KEY未解決(正画像なし)を、
探索に時間を使う前に人手で確定する(post_psa_review の verify→build と同じ思想)。

併せて: psa_resource_gate が確認ゲートを「探索の前」に配線していること、OUT_DIR 未定義の
NameError(post-search HTML が一度も出てなかった bug)が解消されていることを source 固定。
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


def test_build_confirm_html_renders_checkbox_and_flags_noimage():
    prc = _load("psa_resource_confirm")
    items = [
        {"idx": 0, "title": "PSA10 OP11-106 Luffy", "card_no": "OP11-106",
         "ref_image": "https://x/a.jpg", "ref_label": "OP11 SR", "ebay_url": "https://e/1", "no_image": False},
        {"idx": 1, "title": "PSA10 Charizard", "card_no": "SV-P-291",
         "ref_image": "", "ref_label": "", "ebay_url": "https://e/2", "no_image": True},
    ]
    h = prc.build_confirm_html(items)
    assert "type='checkbox' checked" in h          # 既定ON
    assert "確定して探索開始" in h                  # 確定ボタン
    assert "OP11-106" in h and "data-idx='1'" in h  # 各カード描画
    assert "card noimg" in h and "正画像なし" in h   # 正画像なしは赤枠フラグ
    assert "/confirm" in h                          # POST先


def test_gate_confirms_before_search_and_defines_out_dir():
    src = (_TOOLS / "psa_resource_gate.py").read_text(encoding="utf-8")
    # 確認ゲートは「探索の前」= メルカリ探索より前に配線
    i_confirm = src.index("confirm_targets")
    i_mercari = src.index("メルカリ最安取得中")
    assert i_confirm < i_mercari, "確認ゲートが探索より後にある(無意味)"
    # OUT_DIR が定義済(未定義 NameError で post-search HTML が出てなかった bug の回帰防止)
    assert "OUT_DIR = mp.DESK" in src
    # --no-confirm で skip 可能(非対話/test)
    assert "--no-confirm" in src
