# -*- coding: utf-8 -*-
"""UT の目視特定 (2026-09-11 ユーザー「PSAと同じように目視で特定させよう」).

メルカリの新品 UT を、カタログの商品に **人が** 当てる。機械は候補を並べるだけ。
- 2026-08-22 ユーザー確定: 機械で商品を確定しない (柄違いが何十種もある)
- 抽出くんの実測 2026-09-11: タグの番号だけで当てると 呪術廻戦 に ポケモンUT が付いた例がある
"""
from __future__ import annotations

import io
import json
import os
import sys

import pytest

_HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_HQ, "tools"))
import ut_identify as U  # noqa: E402


def _p(pid, name="", collab="", fam="", char="", l1="", colors=("WHITE",), sold_out=True, desc=""):
    p = {"pid": pid, "name": name, "collab": collab, "collab_official_name": "",
         "character_family": fam, "character": char, "l1": l1, "gender": "MEN",
         "colors": [{"name": c, "displayCode": "%02d" % i} for i, c in enumerate(colors)],
         "images": [], "sold_out": sold_out}
    p["_tok"] = U._tokens(p)
    p["_desc"] = U.norm(name + desc)
    return p


class TestTokens:
    def test_work_name_only_in_product_name_is_found(self):
        """★呪術廻戦は collab が空で商品名にしか無い (78件中13件が候補なしだった)."""
        assert "呪術廻戦" in _p("A", name="マンガUT 集英社創業100周年 /呪術廻戦")["_tok"]

    def test_generic_words_are_not_tokens(self):
        """★「タグ付き」の「付き」で全商品に当たっていた."""
        t = _p("A", name="すみっコぐらし UT グラフィックTシャツ コンプリートセット（半袖） シーンぬいぐるみ（たぴおかケーキ）付き")["_tok"]
        assert "すみっコぐらし" in t
        assert not any(g in x for x in t for g in ("付き", "グラフィック", "半袖", "セット"))

    def test_part_number_is_dropped_too(self):
        """メルカリは「ジョジョの奇妙な冒険3」の部の番号を書かない."""
        assert "ジョジョの奇妙な冒険" in _p("A", name="グラフィックT ジョジョの奇妙な冒険3")["_tok"]


class TestColor:
    def test_jp_to_catalog(self):
        cs = [{"name": "WHITE"}, {"name": "OFF WHITE"}, {"name": "NAVY"}]
        assert U.pick_color(cs, "ホワイト") == "WHITE"
        assert U.pick_color(cs, "オフホワイト") == "OFF WHITE"
        assert U.pick_color(cs, "ネイビー") == "NAVY"
        assert U.pick_color(cs, "ピンク") == ""
        assert U.pick_color(cs, "") == ""


class TestRank:
    CAT = [_p("POKE1", name="ポケモン UT", collab="ポケモン", desc="ブラッキー"),
           _p("POKE2", name="ポケモン UT", collab="ポケモン", desc="ピカチュウ"),
           _p("JJK", name="マンガUT /呪術廻戦", l1="486159"),
           _p("MARIO", name="マリオ UT", fam="Super Mario")]

    def test_unrelated_products_are_not_listed(self):
        got = U.rank_candidates("UNIQLO UT ポケモン Tシャツ S", "", self.CAT)
        assert {p["pid"] for p in got} == {"POKE1", "POKE2"}

    def test_character_in_title_puts_that_design_first(self):
        got = U.rank_candidates("UNIQLO UT ポケモン ブラッキー Tシャツ", "", self.CAT)
        assert got[0]["pid"] == "POKE1"

    def test_alias_only_lists_candidates(self):
        got = U.rank_candidates("ユニクロ ポケットモンスター UT ピカチュウ", "", self.CAT)
        assert got and got[0]["pid"] == "POKE2"

    def test_tag_number_goes_first_but_is_only_a_candidate(self):
        """番号は先頭に置くだけ。確定は人 (呪術廻戦にポケモンの番号が出た例がある)."""
        got = U.rank_candidates("ポケモン Tシャツ", "", self.CAT, tag_no="486159")
        assert got[0]["pid"] == "JJK" and len(got) == 3

    def test_nothing_matches(self):
        assert U.rank_candidates("海外限定 ジブリ トトロ", "", self.CAT) == []


