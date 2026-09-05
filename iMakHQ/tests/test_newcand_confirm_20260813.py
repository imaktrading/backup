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

import pytest

_ROOT = r"C:\dev\iMak"
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
    h = ["itemID", "cert", "url", "title"]
    src = [("補URL候補NG", h, ["358_1", "111", "https://m/a", "t"]),
           ("補URL候補NG", h, ["358_2", "222", "https://m/b", "t"]),
           ("補URL要調査", h, ["358_3", "333", "https://m/a", "t"]),   # 重複 url
           ("補URL候補NG", h, ["358_4", "444", "", "t"]),              # url 空
           ("補URL候補NG", h, ["358_5"])]                              # 列不足
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
@pytest.fixture(autouse=True)
def reset_sheet_cache():
    """★2026-08-15: 1走行のシート読取キャッシュを入れたので、test 間で持ち越さない
    (持ち越すと前の test の monkeypatch した値を掴む)。"""
    N.reset_cache()
    yield
    N.reset_cache()


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
    assert "やることは1つ: カード番号を入れる" in page
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
    ng_head = ["itemID", "cert", "url", "title", "日付", "候補タイトル", "候補価格"]
    pr_head = ["itemID", "cert", "url", "title", "現物の番号", "現物の変種", "日付",
               "候補タイトル", "候補価格"]
    src = [("補URL候補NG", ng_head, ["358_1", "111", "https://m/a", "出品側t", "2026-08-13",
                                     "PSA10 ナミ EB03-053", 9000]),
           ("補URL候補NG", ng_head, ["358_2", "222", "https://m/b", "出品側t", "2026-07-30"]),
           ("補URL要調査", pr_head, ["358_3", "333", "https://m/c", "出品側t", "006/020", "AR",
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
    """見出しが貼り付け先の列名になっていること (手で貼る運用は残っている)。"""
    assert N.OUT_HEADER[:8] == ["用途", "HIGH転記", "A列:仕入元URL", "C列:タイトル",
                                "M列:仕入価格(円)", "I列:cert", "R列:カテゴリ", "AI列:KEY"]


def test_the_only_write_path_is_the_cert_screen():
    """商品管理シートへ書くのは **証明番号を打った時だけ**。

    ★2026-08-13 の決定は「シートへの追加は危険。保管されていたらコピペする」だったが、
      2026-09-05 にユーザーが変更:「用途が出品のも、HIGHに追記してよ。他でもやってる
      からいいでしょ。証明番号いれないとだめだね。追加するときに証明番号を入力する
      HTMLをかますか」。

      危険だった理由 (勝手に行が増える) は **人が写真を見て証明番号を打つ画面**で
      塞いでいる: 番号を打たなかった候補は1行も足さない。
      なので「一切書かない」ではなく「その画面を通した時だけ書く」を守る。
    """
    src = open(os.path.join(_TOOLS, "newcand_confirm.py"), encoding="utf-8").read()
    # 追加は run_append_high の中の1箇所だけ
    assert src.count("append_rows(") == 1
    i = src.index("append_rows(")
    fn = src.rindex("def ", 0, i)
    assert src[fn:fn + 40].startswith("def run_append_high"), src[fn:fn + 40]
    # その関数は 人が打った cert を通してからでないと行を作らない
    body = src[fn:src.index("def main():")]
    assert "_serve_confirm(build_cert_html" in body
    assert "plan_high_rows(" in body


def test_save_builds_paste_row(monkeypatch):
    written = {}
    monkeypatch.setattr(N, "_append_tab", lambda tab, h, rows: written.setdefault(tab, rows))
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N, "live_key_set", lambda: set())
    items = [_item(0, [{"pid": "EB03-053_p1", "category": "one_piece_tcg", "name": "Nami",
                        "image": ""}])]
    N.save(items, {"picks": [{"idx": 0, "pid": "EB03-053_p1", "category": "one_piece_tcg",
                              "cert": "147704361"}],
                   "catalog_reqs": [], "outs": [], "holds": []})
    row = written[N.OUT_TAB][0]
    assert row[0] == N.USE_LIST                          # 用途
    assert row[2] == "https://m/0"                       # A列 = 仕入元URL
    assert row[5] == "147704361"                         # I列 = cert
    assert row[6] == "TCG"                               # R列 = カテゴリ
    assert row[7] == "one_piece_tcg:EB03-053_p1"         # AI列 = canonical KEY


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
    assert "鑑定番号はここでは要りません" in page


def test_saved_row_leaves_cert_empty(monkeypatch):
    written = {}
    monkeypatch.setattr(N, "_append_tab", lambda tab, h, rows: written.setdefault(tab, rows))
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N, "live_key_set", lambda: set())
    items = [_item(0, [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami",
                        "image": ""}])]
    N.save(items, {"picks": [{"idx": 0, "pid": "EB03-053", "category": "one_piece_tcg",
                              "cert": ""}],
                   "catalog_reqs": [], "outs": [], "holds": [], "card_nos": []})
    assert written[N.OUT_TAB][0][5] == "", "I列:cert は空のまま (出品直前に入れる)"


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
    rows = [["", "", "u1", "t", "", "", "TCG", "one_piece_tcg:EB03-053", "EB03-053", "i", "d"],
            ["", "", "u2", "t", "", "", "TCG", "one_piece_tcg:EB03-053", "EB03-053", "i", "d"],
            ["", "", "u3", "t", "", "", "TCG", "one_piece_tcg:OP07-047", "OP07-047", "i", "d"]]
    out = N.mark_use(rows, listed_keys=())
    assert [r[0] for r in out] == [N.USE_LIST, N.USE_AUX, N.USE_LIST]


