# -*- coding: utf-8 -*-
"""補URLのボタンを系統ごとに並べる (2026-09-03)。

## なぜ
補URLのボタンが「🆕 補URL 当日分 / 🔎 slice2 / 🩹 slice3」という名前で、
**どれが PSA でどれが一番くじか分からなかった**。UT を足すと3系統が混ざる。
ユーザー要望「PSAなのか一番くじなのかTシャツなのかグルーピングして分かりやすく」。

系統名をラベルに入れ、パネルでは系統ごとの小枠に分ける。
"""
import os
import re

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()


def _labels():
    return re.findall(r'"label": "([^"]*補URL[^"]*)"', _SRC)


def test_every_aux_button_says_which_product_line():
    """系統名 (PSA / UT / 一番くじ / 全系統) が入っていること。"""
    for lab in _labels():
        assert any(k in lab for k in ("PSA", "UT", "くじ", "全系統")), lab


def test_ut_has_both_search_and_confirm():
    assert '"label": "🔎 UT 補URL ② 夜に探す"' in _SRC
    assert '"label": "🩹 UT 補URL ③ 目視"' in _SRC


def test_ut_search_does_not_write_to_the_sheet():
    """検索は貯めるだけ。書くのは目視の後 (補URLの決まり)。"""
    i = _SRC.index('"label": "🔎 UT 補URL ② 夜に探す"')
    seg = _SRC[i:i + 700]
    assert '"ut_hoju_fill.py", "search"' in seg


def test_panel_splits_the_three_product_lines():
    """商材ごとに箱を作っている (PSA / UT / 一番くじ)。"""
    i = _SRC.index('for _name in (')
    assert '"PSA (TCG)", "Tシャツ (UT)", "一番くじ"' in _SRC[i:i + 120]
    # どのボタンがどの商材かを判定している
    assert "def _line_of(" in _SRC


def test_panel_boxes_are_per_product_line_in_work_order():
    """★2026-09-03 ユーザー要望「商材ごとに作業順に並べて、囲って」。

    従来は 工程ごと (発見 / 出品前チェック / 補URL) の箱で、1つの箱に PSA と
    一番くじと UT が混ざり、自分の商材の次の一手が読み取れなかった。
    """
    assert "📦 {_name} — 出品した後の作業 (補URL / 在庫切れ再仕入れ)" in _SRC
    # 作業順 (当日分 → 夜間検索 → 昼の目視) で並べている
    i = _SRC.index("def _step_rank(")
    assert '"①②③④"' in _SRC[i:i + 500]
    # ★2026-09-03: 置き場所は **既存メンテ**。補URLは出品した後の作業なので
    #   新規出品パネルに置くのは誤り (ユーザー指摘)。
    assert _SRC.index("for _name in (") > _SRC.index("===== 🔧 既存メンテ =====")


def test_ut_buttons_show_counts():
    """ヒントに件数を出し、押す価値がある時だけ青にする。"""
    assert '"badge": "ut_search"' in _SRC
    assert '"badge": "ut_confirm"' in _SRC
    assert '"ut_search": ut_s_txt' in _SRC
    # ★2026-09-03 (後): 探す系は夜間バッチが減らすので黒。
    #   ただし **夜が転んだ日は減らない**ので、その日は青に戻す。
    assert '"ut_search": bool(_ut.get("search")) and not _auto' in _SRC
    assert '"ut_confirm": bool(_ut.get("confirm"))' in _SRC


def test_every_ut_button_has_a_hint():
    for lab in ('🔎 UT 補URL ② 夜に探す', '🩹 UT 補URL ③ 目視'):
        i = _SRC.index('"label": "%s"' % lab)
        assert '"tip"' in _SRC[i:i + 800], lab


def test_no_button_appears_in_two_places():
    """同じボタンが 商材の箱 と 在庫補充枠 の両方に出ていた (ユーザー指摘)。"""
    assert "_boxed_idxs = set()" in _SRC
    # 在庫補充・在庫なし の枠は、箱に出した分を除いてから並べる
    assert "for i in ug[\"report\"] if i not in _boxed_idxs" in _SRC
    assert "for i in ug[\"oos\"] if i not in _boxed_idxs" in _SRC


def test_boxes_have_no_listing_buttons():
    """箱は **出品した後** の作業だけ。出品は新規出品パネルの仕事。"""
    i = _SRC.index("for _name in (")
    seg = _SRC[i:i + 1400]
    assert "_head" not in seg, "箱に出品ボタン(新規/自動)が残っている"


def test_all_kuji_entrypoints_are_recognised():
    """一番くじの夜間検索は run_kuji_night.py。名前が違うだけで箱から漏れていた。"""
    i = _SRC.index("def _line_of(")
    seg = _SRC[i:i + 700]
    for name in ("ichibankuji_restock.py", "kuji_hoju_fill.py", "run_kuji_night.py"):
        assert name in seg, name


def test_cross_product_buttons_stay_out_of_the_boxes():
    """「全系統」の物は特定の商材の箱に入れない。"""
    i = _SRC.index("def _line_of(")
    assert '"全系統" in lab' in _SRC[i:i + 400]


def test_ut_count_is_computed_in_the_shared_subprocess():
    """件数は tools/ を sys.path に入れた subprocess で数える。

    パネル側から直接 import していたら tools/ が見えず、毎回「取得できず」だった
    (ユーザー指摘 2026-09-03)。他のボタン (PSA / 一番くじ / 取下げ / 棚) と同じ口に乗せる。
    """
    assert '"    import ut_hoju_fill as UT' in _SRC
    assert "d['ut']=UT.count_workload()" in _SRC
    # パネル側は集計結果から読むだけ (直接 import しない)
    assert 'import ut_hoju_fill as _uh' not in _SRC
    assert '_ut = (w0.get("ut") or {})' in _SRC


def test_badge_texts_are_defined_on_every_path():
    """件数の文字列が **どの分岐でも** 定義されていること。

    ★2026-09-03 実害: UT の再仕入れ2つを足した時、エラー時の分岐でしか代入しておらず
      正常時に NameError。ボタンの件数が「取得に失敗」になった (2回発生)。
      by_kind に渡す名前は、その手前で必ず両方の分岐に現れる。
    """
    i = _SRC.index("by_kind = {")
    head = _SRC[max(0, i - 3200):i]
    names = re.findall(r'"[\w]+": (\w+_txt)', _SRC[i:i + 1400])
    for n in sorted(set(names)):
        if not n.startswith("ut_"):
            continue                      # UT 以外は別ブロックで定義される
        assert re.search(r"\b%s\s*=" % n, head), f"{n} が代入されていない"
