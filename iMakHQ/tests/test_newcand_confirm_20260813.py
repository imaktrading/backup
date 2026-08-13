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
                          "outs": [{"idx": 2, "reason": "bundle"}], "holds": [3]})
    assert [p["idx"] for p in res["picks"]] == [1]
    assert res["picks"][0]["cert"] == "147704361", "cert は数字だけ取り出す"
    assert res["outs"] == [{"idx": 2, "reason": "bundle"}] and res["holds"] == [3]


def test_parse_result_empty():
    res = N.parse_result({})
    assert res == {"picks": [], "catalog_reqs": [], "outs": [], "card_nos": [], "holds": []}


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


# ---------------------------------------------------------------------------
# 7. 「該当なし」という着地を作らない (2026-08-13 ユーザー確定)
# ---------------------------------------------------------------------------
def test_outcomes_are_three_plus_hold():
    """結論は 出品 / カタログ追加依頼 / 対象外(理由必須) の3つ。それ以外は未結論。"""
    res = N.parse_result({
        "picks": [{"idx": 0, "pid": "EB03-053", "category": "one_piece_tcg", "cert": "1"}],
        "catalog_reqs": [1],
        "outs": [{"idx": 2, "reason": "bundle"}],
        "holds": [3]})
    assert [p["idx"] for p in res["picks"]] == [0]
    assert res["catalog_reqs"] == [1]
    assert res["outs"] == [{"idx": 2, "reason": "bundle"}]
    assert res["holds"] == [3]


def test_out_without_reason_becomes_hold_not_a_conclusion():
    """★理由を選ばない『対象外』は結論ではない → 未結論に戻す (捨てさせない)。"""
    res = N.parse_result({"outs": [{"idx": 5, "reason": ""},
                                   {"idx": 6, "reason": "しらない値"}]})
    assert res["outs"] == []
    assert res["holds"] == [5, 6]


def test_html_has_catalog_request_button_and_reasons():
    v = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami", "image": "https://x/a.png"}]
    page = N.build_html([_item(0, v)]).decode()
    assert "カタログに無い→追加依頼" in page
    assert "まとめ売り" in page and "PSA10ではない" in page
    assert "該当なし" not in page, "『該当なし』という着地を残さない"


def test_guess_category_from_title():
    assert N.guess_category("PSA10 ワンピースカード ナミ", []) == "one_piece_tcg"
    assert N.guess_category("PSA10 ポケモンカード", []) == "pokemon_tcg"
    assert N.guess_category("なぞの商品", []) == "", "分からない時は推測しない"
    assert N.guess_category("なぞ", [{"category": "gundam_tcg"}]) == "gundam_tcg"


# ---------------------------------------------------------------------------
# 8. 保管は「貼り付け先の列名」で (商品管理シートへの自動追加はしない)
# ---------------------------------------------------------------------------
def test_out_header_is_paste_ready():
    """ユーザー確定「シートへの追加は危険。保管されていたらコピペする」。

    見出しが貼り付け先の列名になっていること + 自動 append をしていないこと。
    """
    assert N.OUT_HEADER[:6] == ["用途", "A列:仕入元URL", "C列:タイトル", "I列:cert",
                                "R列:カテゴリ", "AI列:KEY"]
    src = open(os.path.join(_TOOLS, "newcand_confirm.py"), encoding="utf-8").read()
    assert "_product_ws" not in src, "商品管理シート本体を触ってはいけない"
    assert "append_row" not in src


def test_save_builds_paste_row(monkeypatch):
    written = {}
    monkeypatch.setattr(N, "_append_tab", lambda tab, h, rows: written.setdefault(tab, rows))
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    items = [_item(0, [{"pid": "EB03-053_p1", "category": "one_piece_tcg", "name": "Nami",
                        "image": ""}])]
    N.save(items, {"picks": [{"idx": 0, "pid": "EB03-053_p1", "category": "one_piece_tcg",
                              "cert": "147704361"}],
                   "catalog_reqs": [], "outs": [], "holds": []})
    row = written[N.OUT_TAB][0]
    assert row[0] == N.USE_LIST                          # 用途
    assert row[1] == "https://m/0"                       # A列 = 仕入元URL
    assert row[3] == "147704361"                         # I列 = cert
    assert row[4] == "TCG"                               # R列 = カテゴリ
    assert row[5] == "one_piece_tcg:EB03-053_p1"         # AI列 = canonical KEY