def test_mark_use_respects_already_saved_keys():
    """前回の走行で出品にした KEY は、今回は補URL に回す (二重出品を作らない)。"""
    rows = [["", "", "u9", "t", "", "", "TCG", "one_piece_tcg:EB03-053", "EB03-053", "i", "d"]]
    out = N.mark_use(rows, listed_keys={"one_piece_tcg:EB03-053"})
    assert out[0][0] == N.USE_AUX


def test_catalog_request_uses_typed_card_number(monkeypatch):
    """★番号を打ったのに『番号不明』で依頼していた。打った番号を使う。"""
    sent = {}
    monkeypatch.setattr(N, "_append_tab", lambda *a: None)
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N, "live_key_set", lambda: set())
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
    monkeypatch.setattr(N, "live_key_set", lambda: set())
    monkeypatch.setattr(N.sheet_io, "read_tab", lambda tab: [])
    monkeypatch.setattr(N.sheet_io, "write_rows_to_tab", lambda tab, rows: None)
    monkeypatch.setattr(N, "append_missing_models",
                        lambda rows, path=None: called.setdefault("n", len(rows)))
    monkeypatch.setattr(N, "catalog_variants", lambda no, db=None: [{"pid": "OP13-118"}])
    items = [_item(0, [], title="PSA10 ワンピース", card_no="")]
    N.save(items, {"picks": [], "catalog_reqs": [0], "outs": [], "holds": [],
                   "card_nos": [{"idx": 0, "no": "OP13-118"}]})
    assert "n" not in called, "catalog に在るのに依頼を出している"


# ---------------------------------------------------------------------------
# 13. 「どこへ行ったか」を台帳で見えるようにする (2026-08-13)
# ---------------------------------------------------------------------------
def test_status_of_reports_destination():
    out = [[N.USE_LIST, "済", "https://m/a", "t", "", "", "TCG", "k", "p", "i", "d"],
           [N.USE_AUX, "", "https://m/b", "t", "", "", "TCG", "k", "p", "i", "d"]]
    ng = [["https://m/c", "カタログ未収録 → 追加依頼を起票", "d", "t"]]
    assert "HIGH転記済" in N.status_of("https://m/a", out, ng)
    assert "補URL" in N.status_of("https://m/b", out, ng)
    assert "HIGH転記済" not in N.status_of("https://m/b", out, ng)
    assert N.status_of("https://m/c", out, ng).startswith("カタログ未収録")
    assert N.status_of("https://m/zzz", out, ng) == "", "未処理は空"


def test_status_of_ignores_url_noise():
    out = [[N.USE_LIST, "", "https://jp.mercari.com/item/m1/", "t", "", "", "TCG", "k", "p",
            "i", "d"]]
    assert N.status_of("https://jp.mercari.com/item/m1?utm=x", out, []) != ""


# ---------------------------------------------------------------------------
# 14. 価格 (2026-08-13 ユーザー指摘「価格がないけど大丈夫かな」)
# ---------------------------------------------------------------------------
def test_out_header_has_price_column():
    assert "M列:仕入価格(円)" in N.OUT_HEADER


