# -*- coding: utf-8 -*-
"""一番くじの補URL補充を PSA と同じ1画面にする (2026-08-22 ユーザー指示).

「既存と新規でいいとこどりしろ。基本、PSAとは同じ作りで」

いいとこ取りの中身:
  ロジック = 既存のまま (キーワード検索 → 新品/送料込み/セラー評価で絞る →
             夜間キャッシュ → 見送りのクールダウン → 他出品が使用中のURLを掴まない)
  画面     = PSA の確証UI (`psa_resource_confirm.restock_confirm`)

★従来は identify → expand の2段 (1つ選んで、それを種に画像検索) で人が2回見ていた。
  補URLは複数本 貯めるものなので、1画面で複数選ぶ方が合う。
  画像検索の段は落とす (ユーザー判断 2026-08-22)。
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))

import ichibankuji_restock as R                                 # noqa: E402


class TestPSAScreen:
    def test_PSAの確証UIを使う(self):
        assert "restock_confirm" in inspect.getsource(R.pass_hoju_psa_style)

    def test_自前のHTMLは使わない(self):
        src = inspect.getsource(R.pass_hoju_psa_style)
        assert "build_identify_html" not in src and "serve_and_collect" not in src

    def test_画像検索の段は呼ばない(self):
        """★1画面に統一した (ユーザー判断)。2段だと人が2回見ることになる."""
        assert "pass_expand" not in inspect.getsource(R.pass_hoju_psa_style)


class TestKeepsExistingLogic:
    def test_候補は既存の取り方(self):
        """新品/送料込み/セラー評価の絞り込みと夜間キャッシュは既存のまま."""
        assert "_identify_scrape" in inspect.getsource(R.pass_hoju_psa_style)

    def test_書込は既存の口(self):
        """既存の補URLを消さない / 空き枠だけ / 他出品が使用中のURLは掴まない."""
        assert "plan_live_aux" in inspect.getsource(R._write_supplies_live)

    def test_見送りはクールダウンに入れる(self):
        """★同じ候補を翌日また見せない (既存の作法)."""
        assert "_add_cooldown" in inspect.getsource(R.pass_hoju_psa_style)


class TestFailClosed:
    def test_現物が見えない行は目視に出さない(self):
        src = inspect.getsource(R.pass_hoju_psa_style)
        assert "not cands or not ref" in src

    def test_未確定なら書かない(self):
        src = inspect.getsource(R.pass_hoju_psa_style)
        assert "未確定" in src and "選ばれた候補が0件" in src

    def test_URL共有ガードを組めなければ書込を中止(self):
        """判定できないまま書くと、2出品が同じ仕入元を掴む (キャンセル→Defect)."""
        assert "書込を中止" in inspect.getsource(R._write_supplies_live)


class TestButton:
    def test_hojuモードが新しい画面を呼ぶ(self):
        import io
        src = io.open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tools", "ichibankuji_restock.py"),
            encoding="utf-8").read()
        i = src.index('elif mode == "hoju":')
        body = src[i:i + 600]
        assert "pass_hoju_psa_style" in body
        assert "pass_expand" not in body


def test_件数を数えられる():
    """パネルのヒント用。母数ではなく『押して出る件数』."""
    assert hasattr(R, "count_workload")
    src = inspect.getsource(R.count_workload)
    assert "_identify_cache_fresh" in src


# ── 目視画面の材料を増やす (2026-08-22 ユーザー要望) ────────────────────
#
# 「ebay出品の仕入元写真を追加して」
# 「仕入候補に、セラー情報 セラー名、星、評価数、商品の状態、発送までの日数を追加して」

class TestSupplyPhoto:
    def test_今の仕入元をitemsに渡す(self):
        assert "supply_url" in inspect.getsource(R.pass_hoju_psa_style)

    def test_対象に仕入元URLを持たせている(self):
        assert '"supply_url": g(0).strip()' in inspect.getsource(R.get_thin_backup_ichibankuji)

    def test_仕入元はキャッシュに焼かない(self):
        """★仕入元は日々変わる。焼くと古い仕入元を出し続ける (kind と同じ扱い)."""
        src = inspect.getsource(R._identify_scrape)
        assert "supply_url" in src and "cacheに焼かない" in src


class TestSellerInfo:
    def _d(self, **kw):
        base = {"seller": "たろう", "star": 4.9, "reviews": 320,
                "cond": "新品、未使用", "ship_days": "1〜2日で発送"}
        base.update(kw)
        return {"https://x/1": base}

    def test_5項目を並べる(self):
        got = R._cand_for_view({"url": "https://x/1", "price": 3500}, self._d())["name"]
        for w in ("たろう", "★4.9", "評価320", "新品、未使用", "1〜2日で発送"):
            assert w in got, w

    def test_取れていない項目は出さない(self):
        """★空欄を埋めない。無い物を「不明」と書くより出さない."""
        got = R._cand_for_view({"url": "https://x/1", "price": 1},
                               self._d(star=None, ship_days=""))["name"]
        assert "★" not in got and "日で発送" not in got
        assert "たろう" in got

    def test_情報が無くても壊れない(self):
        assert R._cand_for_view({"url": "https://y/9", "price": 1}, {})["name"] == ""


class TestParsers:
    def test_星を取る(self):
        assert R._parse_seller_star("この出品者は5段階評価中4.8") == 4.8
        assert R._parse_seller_star("なし") is None

    def test_発送日数はラベル直後だけ見る(self):
        """★全ページ grep は関連商品を拾う (_parse_cond_ship と同じ理由)."""
        assert R._parse_ship_days("発送までの日数</span><span>1〜2日で発送") == "1〜2日で発送"
        assert R._parse_ship_days("関連商品 4〜7日で発送") == ""


class TestCostAndWidth:
    """★2026-08-22 ユーザー要望「今の仕入値段を出してほしい」
    「価格とか評価とかが見づらいから、横に枠を広げて。今の横幅の1.5倍くらい」。"""

    def test_今の仕入値を渡す(self):
        assert '"cost_now"' in inspect.getsource(R.pass_hoju_psa_style)

    def test_対象に仕入値と出品価格を持たせている(self):
        src = inspect.getsource(R.get_thin_backup_ichibankuji)
        assert '"cost_now": g(13).strip()' in src      # N列
        assert '"price_now": g(12).strip()' in src     # M列

    def test_仕入値はキャッシュに焼かない(self):
        """★値段は日々変わる。焼くと古い値で判断させることになる (kind と同じ扱い)."""
        assert "cost_now" in inspect.getsource(R._identify_scrape)

    def test_画面が広い(self):
        import io as _io
        css = _io.open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "tools", "psa_resource_confirm.py"),
            encoding="utf-8").read()
        assert ".card{width:1350px" in css, "1.5倍に広げていない"
        assert ".card{width:900px" not in css


class TestFilterRestored:
    """★2026-08-22 の実害: 絞り込みは画像検索の段 (pass_expand) の中にしか無く、
    その段を廃止した時に **絞りごと消えた**。新品でない物・評価100未満の個人セラーが
    目視画面に並んだ (ユーザー指摘「新品未使用だけにして、評価100以下も含まれている」)。"""

    # ★2026-09-04: 候補は「今そのまま買える」ことも必須 (buyable)。
    #   f = 中身は完璧だがオークション / g = 買えるか未収録の古いキャッシュ。
    D = {"a": {"cond": "新品、未使用", "ship": "送料込み", "reviews": 320, "buyable": True},
         "b": {"cond": "目立った傷や汚れなし", "ship": "送料込み", "reviews": 320, "buyable": True},
         "c": {"cond": "新品、未使用", "ship": "着払い", "reviews": 320, "buyable": True},
         "d": {"cond": "新品、未使用", "ship": "送料込み", "reviews": 30, "buyable": True},
         "e": {"cond": "新品、未使用", "ship": "送料込み", "reviews": None, "buyable": True},
         "f": {"cond": "新品、未使用", "ship": "送料込み", "reviews": 320, "buyable": False},
         "g": {"cond": "新品、未使用", "ship": "送料込み", "reviews": 320}}

    def _run(self, keys):
        return [x["url"] for x in
                R.filter_by_detail_cache([{"url": k} for k in keys], self.D)]

    def test_新品未使用だけ通す(self):
        assert self._run(["a", "b"]) == ["a"]

    def test_オークションは落とす(self):
        """★2026-09-04: 確定価格で買えないので仕入元にならない。"""
        assert self._run(["f"]) == []

    def test_買えるか未収録は落とす(self):
        """判定できない物を通さない (fail-closed)。取り直せば次から通る。"""
        assert self._run(["g"]) == []

    def test_着払いは落とす(self):
        """実原価が過小表示になる (既存の規約)."""
        assert self._run(["c"]) == []

    def test_評価100未満の個人は落とす(self):
        assert self._run(["d"]) == []

    def test_評価が取れない個人は落とす(self):
        """★判定不能を通すと、評価の無いセラーが素通りする (fail-closed)."""
        assert self._run(["e"]) == []

    def test_キャッシュに無い候補は落とす(self):
        assert self._run(["zzz"]) == []

    def test_Shopsは評価不問(self):
        d = {"https://jp.mercari.com/shops/product/x":
             {"cond": "新品、未使用", "ship": "送料込み", "reviews": None,
              "buyable": True}}
        got = R.filter_by_detail_cache(
            [{"url": "https://jp.mercari.com/shops/product/x"}], d)
        assert len(got) == 1

    def test_目視に出す前に落としている(self):
        src = inspect.getsource(R.pass_hoju_psa_style)
        assert "filter_by_detail_cache" in src
        assert src.index("filter_by_detail_cache") < src.index("restock_confirm")

    def test_落とした件数を出す(self):
        """黙って減らすと「候補が少ない」の理由が分からない."""
        assert "条件で落とした候補" in inspect.getsource(R.pass_hoju_psa_style)