# ---------------------------------------------------------------------------
# 9. タイトルが無い候補は「目視で番号を入れて次回引く」(2026-08-13 ユーザー指示)
# ---------------------------------------------------------------------------
def test_parse_result_collects_typed_card_numbers():
    res = N.parse_result({"card_nos": [{"idx": 0, "no": " op05-002 "},
                                       {"idx": 1, "no": ""},
                                       {"no": "X"}]})
    assert res["card_nos"] == [{"idx": 0, "no": "OP05-002"}], "大文字化 + 空は捨てる"


def test_html_has_card_number_input_prefilled():
    v = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami", "image": ""}]
    page = N.build_html([_item(0, v)]).decode()
    assert "class='cno'" in page, "カード番号の入力欄が無い"
    assert 'value="EB03-053"' in page, "読み取れている番号を初期値に入れる"


def test_save_writes_typed_card_numbers(monkeypatch):
    written = {}
    monkeypatch.setattr(N, "_append_tab", lambda *a: None)
    monkeypatch.setattr(N.sheet_io, "read_tab", lambda tab: [])
    monkeypatch.setattr(N.sheet_io, "write_rows_to_tab",
                        lambda tab, rows: written.setdefault(tab, rows))
    items = [_item(0, [], title="", card_no="")]
    N.save(items, {"picks": [], "catalog_reqs": [], "outs": [], "holds": [0],
                   "card_nos": [{"idx": 0, "no": "OP05-002"}]})
    rows = written[N.CNO_TAB]
    assert rows[0] == N.CNO_HEADER
    assert rows[1][0] == "https://m/0" and rows[1][1] == "OP05-002"


# ---------------------------------------------------------------------------
# 10. この画面は「カードの特定」だけ (鑑定番号は出品直前に入れる)
# ---------------------------------------------------------------------------
def test_viewer_has_no_cert_input():
    """ユーザー確定「出品までには鑑定番号を入れるから、今はカードを特定することに専念」。"""
    v = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami", "image": ""}]
    page = N.build_html([_item(0, v)]).decode()
    assert "class='cert'" not in page, "鑑定番号の入力欄が残っている"
    assert "class='cno'" in page, "カード番号の入力欄は要る"
    assert "鑑定番号は出品の直前" in page


def test_saved_row_leaves_cert_empty(monkeypatch):
    written = {}
    monkeypatch.setattr(N, "_append_tab", lambda tab, h, rows: written.setdefault(tab, rows))
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    items = [_item(0, [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami",
                        "image": ""}])]
    N.save(items, {"picks": [{"idx": 0, "pid": "EB03-053", "category": "one_piece_tcg",
                              "cert": ""}],
                   "catalog_reqs": [], "outs": [], "holds": [], "card_nos": []})
    assert written[N.OUT_TAB][0][3] == "", "I列:cert は空のまま (出品直前に入れる)"


# ---------------------------------------------------------------------------
# 11. 英語版の扱い (2026-08-13 ユーザー指摘)
# ---------------------------------------------------------------------------
def test_first_image_prefers_japanese_and_same_variant():
    """★catalog の images は英語版が先頭。日本語 + その版の絵を選ぶ。"""
    imgs = ('["https://files.bandai-tcg-plus.com/card_image/OP-EN/EB03/batch_EB03-053_p2.png",'
            ' "https://files.bandai-tcg-plus.com/card_image/OP-JA/EB03/batch_EB03-053.png",'
            ' "https://www.onepiece-cardgame.com/images/cardlist/card/EB03-053_p2.png"]')
    assert N._first_image(imgs, "EB03-053_p2").endswith("EB03-053_p2.png")
    # 版指定なしでも英語は避ける
    assert "OP-EN" not in N._first_image(imgs)


def test_is_en_only():
    assert N.is_en_only("en") is True
    assert N.is_en_only("both") is False
    assert N.is_en_only("ja") is False
    assert N.is_en_only(None) is False, "未設定は日本語あり扱い (捨てない)"