def test_save_writes_candidate_price(monkeypatch):
    written = {}
    monkeypatch.setattr(N, "_append_tab", lambda tab, h, rows: written.setdefault(tab, rows))
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N, "live_key_set", lambda: set())
    items = [_item(0, [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami",
                        "image": ""}])]
    items[0]["price"] = 19999
    N.save(items, {"picks": [{"idx": 0, "pid": "EB03-053", "category": "one_piece_tcg",
                              "cert": ""}],
                   "catalog_reqs": [], "outs": [], "holds": [], "card_nos": []})
    assert written[N.OUT_TAB][0][4] == 19999, "M列に候補の価格が入っていない"


def test_generator_skips_rows_without_cost():
    """★価格が1つも無い行は出品しない (fail-closed)。$100固定で出す方が危険。"""
    src = open(r"C:\dev\iMak\iMakTCG\psa_to_csv.py", encoding="utf-8").read()
    assert "_skipped_nocost" in src
    assert "仕入値なしガード" in src


def test_migrate_out_rows_requires_exact_header():
    """★列を足した時、先頭2列だけ見て素通りさせない (実際に列ズレを起こした)。"""
    old = [["用途", "HIGH転記", "A列:仕入元URL", "C列:タイトル", "I列:cert", "R列:カテゴリ",
            "AI列:KEY", "product_id", "元itemID", "日付"],
           ["出品", "", "u", "t", "", "TCG", "k", "p", "i", "d"]]
    out = N.migrate_out_rows(old)
    assert len(out[0]) == len(N.OUT_HEADER), "新形式の列数に揃っていない"
    assert out[0][6] == "TCG", "R列の位置がずれている"


# ---------------------------------------------------------------------------
# 15. 同じカードを何度も目視させない (2026-08-13 ユーザー指摘)
# ---------------------------------------------------------------------------
def test_pending_rows_reads_columns_by_header_name():
    """★列が増えても位置で決め打ちしない (状態列を足してタイトルが壊れた実バグ)。"""
    head = ["itemID", "cert", "url", "title", "日付", "状態"]          # 候補タイトルが無い形
    rows = [("補URL候補NG", head, ["i", "c", "https://m/a", "t", "d", "新規出品候補へ (出品)"])]
    out = N.pending_rows(rows, done_urls=set())
    assert out[0]["saved_title"] == "", "状態列をタイトルとして拾っている"
    head2 = ["itemID", "cert", "url", "title", "日付", "候補タイトル", "候補価格", "状態"]
    rows2 = [("補URL候補NG", head2, ["i", "c", "https://m/b", "t", "d", "PSA10 ナミ", 9000, "済"])]
    out2 = N.pending_rows(rows2, done_urls=set())
    assert out2[0]["saved_title"] == "PSA10 ナミ"
    assert out2[0]["saved_price"] == "9000"


