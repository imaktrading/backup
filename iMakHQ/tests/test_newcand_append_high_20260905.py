# -*- coding: utf-8 -*-
"""用途=出品 の候補を商品管理シートに足す (2026-09-05)。

ユーザー指示「用途が出品のも、HIGHに追記してよ。他でもやってるからいいでしょ。
証明番号いれないとだめだね。追加するときに証明番号を入力するHTMLをかますか」。

★ここだけ cert が要る。再出品(リストック)は説明文で吸収するので cert 空でも進めるが
  (2026-09-02 のユーザー指示)、**新規出品は cert が出発点**。生成器
  iMakTCG/psa_to_csv.py は certs.txt / I列 の cert で PSA を引いてカード・グレード・
  画像を決めるので、cert が無いと1枚も作れない。cert は現物ごとに違うので機械では
  埋められない = 人が候補の写真を見て打つ。

併せて sync_status の穴も直した: A列しか見ておらず、補URL欄(AC-AG)に入れた分が
毎回「未転記」に戻されていた (同じ候補を人に何度も見せる)。
実測: 転記済 24/183 → 104/183。
"""
import os
import sys

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS = os.path.join(_HQ, "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import newcand_confirm as N  # noqa: E402

_SRC = open(os.path.join(_TOOLS, "newcand_confirm.py"), encoding="utf-8").read()
_PANEL = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()

U = "https://jp.mercari.com/item/m%d"


def _row(use, done, url, title="title", price="", key="k1", pid="pid"):
    return [use, done, url, title, price, "", "TCG", key, pid, "111", "2026-09-05"]


# ---------------------------------------------- 拾う行

def test_only_unwritten_listing_rows_are_picked():
    rows = [_row(N.USE_LIST, "", U % 1),
            _row(N.USE_LIST, "済", U % 2),          # 転記済
            _row(N.USE_AUX, "", U % 3),             # 用途が違う
            _row(N.USE_LIST, "", "")]               # URL 無し
    got = N.pending_list_rows(rows)
    assert [it["url"] for it in got] == [U % 1]
    assert got[0]["i"] == 0


# ---------------------------------------------- cert の検査

def test_cert_must_be_digits():
    items = N.pending_list_rows([_row(N.USE_LIST, "", U % 1)])
    rows, marked, skipped = N.plan_high_rows(items, {0: "12ab5678"})
    assert rows == [] and marked == set()
    assert "数字でない" in skipped[0][1]


def test_blank_cert_is_held_not_skipped():
    """未入力は保留。次回また出す (エラー扱いにしない)。"""
    items = N.pending_list_rows([_row(N.USE_LIST, "", U % 1)])
    rows, marked, skipped = N.plan_high_rows(items, {0: ""})
    assert rows == [] and marked == set() and skipped == []


def test_duplicate_cert_is_refused():
    """同じ現物を2回出さない。"""
    items = N.pending_list_rows([_row(N.USE_LIST, "", U % 1)])
    rows, _m, skipped = N.plan_high_rows(items, {0: "12345678"},
                                         existing_certs=["12345678"])
    assert rows == []
    assert "既にシートに在る" in skipped[0][1]


def test_same_cert_twice_in_one_submit_is_refused():
    rows_in = [_row(N.USE_LIST, "", U % 1, key="k1"),
               _row(N.USE_LIST, "", U % 2, key="k2")]
    items = N.pending_list_rows(rows_in)
    rows, _m, skipped = N.plan_high_rows(items, {0: "12345678", 1: "12345678"})
    assert len(rows) == 1 and len(skipped) == 1


def test_card_already_listed_is_refused():
    """同じカードを2枚出さない (重複くんが弾く前に止める)。"""
    items = N.pending_list_rows([_row(N.USE_LIST, "", U % 1, key="one_piece_tcg:OP01-001")])
    rows, _m, skipped = N.plan_high_rows(items, {0: "12345678"},
                                         listed_keys=["one_piece_tcg:OP01-001"])
    assert rows == []
    assert "既に出品中" in skipped[0][1]


# ---------------------------------------------- 足す行の中身

def test_row_layout():
    rows_in = [_row(N.USE_LIST, "", U % 1, title="PSA10 Luffy", key="k1"),
               _row(N.USE_AUX, "", U % 2, key="k1"),
               _row(N.USE_AUX, "", U % 3, key="k1"),
               _row(N.USE_AUX, "", U % 4, key="other")]
    items = N.pending_list_rows(rows_in)
    rows, marked, _s = N.plan_high_rows(items, {0: "12345678"}, out_rows=rows_in)
    r = rows[0]
    assert len(r) == 40
    assert r[N.HIGH_URL_COL] == U % 1
    assert r[N.HIGH_TITLE_COL] == "PSA10 Luffy"
    assert r[N.HIGH_CERT_COL] == "12345678"
    assert r[N.HIGH_CAT_COL] == "TCG"
    assert r[1] == "", "B列(itemID)は空 = 未出品として出品くんが拾う"
    # 同じカードの他の仕入元が補URLに入る (自分自身と別カードは入らない)
    assert [r[N.HIGH_AUX0], r[N.HIGH_AUX0 + 1]] == [U % 2, U % 3]
    assert marked == {0}


def test_key_is_not_written_to_the_new_row():
    """AI列(KEY)を書かない。未出品の行にKEYが入ると重複くんが「出品済」と読んで
    そのカードを丸ごとブロックする (orphan KEY 事故)。"""
    items = N.pending_list_rows([_row(N.USE_LIST, "", U % 1, key="one_piece_tcg:OP01-001")])
    rows, _m, _s = N.plan_high_rows(items, {0: "12345678"})
    assert rows[0][34] == ""


# ---------------------------------------------- 画面と配線

def test_html_has_a_cert_input_per_candidate():
    items = N.pending_list_rows([_row(N.USE_LIST, "", U % 1)])
    html = N.build_cert_html(items).decode("utf-8")
    assert "証明番号" in html
    assert "class='cert'" in html
    assert "data-i='0'" in html


def test_parse_cert_result():
    r = N.parse_cert_result({"certs": [{"i": 3, "cert": " 12345678 "}]})
    assert r["certs"] == {3: "12345678"} and r["sold"] == set()
    assert N.parse_cert_result({}) == {"certs": {}, "sold": set()}
    assert N.parse_cert_result({"certs": [{"i": "x"}]})["certs"] == {}


def test_panel_has_the_button():
    assert '"newcand_confirm.py", "--append-high"' in _PANEL


# ---------------------------------------------- sync_status の穴

def test_sync_status_also_looks_at_the_aux_columns():
    """補URL欄に入れた分を「未転記」に戻さない (同じ候補を何度も見せない)。"""
    i = _SRC.index("def sync_status()")
    blk = _SRC[i:i + 2200]
    assert "prod_aux" in blk
    assert "済(補URL)" in blk
    assert "HIGH_AUX0" in blk


# ---------------------------------------------- ボタンのヒント / 件数 / 青

def test_button_has_tip_count_and_blue():
    """ヒント・件数・青の3つが揃っていること。

    ★2026-09-03 ユーザー確定「押さないと減らないのに黒文字だと、無意味」。
      ユーザーは青いものしか押さない = 青にしないと機能を消したのと同じ。
      証明番号は人が打つまで永遠に減らないので、残件があれば必ず青。
    """
    i = _PANEL.index('"🌱 種→出品行に追加 (証明番号)"')
    blk = _PANEL[i - 400:i + 900]
    assert '"badge": "newcand_high"' in blk, "badge が無い = 件数が出ない"
    assert '"tip":' in blk, "tip が無いと _attach_tip が呼ばれず件数も出ない"
    assert '"label_fg"' in blk
    # 件数の文言と、青の判定
    assert "証明番号を打つ %s件" in _PANEL
    assert '"newcand_high": bool(_nh.get("pending"))' in _PANEL
    # 数えるのは subprocess 側 (パネルから直接 import すると tools/ が見えない)
    assert "d['newcand_high']=N.count_workload_high()" in _PANEL


def test_count_workload_high_is_cheap():
    """API もスクレイプも使わない (ラベルのために枠を使わない約束)。"""
    src = _SRC[_SRC.index("def count_workload_high"):]
    body = src[:src.index("def save(")]
    assert "_read_tab(OUT_TAB)" in body
    assert "_read_product" not in body
    assert "_serve_confirm" not in body


def test_button_is_step_two_of_the_seed_flow():
    """①目視 → ②証明番号 の並びとして「どこまで行ったか」を出す。"""
    assert '("newcand", "newcand_high"),' in _PANEL
    assert '"sold_restock")' in _PANEL          # STEP_SINGLES から newcand が抜けた


# ---------------------------------------------- 売り切れ (半数がこれ)

def test_sold_out_is_parsed():
    r = N.parse_cert_result({"certs": [{"i": 1, "cert": "12345678"}], "sold": [2, "3", "x"]})
    assert r["certs"] == {1: "12345678"}
    assert r["sold"] == {2, 3}


def test_html_has_a_sold_out_checkbox():
    items = N.pending_list_rows([_row(N.USE_LIST, "", U % 1)])
    html = N.build_cert_html(items).decode("utf-8")
    assert "class='sold'" in html
    assert "売り切れ" in html


def test_sync_status_keeps_marks_it_did_not_set():
    """人が付けた「売り切れ」を次の同期で消さない。

    ★これが無いと結論が消えて **同じ候補が永久に出続ける**。
      同型の穴を今日1つ踏んでいる (補URL欄に入れた分が毎回「未転記」に戻っていた)。
    """
    assert N.DONE_MARK_SOLD == "売り切れ"
    assert N.DONE_MARK_SOLD not in N.AUTO_MARKS
    i = _SRC.index("def sync_status()")
    blk = _SRC[i:i + 2600]
    assert "cur in AUTO_MARKS" in blk


def test_sold_out_row_is_not_offered_again():
    rows = [_row(N.USE_LIST, N.DONE_MARK_SOLD, U % 1)]
    assert N.pending_list_rows(rows) == []
