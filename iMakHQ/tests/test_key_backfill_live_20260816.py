# -*- coding: utf-8 -*-
"""生きている出品の空KEYを cert から埋める掃除 (2026-08-16)。

★経緯: KEY を埋める処理は **その日のCSVに載っている行だけ**が対象で、出品時に取りこぼした
  行は永久に空のまま残っていた。KEY が空だと補URL探索が毎晩「探索不能」で飛ばし、
  重複チェックも効かない。実測 13件中 12件は cert から引けた (= 目視は不要で、
  出品時に人が確定した値をシートに写していないだけ)。
"""
from __future__ import annotations

import importlib.util
import os
import sys

_TOOLS = r"C:\dev\iMak\iMakHQ\tools"


def _load():
    spec = importlib.util.spec_from_file_location(
        "_hq_key_backfill", os.path.join(_TOOLS, "key_backfill_live.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    for p in (_TOOLS, r"C:\dev\iMak\iMakeBayAPI"):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec.loader.exec_module(mod)
    return mod


K = _load()


def _row(item_id="", cert="", key="", sold="", cat="TCG", title="t"):
    r = [""] * 40
    r[1], r[2], r[3], r[8], r[17], r[34] = item_id, title, sold, cert, cat, key
    return r


def test_only_live_rows_with_blank_key():
    """対象は「生きている・KEYが空・certがある」行だけ。"""
    vals = [[],
            _row("358a", "111"),                        # ← 対象
            _row("358b", "222", key="one_piece_tcg:X"),  # KEY 有り → 触らない
            _row("358c", "333", sold="○"),               # 売り切れ → 対象外
            _row("", "444"),                             # 未出品 → 対象外
            _row("358e", ""),                            # cert 無し → 引けない
            _row("358f", "555", cat="一番くじ")]          # 別カテゴリ
    got = [t["cert"] for t in K.find_targets(vals)]
    assert got == ["111"], got


def test_writes_only_when_category_is_unique():
    """同じ product_id が複数カテゴリに実在する時は書かない (OP と Gundam は同じ体系)。"""
    targets = [{"row": 2, "itemID": "358a", "cert": "1", "title": "a"},
               {"row": 3, "itemID": "358b", "cert": "2", "title": "b"}]
    pid = {"1": "ST02-010", "2": "CP6-031"}
    cats = {"ST02-010": ["one_piece_tcg", "gundam_tcg"], "CP6-031": ["pokemon_tcg"]}
    ok, unresolved, ambiguous = K.plan(targets, pid.get, lambda ids: cats)
    assert [t["key"] for t in ok] == ["pokemon_tcg:CP6-031"]
    assert [t["cert"] for t in ambiguous] == ["1"]
    assert unresolved == []


def test_unresolvable_cert_is_reported_not_guessed():
    """cert から引けない行は **書かず**、目視待ちとして残す (推測で埋めない)。"""
    targets = [{"row": 2, "itemID": "358a", "cert": "9", "title": "zoro"}]
    ok, unresolved, ambiguous = K.plan(targets, lambda _c: "", lambda ids: {})
    assert ok == [] and ambiguous == []
    assert [t["cert"] for t in unresolved] == ["9"]


def test_catalog_missing_pid_is_not_written():
    """確定値は引けても catalog に無ければ書かない (カテゴリを決められない)。"""
    targets = [{"row": 2, "itemID": "358a", "cert": "1", "title": "a"}]
    ok, unresolved, _amb = K.plan(targets, lambda _c: "XX-999", lambda ids: {})
    assert ok == [] and [t["cert"] for t in unresolved] == ["1"]


def test_it_runs_every_night():
    """夜間バッチに入っていること (手で思い出さないと動かない掃除にしない)。"""
    bat = open(os.path.join(_TOOLS, "run_hoju_search.bat"), encoding="ascii").read()
    assert "key_backfill_live.py" in bat
    assert bat.index("key_backfill_live.py") < bat.index("psa_hoju_fill.py search --limit=30"), \
        "補URL検索より前に埋めないと、その晩は探索不能のまま飛ばされる"


def test_daytime_screen_is_assembled_at_night():
    """★昼のボタンは「表示するだけ」にする (2026-08-16)。

    実測: 🩹 は8分のうち約7分が「対象49件を1件ずつ eBay画像取得 + 絵柄をAI照合」で、
    画面に出たのは10件。人がいなくてもできる作業なので夜に回す。
    --dry-run は同じ組み立てを行い、ブラウザを開かず書込もしないので、
    画像キャッシュと絵柄キャッシュだけが温まる。
    """
    bat = open(os.path.join(_TOOLS, "run_hoju_search.bat"), encoding="ascii").read()
    assert "psa_hoju_fill.py confirm --dry-run" in bat, "昼の組み立てを夜に回していない"
    # 候補が無いと組み立てられないので、検索より後に置く
    assert bat.index("confirm --dry-run") > bat.index("psa_hoju_fill.py search --limit=30")


def _naked():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_hq_naked_sheet", os.path.join(_TOOLS, "hoju_naked_sheet.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def test_naked_list_uses_the_same_three_words():
    """★2026-08-17: 丸腰の一覧タブ。状態は3つだけで、語彙はボタンと揃える。

    ユーザー「42件はどこにあるの?」→ 商品管理シートに散っていて見えなかった。
    内部の理由名 (all_art / no_cand …) をそのまま出すと読めない、は 8/15 に指摘済み。
    """
    N = _naked()
    assert N.classify("all_art", False, False)[0] == N.WAIT
    assert N.classify("no_cand", False, False)[0] == N.WAIT
    assert N.classify("no_cache", False, False)[0] == N.ACT
    assert N.classify("all_number", False, False)[0] == N.ACT
    assert N.classify("", True, False) == (N.READY, "候補あり")
    assert "未判定" in N.classify("", True, True)[1]
    # 理由は日本語 (内部名を出さない)
    assert N.classify("all_art", False, False)[1] == "絵柄が別カード"


def test_naked_list_is_sorted_action_first():
    """押せば片づくものを上に、待つしかないものを下に。"""
    N = _naked()
    tg = [{"row": 1, "itemID": "a", "cert": "1", "title": "t", "n_backups": 0}]
    rows = N.build_rows(tg, [(tg[0], [], "all_art", False),
                             (tg[0], [{"x": 1}], "", False),
                             (tg[0], [], "no_cache", False)], "2026-08-17")
    assert [r[0] for r in rows[1:]] == [N.READY, N.ACT, N.WAIT]


def test_naked_list_runs_every_night():
    bat = open(os.path.join(_TOOLS, "run_hoju_search.bat"), encoding="ascii").read()
    assert "hoju_naked_sheet.py" in bat