def test_pick_applies_to_same_card_duplicates(monkeypatch):
    """同じカードの別の仕入元は、同じ結論 (補URL) にして人に聞かない。"""
    written = {}
    monkeypatch.setattr(N, "_append_tab", lambda tab, h, rows: written.setdefault(tab, rows))
    monkeypatch.setattr(N, "already_listed_keys", lambda: set())
    monkeypatch.setattr(N, "live_key_set", lambda: set())
    it = _item(0, [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami", "image": ""}])
    it["dups"] = [{"url": "https://m/dup1", "title": "同じカード別出品", "price": 25000,
                   "src_itemid": "358_1"}]
    N.save([it], {"picks": [{"idx": 0, "pid": "EB03-053", "category": "one_piece_tcg",
                             "cert": ""}],
                  "catalog_reqs": [], "outs": [], "holds": [], "card_nos": []})
    rows = written[N.OUT_TAB]
    assert [r[0] for r in rows] == [N.USE_LIST, N.USE_AUX]
    assert rows[1][2] == "https://m/dup1"
    assert rows[1][7] == "one_piece_tcg:EB03-053", "同じ KEY を引き継いでいない"


def test_reason_select_sets_out_action():
    """理由を選んだだけで『対象外』に確定する (ボタン+理由の二度手間をなくす)。"""
    v = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami", "image": ""}]
    page = N.build_html([_item(0, v)]).decode()
    assert "onchange='pickRsn(this)'" in page
    assert "function pickRsn" in page
    assert "setAct(box.querySelector(\"button[data-a='out']\"))" in page


def test_typed_number_is_not_counted_as_unresolved():
    """★カード番号を入れただけ = 次回へ回す進捗。未結論に数えない。"""
    v = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami", "image": ""}]
    page = N.build_html([_item(0, v)]).decode()
    assert "else if(cno && cno!==(b.dataset.cno||'')){ /* 次回へ */ }" in page
    assert "番号入力(次回へ)" in page


def test_no_candidate_screen_tells_exactly_one_action():
    """候補なしの時にやることは1つ (番号を入れる)。迷わせない。"""
    base = dict(_item(0, []), card_no="", no_from_typed=False, title="")
    page = N.build_html([base]).decode()
    assert "やることは1つ: カード番号を入れる" in page
    assert "ボタンは不要" in page


def test_typed_number_but_still_no_candidate_points_to_catalog_request():
    """番号を入れても候補が出ない = カタログに無い、が確定 → 追加依頼へ誘導。"""
    base = dict(_item(0, []), card_no="OP13-118", no_from_typed=True)
    page = N.build_html([base]).decode()
    assert "カタログに無い" in page and "OP13-118" in page


# ---------------------------------------------------------------------------
# 16. 画面の構成 (2026-08-13「何をしたらいいのか分かりやすい構成にしてな」)
# ---------------------------------------------------------------------------
def test_html_groups_items_by_what_to_do():
    """やることが同じものをまとめて並べる (1件ずつ判断の種類が変わらない)。"""
    v = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami", "image": ""}]
    items = [dict(_item(0, []), card_no="", no_from_typed=False),          # ② 番号入力
             dict(_item(1, v)),                                            # ① 版を選ぶ
             dict(_item(2, []), card_no="OP13-118", no_from_typed=True)]   # ③ 追加依頼
    page = N.build_html(items).decode()
    i1 = page.index("① 絵柄を見て版を選ぶ")
    i2 = page.index("② カード番号を入れるだけ")
    i3 = page.index("③ カタログに無い")
    assert i1 < i2 < i3, "①②③ の順に並んでいない"
    assert page.index("data-idx='1'") < page.index("data-idx='0'") < page.index("data-idx='2'")


# ---------------------------------------------------------------------------
# 17. 既に出品中のカードは目視に出さない (2026-08-13)
# ---------------------------------------------------------------------------
def test_live_cards_is_used_before_showing(monkeypatch):
    """ユーザー指摘「そんなのこっちでは分からないやん」= 機械が突き合わせて外す。"""
    src = open(os.path.join(_TOOLS, "newcand_confirm.py"), encoding="utf-8").read()
    assert "def live_cards()" in src
    assert "decided = dict(live_cards())" in src, "出品中カードを除外していない"


def test_live_cards_registers_printed_number(monkeypatch):
    """★ポケモンは印刷番号(102/078)と product_id(SV1V-102)が別体系。両方を入口にする。"""
    rows = [["url", "358xxxx", "t"] + [""] * 31 + ["pokemon_tcg:SV1V-102"]]
    monkeypatch.setattr(N.sheet_io, "_product_ws",
                        lambda: type("W", (), {"get_all_values": lambda self: [[]] + rows})())
    out = N.live_cards()
    assert "SV1V-102" in out
    assert "102/078" in out, f"印刷番号が入口になっていない: {list(out)}"


def test_live_key_set_keeps_every_variant(monkeypatch):
    """★live_cards() は番号→代表KEYなので版が漏れる (OP05-119 が実際に漏れた)。
    用途の判定には KEY をそのまま集めた集合を使う。"""
    rows = [["u", "358a", "t"] + [""] * 31 + ["one_piece_tcg:OP05-119_p8"],
            ["u", "358b", "t"] + [""] * 31 + ["one_piece_tcg:OP05-119"],
            ["u", "", "t"] + [""] * 31 + ["one_piece_tcg:NOT-LISTED"]]
    monkeypatch.setattr(N.sheet_io, "_product_ws",
                        lambda: type("W", (), {"get_all_values": lambda self: [[]] + rows})())
    ks = N.live_key_set()
    assert ks == {"one_piece_tcg:OP05-119_p8", "one_piece_tcg:OP05-119"}


def test_foreign_language_has_its_own_reason():
    """★外国語版を「別ジャンル」に混ぜない。何件捨てているか数えられる形で残す。"""
    labels = dict(N.OUT_REASONS)
    assert "foreign" in labels
    assert "外国語版" in labels["foreign"]
    v = [{"pid": "EB03-053", "category": "one_piece_tcg", "name": "Nami", "image": ""}]
    assert "外国語版" in N.build_html([_item(0, v)]).decode()


def test_saved_candidates_are_not_shown_again(monkeypatch):
    """★2026-08-15 ユーザー「今出ているカード、以前やったよ」。

    新規出品候補タブは 8/13 に先頭へ「用途 / HIGH転記」を足したので **URL は3列目**。
    1列目を URL とみなしていたため、保管済の候補が1件も除外されず毎回また出ていた。
    """
    saved = "https://jp.mercari.com/item/m111"
    tabs = {
        N.OUT_TAB: [N.OUT_HEADER,
                    [N.USE_LIST, "", saved, "t", "", "", "TCG",
                     "one_piece_tcg:OP01-001", "OP01-001", "358a", "2026-08-14"]],
        N.NG_TAB: [N.NG_HEADER, ["https://jp.mercari.com/item/m222", "対象外", "2026-08-14", "t"]],
        N.CNO_TAB: [N.CNO_HEADER],
        "補URL候補NG": [["itemID", "cert", "url", "候補タイトル"],
                        ["358a", "1", saved + "/", "t1"],
                        ["358b", "2", "https://jp.mercari.com/item/m222", "t2"],
                        ["358c", "3", "https://jp.mercari.com/item/m333", "t3"]],
        "補URL要調査": [["itemID", "cert", "url", "候補タイトル"]],
    }
    monkeypatch.setattr(N.sheet_io, "read_tab", lambda tab, *a, **k: tabs.get(tab, []))
    monkeypatch.setattr(N.sheet_io, "_product_ws",
                        lambda: type("W", (), {"get_all_values": lambda self: [[]]})())
    monkeypatch.setattr(N, "catalog_candidates", lambda *a, **k: [])
    urls = [it["url"] for it in N.load_items(write=False)]
    assert urls == ["https://jp.mercari.com/item/m333"], f"結論済がまた出ている: {urls}"


def test_count_workload_reports_what_pressing_gives(monkeypatch):
    """★2026-08-15 ユーザー要望「ラベルに残件数出せる? 押すかどうかの判断になる」。

    出すのは **押したら目視が何件出るか**。未結論の母数を出すと、その大半が
    結論済カードの別の仕入元 (= 人に見せず補URLへ回る) なので桁がずれる。
    """
    seen = "https://jp.mercari.com/item/m900"
    tabs = {
        N.OUT_TAB: [N.OUT_HEADER,
                    [N.USE_LIST, "", "https://jp.mercari.com/item/m1", "t", "", "", "TCG",
                     "one_piece_tcg:OP01-001", "OP01-001", "358a", "2026-08-14"]],
        N.NG_TAB: [N.NG_HEADER], N.CNO_TAB: [N.CNO_HEADER],
        "補URL候補NG": [["itemID", "cert", "url", "候補タイトル"],
                        # 結論済カード(OP01-001) の別の仕入元 → 自動で補URL
                        ["358b", "1", seen, "PSA10 モンキー・D・ルフィ OP01-001"],
                        # 未結論のカード → 目視に出る
                        ["358c", "2", "https://jp.mercari.com/item/m901",
                         "PSA10 ゾロ OP02-002"]],
        "補URL要調査": [["itemID", "cert", "url", "候補タイトル"]],
    }
    wrote = []
    monkeypatch.setattr(N.sheet_io, "read_tab", lambda tab, *a, **k: tabs.get(tab, []))
    monkeypatch.setattr(N.sheet_io, "write_rows_to_tab",
                        lambda *a, **k: wrote.append(a[0]))
    monkeypatch.setattr(N.sheet_io, "_product_ws",
                        lambda: type("W", (), {"get_all_values": lambda self: [[]]})())
    monkeypatch.setattr(N, "catalog_candidates", lambda *a, **k: [])
    w = N.count_workload()
    assert w == {"show": 1, "auto": 1, "pending": 2}, w
    assert not wrote, "数えるだけなのに書いている"


def test_panel_shows_seed_backlog_on_the_button():
    """ボタンのラベルに残件を出す配線 (押す前に判断できる)。"""
    src = open(os.path.join(_ROOT, "iMakHQ", "control_panel.py"), encoding="utf-8").read()
    assert '"badge": "newcand"' in src, "🌱 ボタンに badge が付いていない"
    assert "d['newcand']=N.count_workload()" in src, "残件を数えていない"
    assert '"newcand": n_txt' in src, "ラベルに反映していない"
