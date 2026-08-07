# -*- coding: utf-8 -*-
"""入稿前に「同一cert が既に出品済」の行を物理除外する (2026-08-03).

なぜ抽出段のガード (test_double_listing_guard_20260803.py) だけでは足りないか:

  1. 抽出段はシートの B列(itemID) を根拠にする。しかし **書き戻しは漏れる**。
     実測 (2026-08-03): live PSA10 627件のうち **35件がシートに itemID を持たない**。
     その35件と同じ cert は「まだ出品していない」に見えるので素通りする。
  2. CSV は抽出段以外の経路 (fork / 手直し / RESTOCK) でも作られる。最終地点で見る必要がある。

そして pre_upload には **同一cert を必ず見逃す設計バグ**があった:
  「自分自身(=同じcert)は除外して突合する」で live index から同一cert を外していたため、
  最も重い「同じ現物の二重出品」だけが常に無検出だった (2026-08-03 の実害2件がこれ)。

守りたいこと:
  - 同一cert = 同じ現物 → **物理除外**する (二度売れたら片方は必ず履行できない)
  - 同一カードの2枚目 → 従来どおり **警告のみ** (仕入元が別なら健全。出品を勝手に絞らない)
"""
from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import dup_guard as dg  # noqa: E402
import sheet_io  # noqa: E402

HEADER = [dg.CSV_LABEL, dg.CSV_TITLE, dg.CSV_CERT]


def _rows():
    return [["PSA10-152687775", "PSA 10 One Piece #OP09-020 Come On", "152687775"],
            ["PSA10-137215176", "PSA 10 Pokemon #324/S-P Lugia V", "137215176"]]


class TestCertsFromSkus:
    def test_extracts_cert_from_custom_label(self):
        assert dg.certs_from_skus({"3588": "PSA10-152687775"}) == {"152687775"}

    def test_ignores_non_psa_skus(self):
        assert dg.certs_from_skus({"1": "m83047742482", "2": "", "3": None}) == set()

    def test_definition_is_shared_with_sheet_io(self):
        """抽出段と入稿前で判定がズレないよう、定義は1本であること."""
        assert dg.certs_from_skus is sheet_io.certs_from_skus


class TestSameCertAlreadyLive:
    def test_detects_row_whose_cert_is_already_listed(self):
        got = dg.same_cert_already_live(_rows(), HEADER, {"152687775"})
        assert [g["cert"] for g in got] == ["152687775"]
        assert got[0]["row"] == 0

    def test_clean_rows_pass(self):
        assert dg.same_cert_already_live(_rows(), HEADER, {"999999999"}) == []

    def test_empty_listed_set_is_safe(self):
        assert dg.same_cert_already_live(_rows(), HEADER, set()) == []
        assert dg.same_cert_already_live(_rows(), HEADER, None) == []

    def test_row_without_cert_is_not_blocked(self):
        """cert が無い行まで止めると出品対象を勝手に絞ることになる."""
        assert dg.same_cert_already_live([["m1", "t", ""]], HEADER, {"152687775"}) == []


class TestStripRows:
    def _csv(self, tmp_path):
        p = tmp_path / "t.csv"
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
            w.writerow(HEADER)
            w.writerows(_rows())
        return str(p)

    def test_rewrites_csv_and_keeps_backup(self, tmp_path, capsys):
        p = self._csv(tmp_path)
        dg._strip_rows(p, HEADER, _rows()[1:])
        with open(p, encoding="utf-8") as f:
            out = list(csv.reader(f))
        assert len(out) == 2 and out[1][0] == "PSA10-137215176"
        assert os.path.exists(p + ".bak_same_cert"), "戻せる形にしてから書き換えること"

    def test_backup_holds_the_original(self, tmp_path):
        p = self._csv(tmp_path)
        dg._strip_rows(p, HEADER, [])
        with open(p + ".bak_same_cert", encoding="utf-8") as f:
            assert len(list(csv.reader(f))) == 3


class TestSelfExclusionNoLongerHidesSameCert:
    """★回帰の本体: 「自分自身は除外」が同一cert を隠していた件."""

    def test_same_cert_is_reported_even_though_index_excludes_self(self):
        # live index からは self_iids として消える cert でも、severe 判定は独立に効く
        severe = dg.same_cert_already_live(_rows(), HEADER, {"152687775"})
        assert severe, "同一cert は self 扱いで消してはいけない"


class TestLiveListedCerts:
    def test_missing_cache_is_empty_not_crash(self, tmp_path):
        assert sheet_io.live_listed_certs(str(tmp_path / "nope.json")) == set()

    def test_reads_skus_from_cache(self, tmp_path):
        import json
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"titles": {}, "skus": {"3588": "PSA10-152687775"}}),
                     encoding="utf-8")
        assert sheet_io.live_listed_certs(str(p)) == {"152687775"}

    def test_old_cache_without_skus_is_empty(self, tmp_path):
        """旧形式 cache でも壊れない (= シート側の判定に素直に戻るだけ)."""
        import json
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"titles": {"1": "t"}}), encoding="utf-8")
        assert sheet_io.live_listed_certs(str(p)) == set()