class TestHarvestHints:
    """抽出くんの POC (2026-09-11): X列=見つけた語 / Y列=タグの番号 を目視の材料に使う."""
    CAT = TestRank.CAT

    def test_keyword_ranks_that_collab_first(self):
        got = U.rank_candidates("UNIQLO UT Tシャツ", "", self.CAT, hint_kw="ポケモン")
        assert {p["pid"] for p in got} == {"POKE1", "POKE2"}

    def test_conflict_is_warned(self):
        """番号が読めた18件中5件で語と食い違った。どちらが正しいかは人が写真で決める."""
        w = U.tag_conflict("486159", "ポケモン", self.CAT)
        assert "食い違う" in w and "呪術廻戦" in w

    def test_conflicting_tag_does_not_jump_to_the_top(self):
        """★POC: 486159 (ポケモン) が無関係の出品に何度も出た。語と食い違う番号では上げない."""
        got = U.rank_candidates("UNIQLO UT ポケモン 呪術廻戦", "", self.CAT,
                                hint_kw="ポケモン", tag_no="486159")
        assert got[0]["pid"] != "JJK"

    def test_matching_tag_is_silent(self):
        assert U.tag_conflict("486159", "呪術廻戦", self.CAT) == ""

    def test_unknown_tag(self):
        assert "カタログに無い" in U.tag_conflict("999999", "ポケモン", self.CAT)

    def test_no_tag(self):
        assert U.tag_conflict("", "ポケモン", self.CAT) == ""


def _row(url, title="t", sold="", price="1650", color="ホワイト", size="M"):
    r = [""] * 36
    r[U.C_URL], r[U.C_TITLE], r[U.C_SOLD], r[U.C_PRICE] = url, title, sold, price
    r[U.C_COND], r[U.C_PHOTOS], r[U.C_DESC] = "新品、未使用", "a.jpg|b.jpg", "desc"
    r[U.C_COLOR], r[U.C_SIZE] = color, size
    r[13], r[34] = "999", "should-not-copy"          # N / KEY
    return r


class TestPending:
    def test_filters(self):
        src = [["hdr"], _row("https://a"), _row("https://b", sold="売"), _row("https://c"),
               _row("https://d"), _row("")]
        got = U.pending_rows(src, decided={"https://c": {}}, in_high={"https://d"})
        assert [r[U.C_URL] for _i, r in got] == ["https://a"]
        assert got[0][0] == 2                       # シートの行番号


class TestHighRow:
    def test_copies_only_safe_columns(self):
        """N (数式) / M (監視くんの列) / KEY は書かない。仕入値は F だけ."""
        h = U.high_row(_row("https://a"))
        assert h[U.C_URL] == "https://a" and h[U.C_PRICE] == "1650" and h[U.C_CAT] == "Tシャツ"
        assert h[U.C_COLOR] == "ホワイト" and h[U.C_SIZE] == "M"
        assert len(h) == U.C_SIZE + 1               # AI (KEY) まで届かない
        assert h[12] == "" and h[13] == ""          # M / N


class TestParse:
    def test_pick_needs_product_and_color(self):
        got = U.parse_result({"picks": [{"idx": 2, "pid": "A", "color": "WHITE"},
                                        {"idx": 3, "pid": "B", "color": ""},
                                        {"idx": "x", "pid": "C", "color": "NAVY"}],
                              "nocat": [4, "y"], "outs": [{"idx": 5, "reason": "used"},
                                                          {"idx": 6, "reason": ""}]})
        assert got["picks"] == [{"idx": 2, "pid": "A", "color": "WHITE"}]
        assert got["nocat"] == [4] and got["outs"] == [{"idx": 5, "reason": "used"}]

    def test_skip_needs_product_color_and_reason(self):
        """一致・見送り (2026-09-12): 商品と色は合っているが出さない。理由必須."""
        got = U.parse_result({"skips": [{"idx": 2, "pid": "A", "color": "WHITE", "reason": "skip_price"},
                                        {"idx": 3, "pid": "A", "color": "WHITE", "reason": ""},
                                        {"idx": 4, "pid": "", "color": "WHITE", "reason": "skip_price"}]})
        assert got["skips"] == [{"idx": 2, "pid": "A", "color": "WHITE", "reason": "skip_price"}]

    def test_reason_lists(self):
        """PSA の理由を流用 (仕入元売り切れ等)。見送りと対象外は混ぜない."""
        assert "gone" in dict(U.OUT_REASONS)
        assert all(k.startswith("skip_") for k, _ in U.SKIP_REASONS)
        assert not any(k.startswith("skip_") for k, _ in U.OUT_REASONS)


