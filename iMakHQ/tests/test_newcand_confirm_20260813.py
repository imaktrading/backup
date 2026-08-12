# -*- coding: utf-8 -*-
"""捨てた仕入候補 → 新規出品の種 (newcand_confirm) の純関数テスト (2026-08-13)。

背景: 補URL確証で「違う(別商品)」「要調査」を押した候補は台帳に記録されるだけで、
その後どこにも使われていなかった (= 出品していないカードの供給を毎日捨てていた)。
ただし「違う」は *その出品のカードでない* としか言っておらず、**何のカードかは不明**。
そのまま出品に回すと誤出品になるので、**同定をゼロからやり直す** のがこのツール。

固定する挙動:
  1. 候補タイトルからカード番号を取れる (TCG形式 / ポケモンの印刷番号形式)
  2. 探索cache から候補タイトルを復元できる (押した時に保存していなかったため)
  3. 処理済 URL は二度出さない
  4. 版(product_id)が決まっていない pick は捨てる = 出品に回さない (fail-closed)
"""
from __future__ import annotations

import os
import sys

_TOOLS = r"C:\dev\iMak\iMakHQ\tools"
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import newcand_confirm as N  # noqa: E402


# ---------------------------------------------------------------------------
# 1. カード番号の抽出
# ---------------------------------------------------------------------------
def test_extract_card_no_tcg():
    t = "【PSA10】ベロ・ベティ(L★){赤/黄}〈OP05-002〉[ブースターパック 新時代の主役] 4361"
    assert N.extract_card_no(t) == "OP05-002"


def test_extract_card_no_lowercase_is_normalized():
    assert N.extract_card_no("psa10 ペローナ SR [op12-034]") == "OP12-034"


def test_extract_card_no_pokemon_print_number():
    assert N.extract_card_no("PSA10 わるいヘルガー 006/020 ポケモンカード") == "006/020"


def test_extract_card_no_absent():
    assert N.extract_card_no("PSA10 ポケモンカード まとめ売り") == ""
    assert N.extract_card_no("") == ""


# ---------------------------------------------------------------------------
# 2. 探索cache からの候補タイトル復元
# ---------------------------------------------------------------------------
def test_url_title_map_reads_all_buckets():
    cache = {
        "358000000001": {"mercari": {
            "best": [9500, "https://m/x1", "タイトル1"],
            "cands": [[8000, "https://m/x2", "タイトル2"]],
            "all_cands": [[7000, "https://m/x3", "タイトル3"]],
            "loose_cands": [[6000, "https://m/x4", "タイトル4"]],
        }},
        "358000000002": {"mercari": {}},
        "358000000003": {},
    }
    m = N.url_title_map(cache)
    assert m["https://m/x1"] == (9500, "タイトル1")
    assert m["https://m/x4"] == (6000, "タイトル4")
    assert len(m) == 4


def test_url_title_map_tolerates_garbage():
    assert N.url_title_map({}) == {}
    assert N.url_title_map({"a": {"mercari": {"cands": [None, [1], ["", "", ""]]}}}) == {}


# ---------------------------------------------------------------------------
# 3. 未処理だけ拾う
# ---------------------------------------------------------------------------
def test_pending_rows_skips_done_and_duplicates():
    src = [("補URL候補NG", ["358_1", "111", "https://m/a", "t"]),
           ("補URL候補NG", ["358_2", "222", "https://m/b", "t"]),
           ("補URL要調査", ["358_3", "333", "https://m/a", "t"]),   # 重複 url
           ("補URL候補NG", ["358_4", "444", "", "t"]),              # url 空
           ("補URL候補NG", ["358_5"])]                              # 列不足
    out = N.pending_rows(src, done_urls={"https://m/b"})
    assert [o["url"] for o in out] == ["https://m/a"]
    assert out[0]["src"] == "補URL候補NG" and out[0]["src_cert"] == "111"


# ---------------------------------------------------------------------------
# 4. 確定結果のパース (fail-closed)
# ---------------------------------------------------------------------------
def test_parse_result_drops_pick_without_product_id():
    """版が決まっていない = 何のカードか確定していない → 出品に回さない。"""
    res = N.parse_result({"picks": [{"idx": 0, "pid": "", "cert": "12345678"},
                                    {"idx": 1, "pid": "OP05-002_p1", "category": "one_piece_tcg",
                                     "cert": "PSA 147704361"}],
                          "rejects": [2], "holds": [3]})
    assert [p["idx"] for p in res["picks"]] == [1]
    assert res["picks"][0]["cert"] == "147704361", "cert は数字だけ取り出す"
    assert res["rejects"] == [2] and res["holds"] == [3]


def test_parse_result_empty():
    res = N.parse_result({})
    assert res == {"picks": [], "rejects": [], "holds": []}


# ---------------------------------------------------------------------------
# 5. HTML が3つの状態を出し分ける
# ---------------------------------------------------------------------------
def _item(idx, variants, title="PSA10 ナミ EB03-053", card_no="EB03-053"):
    return {"idx": idx, "url": f"https://m/{idx}", "src": "補URL候補NG", "src_itemid": "358_1",
            "src_cert": "111", "price": 9000, "title": title, "card_no": card_no,
            "variants": variants}


def test_build_html_marks_single_multi_and_missing():
    v1 = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami", "image": ""}]
    v2 = v1 + [{"pid": "EB03-053_p1", "category": "one_piece_tcg", "name": "Nami", "image": ""}]
    page = N.build_html([_item(0, v1), _item(1, v2), _item(2, [], title="", card_no="")]).decode()
    assert "カタログで確定: EB03-053" in page
    assert "版が 2 つあります" in page
    assert "カタログに該当なし" in page
    assert "タイトル不明" in page
    assert page.count("data-a='go'") == 3, "全件に『出品する』ボタンが出る"