class TestLiveIsEbayTruthNotSheetSoldColumn:
    """★2026-08-04: D列(仕入元 売切) で live を判定すると live を過小評価する.

    実測: itemID を持つ 1,127行のうち D='○' が 749行、**そのうち 626行は eBay ActiveList
    に居る**(補URL で供給を繋いでいるので出品は生きている)。D列基準だと、その626件が
    「live でない」扱いになり、KEY が完全一致していても重複判定が効かない。
    実害: 8/03 OP07-109 / 8/04 OP05-098_P が素通りして CSV に入った (2日連続)。
    """

    B, D, KEY = dg.B, dg.D, dg.KEY

    def _rows(self):
        def row(iid, sold, key, ncols=36):
            r = [""] * ncols
            r[self.B], r[self.D], r[self.KEY] = iid, sold, key
            return r
        return [["URL", "itemID"],
                row("358833464170", "○", "one_piece_tcg:OP05-098_P"),   # 仕入元売切だが eBay は live
                row("358999999999", "", "one_piece_tcg:OTHER-001")]

    def test_sold_marked_row_is_dropped_without_active_ids(self):
        """従来挙動 (= これが取りこぼしの正体)."""
        index, _ = dg.live_card_index(self._rows())
        assert "one_piece_tcg:OP05-098_P" not in index

    def test_sold_marked_row_counts_as_live_when_ebay_says_so(self):
        index, _ = dg.live_card_index(self._rows(), active_ids={"358833464170"})
        assert index["one_piece_tcg:OP05-098_P"] == ["358833464170"]

    def test_ebay_truth_also_drops_rows_not_in_active_list(self):
        """逆向き: シートが live と言っても eBay に無ければ live ではない."""
        index, _ = dg.live_card_index(self._rows(), active_ids={"358833464170"})
        assert "one_piece_tcg:OTHER-001" not in index

    def test_empty_active_ids_falls_back_to_sheet(self):
        """cache が空の時は従来判定に戻る (悪化させない)."""
        index, _ = dg.live_card_index(self._rows(), active_ids=None)
        assert "one_piece_tcg:OTHER-001" in index


class TestExactKeyIsStrippedTokenIsNot:
    """★2026-08-05: canonical KEY 完全一致は物理除外、タイトル token 一致は残す.

    3日連続で人が手で外していた (8/03 OP07-109 / 8/04 OP05-098_P / 8/05 OP05-060)。
    KEY 完全一致は重複くんが元々落とす対象なので、落とすのは「勝手に絞る」ではない。
    一方 token 一致 (`t:OP05-119`) は **別セットの同番号**を巻き込む:
    実データで `one_piece_tcg:OP05-119`(Awakening/日本語) と
    `OP05-119_PRB01_1`(Premium Booster再録) / `OP05-119_p8`(英語版) は別のカード。
    """

    CANDS = [{"label": "m98445743388", "cert": "157208427",
              "card_key": "one_piece_tcg:OP05-060", "existing": ["358419376373"]},
             {"label": "m11111111111", "cert": "146618418",
              "card_key": "t:OP05-119", "existing": ["358814877732"]}]

    def _split(self, cands):
        exact = [c for c in cands if not str(c.get("card_key", "")).startswith("t:")]
        return exact, [c for c in cands if c not in exact]

    def test_exact_key_match_is_selected_for_removal(self):
        exact, _ = self._split(self.CANDS)
        assert [c["label"] for c in exact] == ["m98445743388"]

    def test_title_token_match_is_kept(self):
        _, weak = self._split(self.CANDS)
        assert [c["label"] for c in weak] == ["m11111111111"], \
            "別セットの同番号を落とすと出品対象を不当に減らす"

    def test_source_strips_only_exact(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "tools", "dup_guard.py"),
                   encoding="utf-8").read()
        assert 'startswith("t:")' in src, "token 一致を除外対象から外す条件が要る"
        assert "pre_upload_stripped_samekey" in src, "除外は台帳に残すこと"