class TestSave:
    def _setup(self, tmp_path, monkeypatch, fail=False):
        led = tmp_path / "led.json"
        monkeypatch.setattr(U, "LEDGER", str(led))
        monkeypatch.setattr(U, "load_ledger", lambda path=None: {})
        monkeypatch.setattr(U, "save_ledger",
                            lambda d, path=None: led.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8"))
        monkeypatch.setattr(U, "_high_urls", lambda: set())
        monkeypatch.setattr(U, "load_catalog", lambda db=None: [_p("E1")])
        sent = []
        import sheet_io

        def app(rows, **k):
            if fail:
                raise RuntimeError("quota")
            sent.extend(rows)
            return len(rows)
        monkeypatch.setattr(sheet_io, "append_product_rows", app)
        return led, sent

    ITEMS = [{"idx": 2, "row": _row("https://a"), "cands": []},
             {"idx": 3, "row": _row("https://b"), "cands": []},
             {"idx": 4, "row": _row("https://c"), "cands": []}]

    def test_writes_rows_and_ledger(self, tmp_path, monkeypatch):
        led, sent = self._setup(tmp_path, monkeypatch)
        res = {"picks": [{"idx": 2, "pid": "E1", "color": "WHITE"}], "nocat": [3],
               "outs": [{"idx": 4, "reason": "used"}], "holds": []}
        assert U.save(self.ITEMS, res, now="T") == (1, 3)
        assert [r[U.C_URL] for r in sent] == ["https://a"]
        d = json.loads(led.read_text(encoding="utf-8"))
        assert d["https://a"]["product_id"] == "E1" and d["https://a"]["color"] == "WHITE"
        assert d["https://b"]["decision"] == "nocat" and d["https://c"]["reason"] == "used"

    def test_skip_keeps_identity_but_adds_no_row(self, tmp_path, monkeypatch):
        """★見送りでも特定結果は資産として残す。出品行には足さない."""
        led, sent = self._setup(tmp_path, monkeypatch)
        res = {"picks": [], "skips": [{"idx": 2, "pid": "E1", "color": "WHITE", "reason": "skip_price"}],
               "nocat": [], "outs": [], "holds": []}
        assert U.save(self.ITEMS, res, now="T") == (0, 1) and sent == []
        d = json.loads(led.read_text(encoding="utf-8"))
        assert d["https://a"] == {"decision": "skip", "product_id": "E1", "color": "WHITE",
                                  "reason": "skip_price", "title": "t", "size": "M", "at": "T"}

    def test_sheet_failure_leaves_ledger_untouched(self, tmp_path, monkeypatch):
        """★先に台帳を書くと、シートに入らなかった行が「決着済み」になって二度と出ない."""
        led, _ = self._setup(tmp_path, monkeypatch, fail=True)
        res = {"picks": [{"idx": 2, "pid": "E1", "color": "WHITE"}], "nocat": [], "outs": [], "holds": []}
        with pytest.raises(RuntimeError):
            U.save(self.ITEMS, res, now="T")
        assert not led.exists()

    def test_unknown_product_is_not_written(self, tmp_path, monkeypatch):
        led, sent = self._setup(tmp_path, monkeypatch)
        res = {"picks": [{"idx": 2, "pid": "NOPE", "color": "WHITE"}], "nocat": [], "outs": [], "holds": []}
        assert U.save(self.ITEMS, res, now="T") == (0, 0) and sent == []


class TestColorFilter:
    """★2026-09-12「色が明らかに違うのは、外せないかな」."""

    def test_clearly_different_is_hidden(self):
        assert not U.color_ok(_p("A", colors=("WHITE",)), "ブラック")
        assert U.color_ok(_p("A", colors=("WHITE", "BLACK")), "ブラック")

    def test_near_colors_are_kept(self):
        """出品者の書き方の揺れで正解を隠さない."""
        assert U.color_ok(_p("A", colors=("OFF WHITE",)), "ホワイト")
        assert U.color_ok(_p("A", colors=("NATURAL",)), "ホワイト")
        assert U.color_ok(_p("A", colors=("DARK GRAY",)), "グレー")
        assert U.color_ok(_p("A", colors=("BLUE",)), "ネイビー")

    def test_unknown_is_kept(self):
        assert U.color_ok(_p("A", colors=("WHITE",)), "")
        assert U.color_ok(_p("A", colors=("WHITE",)), "マルチカラー")
        assert U.color_ok(_p("A", colors=()), "ブラック")
        assert U.color_ok(_p("A", colors=("WHITE", "Other")), "ブラック")    # 柄物は判断できない

    def test_hidden_count_is_shown(self):
        it = {"idx": 2, "row": _row("https://a"), "cands": [], "hidden_color": 3}
        assert "3件を隠しました" in U.build_html([it], []).decode("utf-8")


class TestNoKids:
    def test_kids_and_baby_are_not_candidates(self, tmp_path):
        """★2026-09-12「キッズはそもそも対象外だから外さないとね」."""
        import sqlite3
        db = tmp_path / "p.sqlite"
        con = sqlite3.connect(db)
        con.execute("create table products (category, product_id, name, specs, images)")
        for pid, g in (("M", "MEN"), ("K", "KIDS"), ("B", "BABY"), ("GK", "kids"), ("U", "UNISEX")):
            con.execute("insert into products values ('uniqlo_ut', ?, 'ポケモン UT', ?, '[]')",
                        (pid, json.dumps({"gender": g, "collab": "ポケモン"})))
        con.commit()
        con.close()
        got = {p["pid"] for p in U.load_catalog(str(db))}
        assert got == {"M", "U"}


class TestGallery:
    """★2026-09-12「バックプリントもあるから、画像一枚だけだと見逃しちゃう」."""

    def test_all_images_color_main_first_no_chip(self):
        p = _p("E1", l1="482770", colors=("WHITE", "BLACK"))
        base = "https://image.uniqlo.com/UQ/ST3/jp/imagesgoods/482770/"
        p["images"] = [base + "item/jpgoods_00_482770_3x4.jpg", base + "item/jpgoods_01_482770_3x4.jpg",
                       base + "sub/jpgoods_482770_sub3_3x4.jpg", base + "sub/goods_482770_sub14_3x4.jpg",
                       base + "chip/goods_00_482770_chip.jpg"]
        g = U.gallery(p, "BLACK")
        assert g[0].endswith("jpgoods_01_482770_3x4.jpg")          # 選んだ色の表
        assert any("sub14" in u for u in g) and not any("/chip/" in u for u in g)
        assert len(g) == 4

    def test_page_carries_every_photo_for_side_by_side(self):
        p = _p("E1", name="ポケモン UT")
        p["images"] = ["https://x/item/a.jpg", "https://x/sub/b.jpg", "https://x/sub/c.jpg"]
        it = {"idx": 2, "row": _row("https://a"), "cands": [p]}
        html = U.build_html([it], []).decode("utf-8")
        assert "data-imgs=" in html and "data-photos=" in html
        assert "swapImg(" in html and "全部の写真を並べて見比べる" in html


class TestPage:
    def test_page_builds_and_keeps_input_on_send_failure(self):
        it = {"idx": 2, "row": _row("https://a", title="UNIQLO UT ポケモン"), "cands": [_p("E1", name="ポケモン UT")]}
        html = U.build_html([it], []).decode("utf-8")
        assert "E1" in html and "この商品" in html and "カタログに無い" in html
        assert "_sendFailed" in html, "送信失敗を黙らせない (356c396)"
        assert "imak_confirm_draft_ut_identify" in html, "下書きのキーがポート依存だと次回に出ない"

    def test_search_api(self):
        got = U.lookup_api("/api/search", {"q": "ポケモン"}, catalog=[_p("E1", name="ポケモン UT")])
        assert got["n"] == 1 and "E1" in got["html"]
        assert U.lookup_api("/other", {}, catalog=[]) is None


class TestPanel:
    SRC = io.open(os.path.join(_HQ, "control_panel.py"), encoding="utf-8").read()

    def test_button_is_on_the_new_listing_panel(self):
        assert '"ut_identify.py", "--limit=20"' in self.SRC
        i = self.SRC.index("def _ugroup(")
        assert '"ut_identify.py"' in self.SRC[i:i + 1500]

    def test_badge_counts_and_turns_blue(self):
        assert "d['ut_identify']=UI.count_workload()" in self.SRC
        assert '"ut_identify": bool(_ui.get("pending"))' in self.SRC
