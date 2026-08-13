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
    v1 = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami",
           "image": "https://x/a.png"}]
    v2 = v1 + [{"pid": "EB03-053_p1", "category": "one_piece_tcg", "name": "Nami",
                "image": "https://x/b.png"}]
    page = N.build_html([_item(0, v1), _item(1, v2), _item(2, [], title="", card_no="")]).decode()
    assert "カタログ候補 1件" in page
    assert "カタログ候補 2件" in page
    assert "カタログ候補なし" in page
    assert "タイトル不明" in page
    assert page.count("data-a='go'") == 3, "全件に『出品する』ボタンが出る"


def test_build_html_always_renders_catalog_images_and_zoom():
    """★1件しか候補が無い時も**画像で**出す (文字だけだと見比べられない)。虫眼鏡も出す。"""
    v1 = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami",
           "image": "https://files.example/EB03-053.png"}]
    page = N.build_html([_item(0, v1)]).decode()
    assert "EB03-053.png" in page, "カタログ画像が埋まっていない"
    assert page.count("class='v'") == 1
    assert "id='zov'" in page, "拡大オーバーレイが無い"
    assert "🔍" in page, "虫眼鏡ボタンが無い"


def test_catalog_candidates_does_not_pad_when_number_matched(monkeypatch):
    """番号が一致した時に同名カードで水増ししない (関係ない候補が混ざると選べない)。"""
    monkeypatch.setattr(N, "catalog_variants",
                        lambda no, db=None: [{"pid": "EB03-053", "category": "one_piece_tcg",
                                              "name": "Nami", "image": ""}])
    monkeypatch.setattr(N, "catalog_by_name",
                        lambda t, limit=12, db=None: [{"pid": "OP01-016"}] * 12)
    out = N.catalog_candidates("PSA10 ナミ EB03-053", "EB03-053")
    assert [c["pid"] for c in out] == ["EB03-053"]


def test_variant_prefix_excludes_other_numbers():
    """★前方一致で拾った別番号 (OP05-0021) を版として混ぜない。"""
    assert N._is_other_card("OP05-002", "OP05-002") is False
    assert N._is_other_card("OP05-002_p1", "OP05-002") is False
    assert N._is_other_card("OP05-002_EB02_LF", "OP05-002") is False
    assert N._is_other_card("OP05-0021", "OP05-002") is True


def test_catalog_variants_finds_suffixed_versions():
    """★2026-08-13 実バグ: LIKE の `\\_` が SQLite で効かず、版が1件も引けていなかった。

    実DBで確認する (版が複数あるカードの代表)。
    """
    import os
    if not os.path.exists(N.DB_PATH):
        import pytest
        pytest.skip("catalog DB が無い環境")
    pids = [c["pid"] for c in N.catalog_variants("OP05-002")]
    assert "OP05-002" in pids
    assert any(p.startswith("OP05-002_") for p in pids), f"版が引けていない: {pids}"
    assert len(pids) >= 2


def test_catalog_candidates_falls_back_to_name(monkeypatch):
    """番号が読めない/未収録なら名前で候補を出す (= 候補ゼロにしない)。"""
    monkeypatch.setattr(N, "catalog_variants", lambda no, db=None: [])
    monkeypatch.setattr(N, "catalog_by_name",
                        lambda t, limit=12, db=None: [{"pid": "A"}, {"pid": "B"}])
    assert [c["pid"] for c in N.catalog_candidates("PSA10 ナミ", "")] == ["A", "B"]


# ---------------------------------------------------------------------------
# 6. 台帳に候補タイトルを保存する (2026-08-13 追加分)
# ---------------------------------------------------------------------------
def test_pending_rows_reads_saved_candidate_title():
    """新形式 (候補タイトル/価格つき) の行はそこから読む。旧形式は空のまま。"""
    src = [("補URL候補NG", ["358_1", "111", "https://m/a", "出品側t", "2026-08-13",
                            "PSA10 ナミ EB03-053", 9000]),
           ("補URL候補NG", ["358_2", "222", "https://m/b", "出品側t", "2026-07-30"]),
           ("補URL要調査", ["358_3", "333", "https://m/c", "出品側t", "006/020", "AR",
                            "2026-08-13", "PSA10 わるいヘルガー", 4200])]
    out = {o["url"]: o for o in N.pending_rows(src, done_urls=set())}
    assert out["https://m/a"]["saved_title"] == "PSA10 ナミ EB03-053"
    assert out["https://m/b"]["saved_title"] == ""      # 旧形式 = 空 (cache から復元する)
    assert out["https://m/c"]["saved_title"] == "PSA10 わるいヘルガー"


def test_cand_info_by_url_is_pure():
    import psa_hoju_fill as H
    m = H.cand_info_by_url([{"url": "https://m/a", "name": "PSA10 ナミ", "price": 9000},
                            {"url": "", "name": "x"}, None])
    assert list(m.values()) == [("PSA10 ナミ", 9000)]
