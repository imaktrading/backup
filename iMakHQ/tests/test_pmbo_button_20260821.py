# -*- coding: utf-8 -*-
"""TOPパネルの「📣 Pm/Bo」ボタン (2026-08-21).

ユーザー依頼: 「ボタンを出品君TOPパネルのオファー対応の横に Pm/Bo ボタンを」

UK/AU/CA のミラー出品に 広告10% と ベストオファー を付ける。
人が3サイトの画面を回って手でやっていた作業。

★いきなり書かない。**まず数えて見せて、人が了解してから**実行する。
  3,500件規模を1件ずつ書き換える処理なので、押し間違いで走らせない。
"""
from __future__ import annotations

import io
import os
import re

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL = os.path.join(HQ, "control_panel.py")
SRC = io.open(PANEL, encoding="utf-8").read()


def test_ボタンがある():
    assert 'text="📣 Pm/Bo"' in SRC


def test_オファー対応の隣にある():
    """side=right は pack した順に右から左へ並ぶ。
    見た目で隣にするには オファー対応 の **直前** に pack する."""
    i_pm = SRC.index('self.pmbo_btn.pack(')
    i_of = SRC.index('self.offer_btn.pack(')
    assert i_pm < i_of, "オファー対応 より後に pack すると隣に並ばない"


def test_押しても即実行しない():
    """★確認を挟む。3,500件を1件ずつ書き換えるので、押し間違いで走らせない."""
    body = SRC[SRC.index("def open_mirror_pmbo"):SRC.index("def open_listing")]
    assert "askyesno" in body
    # 最初の起動は --write なし (数えるだけ)
    assert "args=(False,)" in body


def test_同じ道具を呼んでいる():
    body = SRC[SRC.index("def open_mirror_pmbo"):SRC.index("def open_listing")]
    assert "mirror_promo_bestoffer.py" in body
    assert '"--write"' in body


def test_失敗を黙って飲まない():
    body = SRC[SRC.index("def open_mirror_pmbo"):SRC.index("def open_listing")]
    assert "showerror" in body


# ── 一番くじの補URL 2ボタン (2026-08-22 ユーザー指示) ──────────────────
#
# 「PSA で実績があるので、ボタンを作って」「新規出品パネルにね」
# PSA と同じ 2段 (夜=検索 / 昼=目視)。画面も PSA の確証UI をそのまま使う。

def test_一番くじの補URLボタンが2つある():
    assert "🔎 くじ 補URL ② 夜に探す" in SRC
    assert "🩹 くじ 補URL ③ 目視" in SRC


def test_ラベルが長すぎない():
    """★2026-08-22「ラベルがボタンからはみ出ていて、どのボタンが何かわからない」。
    PSA の一番長いラベル (20字) 以下に収める."""
    for lb in ("🔎 くじ 補URL ② 夜に探す", "🩹 くじ 補URL ③ 目視"):
        assert len(lb) <= 20, lb


def test_一番くじは絵文字で見分けられる():
    """★PSA と混ざって見えた。

    ★2026-09-03: 商材名は **箱の見出し**に出るようになったので、絵文字は
      商材ではなく **工程** を表すことにした (ユーザー要望「同じ機能なら表記統一」)。
        🔎 = 探す / 🩹 = 目視 / 🛒 = 再仕入れ / 🆕 = 当日分
      商材の区別は箱と、同じ箱に無い時の補足 (UT) / (くじ) で付ける。
    """
    for lb in ("🔎 くじ 補URL ② 夜に探す", "🩹 くじ 補URL ③ 目視"):
        assert lb in SRC, lb
        assert lb[0] in "🔎🩹🛒🆕"


def test_夜と昼で別のコマンド():
    # ★2026-08-22: 夜は候補 (prefetch-live) だけでなく詳細 (prefetch-detail) も要る。
    #   2つで1組なので run_kuji_night.py にまとめた。
    assert '"run_kuji_night.py"' in SRC
    assert '"ichibankuji_restock.py", "hoju"' in SRC


def test_新規出品パネルに置かれる():
    """★出品→itemID書込→補URL確保 は一連の流れ。既存メンテ側に離すと導線が切れる
    (PSA の 🆕/🩹 と同じ扱い)."""
    i = SRC.index('if "ichibankuji_restock.py" in cmd and (')
    assert 'return "hoju"' in SRC[i:i + 200]


def test_昼は件数を区切る():
    """確証UIは全件まとめて送信する = 出した分はやり切る必要がある。
    PSA と同じく1回10件ずつ."""
    i = SRC.index('"ichibankuji_restock.py", "hoju"')
    assert '"10"' in SRC[i:i + 120]


# ── ラベルを短く / 詳細はヒント / 系統ごとに並べる (2026-08-22 ユーザー指摘) ──

def test_ラベルは短い():
    """★「ラベルがボタンからはみ出ていて、どのボタンが何かわからない」."""
    import re
    for m in re.finditer(r'"label": "([^"]*補URL[^"]*)"', SRC):
        assert len(m.group(1)) <= 17, m.group(1)