class TestLiveCacheFreshness:
    """★2026-08-07: この cache を **更新する担当が居なかった**.

    control_panel は `--audit --no-refresh` (eBay を叩かない) で呼び、`--pre-upload` は
    cache を読むだけ。8/04-8/06 に cache が最新だったのは **人が手で叩いていたから**。
    古い cache を「今 live」の根拠にすると、
      - 新しく出した listing が cache に無い → 重複を見逃す (直したはずの事故の再来)
      - 終了した listing が cache に残る    → 真新規を誤って落とす
    どちらも黙って起きるので、入稿直前に自分で新鮮さを保証する。
    """

    def _write(self, tmp_path, ts):
        import json
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"generated_at": ts, "titles": {}, "skus": {}}),
                     encoding="utf-8")
        return str(p)

    def test_age_of_fresh_cache_is_small(self):
        from datetime import datetime, timedelta
        now = datetime(2026, 8, 7, 12, 0, 0)
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            import pathlib
            p = self._write(pathlib.Path(d), (now - timedelta(hours=1)).isoformat())
            assert abs(dg.cache_age_hours(p, now) - 1.0) < 0.01

    def test_missing_cache_is_unknown_not_zero(self, tmp_path):
        """無い cache を「0時間前(新鮮)」にすると、黙って古い判定で通ってしまう."""
        assert dg.cache_age_hours(str(tmp_path / "nope.json")) is None

    def test_broken_cache_is_unknown(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text("{ not json", encoding="utf-8")
        assert dg.cache_age_hours(str(p)) is None

    def test_cache_without_timestamp_is_unknown(self, tmp_path):
        import json
        p = tmp_path / "c.json"
        p.write_text(json.dumps({"titles": {}}), encoding="utf-8")
        assert dg.cache_age_hours(str(p)) is None

    def test_stale_threshold_exists(self):
        assert dg.CACHE_MAX_AGE_H > 0

    def test_pre_upload_blocks_when_live_unknown(self, tmp_path, monkeypatch, capsys):
        """判定不能を「重複なし」に倒さない (= CSV を触らず人に返す)."""
        p = tmp_path / "t.csv"
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, quoting=csv.QUOTE_NONNUMERIC)
            w.writerow(HEADER)
            w.writerows(_rows())
        before = open(p, encoding="utf-8").read()
        monkeypatch.setattr(dg.sheet_io, "_product_ws",
                            lambda: type("W", (), {"get_all_values": lambda s: [["h"]]})())
        monkeypatch.setattr(dg, "ensure_fresh_live_cache", lambda *a, **k: ({}, {}, False))
        r = dg.pre_upload(str(p))
        assert r.get("blocked") is True
        assert "⛔" in capsys.readouterr().out
        assert open(p, encoding="utf-8").read() == before, "判定不能なら CSV は触らない"


class TestKeySplitSameCardMonitor:
    """★2026-08-07: catalog の canonical 未統合が **何件の害か** を常設で数える.

    カタログ回答 (2026-08-07): 同じカードが EN源/JP源で別 product_id。`alias_of` は
    G-SHOCK 専用設計で TCG には 0件。統合するには image_phash の backfill + 新スキーマが要る。
    しかし実測すると助かる件は 未出品側 0件 / live どうし 3組(578種) しか無い。
    → **直さない判断**をしたので、増えたら気づけるように毎サイクル数える。
    """

    B, KEY = dg.B, dg.KEY

    def _rows(self, keys):
        def row(iid, key, ncols=36):
            r = [""] * ncols
            r[self.B], r[self.KEY] = iid, key
            return r
        return [["URL", "itemID"]] + [row(i, k) for i, k in keys]

    def test_identity_ignores_variant_suffix_and_namespace(self):
        sc = {("one_piece_tcg", "OP09-020_PRB02"): "PRB02",
              ("one_piece_tcg", "OP09-020_r1"): "PRB02"}
        a = dg.card_identity("one_piece_tcg:OP09-020_PRB02", sc)
        b = dg.card_identity("one_piece_tcg:OP09-020_r1", sc)
        assert a == b == ("OP09-020", "PRB02")

    def test_different_set_is_different_card(self):
        """★ここを畳むと別カードまで重複扱いになる (ST-23版 と PRB-02版)."""
        sc = {("one_piece_tcg", "OP09-020_ST23"): "ST23",
              ("one_piece_tcg", "OP09-020_PRB02"): "PRB02"}
        assert (dg.card_identity("one_piece_tcg:OP09-020_ST23", sc)
                != dg.card_identity("one_piece_tcg:OP09-020_PRB02", sc))

    def test_detects_en_jp_split(self, monkeypatch):
        monkeypatch.setattr(dg, "_setcode_map",
                            lambda: {("one_piece_tcg", "OP09-020_PRB02"): "PRB02",
                                     ("one_piece_tcg", "OP09-020_r1"): "PRB02"})
        rows = self._rows([("1", "one_piece_tcg:OP09-020_PRB02"),
                           ("2", "one_piece_tcg:OP09-020_r1")])
        got = dg.key_split_same_card(rows, {"1": "t", "2": "t"})
        assert len(got) == 1 and got[0]["number"] == "OP09-020"

    def test_unknown_setcode_is_not_counted(self, monkeypatch):
        """セットコードが取れない = 別カードかもしれない。過大に言わない."""
        monkeypatch.setattr(dg, "_setcode_map", lambda: {})
        rows = self._rows([("1", "one_piece_tcg:OP07-085_OP11"),
                           ("2", "one_piece_tcg:OP07-085_p")])
        assert dg.key_split_same_card(rows, {"1": "t", "2": "t"}) == []

    def test_non_live_rows_are_ignored(self, monkeypatch):
        monkeypatch.setattr(dg, "_setcode_map",
                            lambda: {("one_piece_tcg", "OP09-020_PRB02"): "PRB02",
                                     ("one_piece_tcg", "OP09-020_r1"): "PRB02"})
        rows = self._rows([("1", "one_piece_tcg:OP09-020_PRB02"),
                           ("2", "one_piece_tcg:OP09-020_r1")])
        assert dg.key_split_same_card(rows, {"1": "t"}) == []
