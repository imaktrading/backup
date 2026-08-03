# -*- coding: utf-8 -*-
"""同じ現物を二度出品しないガード (2026-08-03).

実害 (2026-08-03 19:42 の走行):
  CSV 6件中3件が重複していた。うち2件は **同一の PSA cert が既に eBay 出品中**
  (cert 152687775 → itemID 358853881133 / cert 158452544 → 358794594782)。
  現物は1枚しかないので、二度出せば片方は必ず履行できない (= キャンセル → Defect Rate)。

なぜ素通りしたか:
  抽出段の除外が `key_v and key_v in _listed` = **KEY が空なら通す fail-OPEN** だった。
  さらに KEY は表記が揺れる:
    - namespace prefix の有無  : `FB08-121_p1` / `dragonball_scg:FB08-121_p1`
    - 同一カードに別 product_id: catalog が EN源(bandai_tcg_plus) と JP源(opcg_official)
      を別 product_id で持ち、`alias_of` は 94,158行中 243行 (0.26%) しか埋まっていない
  → **KEY 一致に頼る限り漏れる**。cert は揺れないので cert で止めるのが最も硬い。

シート実測 (1,580行): 同一cert が「出品済 + 未出品」で併存 24件 / うち KEY 不一致 21件。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from sheet_io import (already_listed_reason, listed_certs, listed_key_forms,  # noqa: E402
                      normalize_key, PRODUCT_COL_CATEGORY, PRODUCT_COL_CERT,
                      PRODUCT_COL_ITEMID, PRODUCT_COL_KEY)

HEADER = ["URL", "itemID", "title"]


def _row(itemid="", key="", cert="", category="TCG", ncols=36):
    r = [""] * ncols
    r[PRODUCT_COL_ITEMID] = itemid
    r[PRODUCT_COL_KEY] = key
    r[PRODUCT_COL_CERT] = cert
    r[PRODUCT_COL_CATEGORY] = category
    return r


class TestNormalizeKey:
    def test_namespace_prefix_is_ignored_for_comparison(self):
        assert normalize_key("dragonball_scg:FB08-121_p1") == normalize_key("FB08-121_p1")

    def test_case_and_space_are_ignored(self):
        assert normalize_key("  One_Piece_TCG:OP09-020 ") == normalize_key("one_piece_tcg:OP09-020")

    def test_url_keys_are_not_comparable(self):
        """item:/shops: は catalog-backed でない固有id。KEY として突き合わせない."""
        assert normalize_key("item:m12345") == ""
        assert normalize_key("shops:abc") == ""

    def test_empty(self):
        assert normalize_key("") == "" and normalize_key(None) == ""

    def test_variant_suffix_is_kept(self):
        """★_PARA と base は **別のカード**。ここを畳むと出品対象を勝手に絞ることになる."""
        assert normalize_key("FB08-121_PARA") != normalize_key("FB08-121")


class TestListedCerts:
    def test_only_rows_with_itemid_count_as_listed(self):
        rows = [HEADER,
                _row(itemid="358853881133", cert="152687775"),   # 出品済
                _row(itemid="", cert="999999999")]               # 未出品
        assert listed_certs(rows) == {"152687775"}

    def test_short_rows_do_not_crash(self):
        assert listed_certs([HEADER, ["a", "b"]]) == set()

    def test_blank_cert_is_ignored(self):
        assert listed_certs([HEADER, _row(itemid="358", cert="")]) == set()

    def test_non_tcg_rows_are_excluded(self):
        """★I列は PSA cert 専用ではない。montbell は同じ列に **型番** を入れている.

        実データ (2026-08-03): `1103247` = O.D.アノラックの型番が3行で共有され、
        1行が出品済。型番は「同じ現物」を意味しない (在庫のある通常商品) ので、
        カテゴリを見ずに止めると **別商品の出品を潰す**。
        """
        rows = [HEADER,
                _row(itemid="356816799540", cert="1103247", category="アウトドア・ジャケット"),
                _row(itemid="358853881133", cert="152687775", category="TCG")]
        assert listed_certs(rows) == {"152687775"}, "montbell 型番を cert 扱いしない"

    def test_categories_none_means_all(self):
        rows = [HEADER, _row(itemid="1", cert="1103247", category="アウトドア・ジャケット")]
        assert listed_certs(rows, categories=None) == {"1103247"}


class TestAlreadyListedReason:
    #: 2026-08-03 の実データ (cert は同じ / KEY だけ食い違う)
    REAL = [HEADER,
            _row(itemid="358853881133", cert="152687775", key="one_piece_tcg:OP09-020"),
            _row(itemid="358794594782", cert="158452544", key="FB08-121_p1"),
            _row(itemid="", cert="152687775", key="one_piece_tcg:OP09-020_PRB02"),
            _row(itemid="", cert="158452544", key="dragonball_scg:FB08-121_PARA")]

    def _sets(self, rows=None):
        rows = rows or self.REAL
        return listed_certs(rows), listed_key_forms(rows)

    def test_same_cert_is_blocked_even_when_key_differs(self):
        """★本命: KEY が変わっても現物は同じ。今日すり抜けた2件がこれ."""
        c, k = self._sets()
        assert already_listed_reason("152687775", "one_piece_tcg:OP09-020_PRB02", c, k) == "cert"
        assert already_listed_reason("158452544", "dragonball_scg:FB08-121_PARA", c, k) == "cert"

    def test_same_cert_is_blocked_even_when_key_is_blank(self):
        """旧実装の fail-OPEN 経路 (シート実測 24件中 21件がこれ)."""
        c, k = self._sets()
        assert already_listed_reason("152687775", "", c, k) == "cert"

    def test_same_key_is_blocked_across_namespace_prefix(self):
        """cert 違い(=別の現物)でも同じカードの2枚目は従来どおり止める."""
        c, k = self._sets()
        assert already_listed_reason("111111111", "dragonball_scg:FB08-121_p1", c, k) == "key"

    def test_new_card_passes(self):
        c, k = self._sets()
        assert already_listed_reason("137215176", "pokemon_tcg:S-P-324", c, k) == ""

    def test_blank_cert_and_blank_key_passes(self):
        """情報が無い行まで止めると出品対象を勝手に絞ることになる (fail-closed の行き過ぎ)."""
        c, k = self._sets()
        assert already_listed_reason("", "", c, k) == ""

    def test_url_key_does_not_collide(self):
        """item: 系は固有idなので、他の item: 行と衝突させない."""
        rows = [HEADER, _row(itemid="358", cert="", key="item:m111")]
        c, k = self._sets(rows)
        assert already_listed_reason("", "item:m222", c, k) == ""

    def test_cert_wins_over_key(self):
        """両方該当なら cert (= より重い「現物の二重出品」) を理由に返す."""
        c, k = self._sets()
        assert already_listed_reason("152687775", "one_piece_tcg:OP09-020", c, k) == "cert"

    def test_empty_sets_are_safe(self):
        assert already_listed_reason("1", "k", None, None) == ""