def test_詳細はヒントに逃がしている():
    """★「詳細はヒントテキストにしてボタンのラベルはシンプルに」."""
    assert "_attach_tip" in SRC
    for lb in ("🔎 PSA 補URL ② 夜に探す", "🩹 PSA 補URL ③ 目視",
               "🔎 くじ 補URL ② 夜に探す", "🩹 くじ 補URL ③ 目視"):
        i = SRC.index('"label": "%s"' % lb)
        assert '"tip"' in SRC[i:i + 400], lb


def test_ヒントが出せなくてもボタンは動く():
    """装飾なので、表示に失敗しても押せなくならない."""
    i = SRC.index("def _attach_tip")
    body = SRC[i:i + 1400]
    assert "except Exception" in body


def test_系統ごとに並ぶ():
    """★「ボタン配置が、PSA、一番くじ、一番くじ、PSA になっている」.

    ★2026-09-03: 並べ替え (_order) も 工程ごとの箱もやめ、**商材ごとの箱**にした。
      UT が加わって3系統になり、順番だけではどれが何か分からなくなったため
      (ユーザー要望「商材ごとに作業順に並べて、囲って」)。
    """
    i = SRC.index("for _name in (")
    assert '"PSA (TCG)", "Tシャツ (UT)", "一番くじ"' in SRC[i:i + 120]
    # 置き場所は既存メンテ (補URLは出品した後の作業)
    assert i > SRC.index("===== 🔧 既存メンテ =====")
    # 箱の中は作業順 (当日分 → 夜間検索 → 昼の目視)
    j = SRC.index("def _step_rank(")
    assert '"①②③④"' in SRC[j:j + 500]


# ── 件数はヒントへ / 押すべき時は青 (2026-08-22 ユーザー指示) ────────────

def test_件数をラベルに焼かない():
    """★以前は件数をラベルに足していたのでボタンが4〜7行に伸び、
    何のボタンか読めなかった。ラベルは固定にする。

    ★2026-08-31 例外: 「棚を入れ替える」ボタンだけ、ユーザーが明示で
      ラベルにも件数・金額を求めた (kind == "shelf_evict" に限定)。"""
    i = SRC.index("def paint_hoju_badge")
    body = SRC[i:i + 1600]
    assert "b.config(text=text, height=(5 if extra else 3)," in body
    assert "base + by_kind" not in body
    assert 'kind == "shelf_evict"' in body


def test_件数はヒントに出す():
    i = SRC.index("def paint_hoju_badge")
    body = SRC[i:i + 1400]
    assert "set_tip(" in body


def test_押すべき時だけ青():
    """色が「今押すといい」の合図。件数が0なら黒のまま."""
    i = SRC.index("def paint_hoju_badge")
    body = SRC[i:i + 1400]
    assert '"#0066cc" if act_kind.get(kind) else "black"' in body


def test_ヒントは後から差し替えられる():
    """件数は起動後に数えるので、固定文では出せない."""
    i = SRC.index("def _attach_tip")
    body = SRC[i:i + 1600]
    assert "def set_text" in body and "return set_text" in body


# ── 一番くじも件数を出す (2026-08-22 ユーザー要望) ──────────────────────

def test_一番くじにも件数の印がある():
    for b in ("kuji_search", "kuji_confirm"):
        assert '"badge": "%s"' % b in SRC


def test_一番くじの件数を同じ集計で数える():
    """★片方が転んでも もう片方のヒントは出す (PSA/🌱 と同じ作り)."""
    i = SRC.index("import ichibankuji_restock as KJ")
    assert "d['kuji']=KJ.count_workload()" in SRC[i:i + 200]
    assert "d['kuji']={'error'" in SRC[i:i + 400]


def test_一番くじの夜間は自動が動いていれば黒():
    """★2026-09-03: 夜間検索は run_kuji_night.py が **毎晩** 回るようになったので、
    自動が動いている限り朝に押す合図を出さない。

    ただし **夜が止まった日は誰も減らさない**ので、その日は青に戻す
    (黒のままだと自動が転んだことに気づけず、溜まり続ける)。"""
    assert '"kuji_search": bool((kj.get("search") or {}).get("can")) and not _auto' in SRC


def test_目視0件なら次に何をするか書く():
    """0件とだけ出ると、何をすればいいのか分からない."""
    assert "先に slice2 (夜間検索) を回してください" in SRC


def test_前回値が無い種類は空欄にしない():
    """★2026-08-22: 一番くじのボタンを足した日、前回値に無いので **何も出なかった**。
    「更新押したら、出たわ」= 押すまで分からない状態だった。"""
    i = SRC.index("def show_cached_hoju_badge")
    body = SRC[i:i + 1200]
    assert "まだ数えていません" in body
    assert "for _b, _base, kind" in body, "前回値の側だけを見ている (新しい種類が漏れる)"


def test_一番くじの補URLボタンは2つだけ():
    """★2026-08-22: slice3 を既存の `hoju` に向け直した結果、
    「🎴一番くじ 補URL補充(目視)」と **同じコマンドのボタンが2つ**になった。
    同じ物が2つあると、どちらを押せばいいか分からない (ユーザー指摘で撤去)。"""
    # (撤去の経緯はコメントに残してあるので、**ラベル定義**が無いことを見る)
    assert '"label": "🎴一番くじ 補URL補充(目視)"' not in SRC
    import re
    n = len(re.findall(r'"ichibankuji_restock\.py", "hoju", "10"', SRC))
    assert n == 1, "hoju を呼ぶボタンが %d 個ある" % n