def test_html_flags_english_only_and_pushes_catalog_request():
    """英語版しか無い = 日本語版が未収録 → 追加依頼へ誘導する (黙って消さない)。"""
    en = [{"pid": "EB03-053_p2", "category": "one_piece_tcg", "name": "Nami",
           "image": "https://x/a.png", "en_only": True}]
    page = N.build_html([_item(0, en)]).decode()
    assert "英語版のみ" in page
    assert "日本語版がカタログに未収録" in page


def test_gone_reason_is_limited_to_unidentifiable():
    """「ページが消えている」は売り切れ。カードが特定できるなら出品候補にしてよい。"""
    labels = dict(N.OUT_REASONS)
    assert "カードも特定できない" in labels["gone"]
    v = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami", "image": ""}]
    page = N.build_html([_item(0, v)]).decode()
    assert "無在庫なので仕入元は後で探し直せます" in page


# ---------------------------------------------------------------------------
# 12. 同じカードは1行だけ『出品』/ 入力番号を依頼に反映 (2026-08-13)
# ---------------------------------------------------------------------------
def test_mark_use_keeps_one_listing_per_card():
    rows = [["", "u1", "t", "", "TCG", "one_piece_tcg:EB03-053", "EB03-053", "i", "d"],
            ["", "u2", "t", "", "TCG", "one_piece_tcg:EB03-053", "EB03-053", "i", "d"],
            ["", "u3", "t", "", "TCG", "one_piece_tcg:OP07-047", "OP07-047", "i", "d"]]
    out = N.mark_use(rows, listed_keys=())
    assert [r[0] for r in out] == [N.USE_LIST, N.USE_AUX, N.USE_LIST]


def test_mark_use_respects_already_saved_keys():
    """前回の走行で出品にした KEY は、今回は補URL に回す (二重出品を作らない)。"""
    rows = [["", "u9", "t", "", "TCG", "one_piece_tcg:EB03-053", "EB03-053", "i", "d"]]
    out = N.mark_use(rows, listed_keys={"one_piece_tcg:EB03-053"})
    assert out[0][0] == N.USE_AUX


def test_catalog_request_uses_typed_card_number(monkeypatch):
    """★番号を打ったのに『番号不明』で依頼していた。打った番号を使う。"""
    sent = {}
    monkeypatch.setattr(N, "_append_tab", lambda *a: None)
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N.sheet_io, "read_tab", lambda tab: [])
    monkeypatch.setattr(N.sheet_io, "write_rows_to_tab", lambda tab, rows: None)
    monkeypatch.setattr(N, "append_missing_models",
                        lambda rows, path=None: sent.setdefault("rows", rows) or len(rows))
    monkeypatch.setattr(N, "catalog_variants", lambda no, db=None: [])   # catalog に無い
    items = [_item(0, [], title="PSA10 ワンピース", card_no="")]
    N.save(items, {"picks": [], "catalog_reqs": [0], "outs": [], "holds": [],
                   "card_nos": [{"idx": 0, "no": "OP13-118"}]})
    assert "OP13-118" in sent["rows"][0][1]
    assert "番号不明" not in sent["rows"][0][1]


def test_catalog_request_skipped_when_typed_number_exists_in_catalog(monkeypatch):
    """入力番号で catalog に在るなら依頼しない (無駄な依頼を出さない)。"""
    called = {}
    monkeypatch.setattr(N, "_append_tab", lambda *a: None)
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N.sheet_io, "read_tab", lambda tab: [])
    monkeypatch.setattr(N.sheet_io, "write_rows_to_tab", lambda tab, rows: None)
    monkeypatch.setattr(N, "append_missing_models",
                        lambda rows, path=None: called.setdefault("n", len(rows)))
    monkeypatch.setattr(N, "catalog_variants", lambda no, db=None: [{"pid": "OP13-118"}])
    items = [_item(0, [], title="PSA10 ワンピース", card_no="")]
    N.save(items, {"picks": [], "catalog_reqs": [0], "outs": [], "holds": [],
                   "card_nos": [{"idx": 0, "no": "OP13-118"}]})
    assert "n" not in called, "catalog に在るのに依頼を出している"
