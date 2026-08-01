"""Pokemon set_name_official パーサ差替 (regex → SubSection 構造セレクタ) 回帰 test.

依頼: requests/2026-08-01_fix_catalog_data_only_BC_response.md §C-2/C-3 段階1
判定: ① 誤 (NULL 6,533件 / 29.7% / 147 プレフィックス) → パーサを直す = GO

窓口実測 (poke_sample30.json = 30/30 成功) を根拠に、公式 detail HTML の
    <section class="SubSection"><div class="PopupSub"><ul class="List">
      <li class="List_item">TEXT or <a>TEXT</a></li>
から先頭を採る。空/欠落なら既存の 5 regex に fallback、両方空なら NULL (推測しない)。

fixture の HTML 断片は _evidence_20260801_BC/ の実 HTML から特徴部分を抜粋。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))

from iMakCatalog.scrapers.pokemon_tcg import _parse_detail_html  # noqa: E402


def _wrap(inner_body: str, name: str = "テストカード") -> str:
    """_parse_detail_html が返る最低限の骨格 (h1 + image_url) で inner_body を包む."""
    return f"""<html><body>
      <h1>{name}</h1>
      <img src="/assets/images/card_images/large/TEST/00001_p.jpg"/>
      {inner_body}
    </body></html>"""


class TestSubSectionExtraction(unittest.TestCase):
    """新パーサが SubSection から先頭 <li class="List_item"> を採ること."""

    def test_plain_text_li(self):
        # HSZm-014 型: <li class="List_item">TEXT</li> (リンクなし)
        html = _wrap("""
        <section class="SubSection">
          <div class="PopupSub">
            <ul class="List">
<p>              <li class="List_item">ポケモンカードゲームBW はじめてセット 全国図鑑版 （ミジュマルデッキ）</li>
</p>            </ul>
          </div>
        </section>
        """)
        out = _parse_detail_html(html, card_id="1")
        self.assertIsNotNone(out)
        self.assertEqual(
            out.get("set_name_official"),
            "ポケモンカードゲームBW はじめてセット 全国図鑑版 （ミジュマルデッキ）",
        )

    def test_anchor_link_li(self):
        # SVOM-020 型: <li class="List_item"><a>TEXT</a></li>
        html = _wrap("""
        <section class="SubSection">
          <div class="PopupSub">
            <ul class="List">
<p>              <li class="List_item"><a href="/products/sv/svo.html" class="Link Link-arrow">スターターセットex マリィのモルペコ＆オーロンゲex</a></li>
</p>            </ul>
          </div>
        </section>
        """)
        out = _parse_detail_html(html, card_id="2")
        self.assertIsNotNone(out)
        self.assertEqual(
            out.get("set_name_official"),
            "スターターセットex マリィのモルペコ＆オーロンゲex",
        )

    def test_multiple_li_takes_first(self):
        # SVM-001 型: 2 番目以降はシリーズ名 / 購入導線なので捨てる
        html = _wrap("""
        <section class="SubSection">
          <div class="PopupSub">
            <ul class="List">
<p>              <li class="List_item"><a href="/ex/svm/" class="Link Link-arrow">スタートデッキGenerations ピカチュウex・カビゴンex</a></li>

              <li class="List_item"><a href="/ex/svm" class="Link Link-arrow">スタートデッキ Generations</a></li>
</p>            </ul>
          </div>
        </section>
        """)
        out = _parse_detail_html(html, card_id="3")
        self.assertIsNotNone(out)
        self.assertEqual(
            out.get("set_name_official"),
            "スタートデッキGenerations ピカチュウex・カビゴンex",
        )

    def test_double_quote_kakko_and_zenkaku_space_normalized(self):
        # DPP-107 型: 「」 + 全角空白 (　) が半角1つに畳まれる
        html = _wrap("""
        <section class="SubSection">
          <div class="PopupSub">
            <ul class="List">
<p>              <li class="List_item">「ポケモンカードゲームDP　秘境の叫び・怒りの神殿　スペシャルパック」おまけカード</li>
</p>            </ul>
          </div>
        </section>
        """)
        out = _parse_detail_html(html, card_id="4")
        self.assertIsNotNone(out)
        # 全角空白は re.sub(r"\s+", " ", ...) で半角空白 1 つに畳まれる
        self.assertEqual(
            out.get("set_name_official"),
            "「ポケモンカードゲームDP 秘境の叫び・怒りの神殿 スペシャルパック」おまけカード",
        )

    def test_single_quote_daiiku_yamayama(self):
        # LP-032 型: 『 』表記 (現行 regex は「」限定で漏れていた)
        html = _wrap("""
        <section class="SubSection">
          <div class="PopupSub">
            <ul class="List">
<p>              <li class="List_item">『ジム☆チャレンジ』入賞者カード</li>
</p>            </ul>
          </div>
        </section>
        """)
        out = _parse_detail_html(html, card_id="5")
        self.assertIsNotNone(out)
        self.assertEqual(out.get("set_name_official"), "『ジム☆チャレンジ』入賞者カード")


class TestRegexFallback(unittest.TestCase):
    """SubSection が空 / 欠落なら旧 regex 5本に fallback."""

    def test_no_subsection_but_kakuchou_pack_regex_hits(self):
        # SubSection 自体無し / 本文 text に 拡張パック「XXX」がある古い HTML
        html = _wrap("""
        <div>これは拡張パック「シャイニースターV」に収録されるカードです</div>
        """)
        out = _parse_detail_html(html, card_id="6")
        self.assertIsNotNone(out)
        self.assertEqual(out.get("set_name_official"), "拡張パック「シャイニースターV」")

    def test_no_subsection_but_high_class_pack_regex_hits(self):
        html = _wrap("""
        <div>ハイクラスパック「シャイニースターV」から収録。</div>
        """)
        out = _parse_detail_html(html, card_id="7")
        self.assertIsNotNone(out)
        self.assertEqual(out.get("set_name_official"), "ハイクラスパック「シャイニースターV」")

    def test_empty_subsection_falls_back_to_regex(self):
        # SubSection はあるが <li> の中身が空 → regex fallback へ
        html = _wrap("""
        <section class="SubSection">
          <div class="PopupSub">
            <ul class="List">
              <li class="List_item">   </li>
            </ul>
          </div>
        </section>
        <div>拡張パック「フュージョンアーツ」より</div>
        """)
        out = _parse_detail_html(html, card_id="8")
        self.assertIsNotNone(out)
        self.assertEqual(out.get("set_name_official"), "拡張パック「フュージョンアーツ」")


class TestFailClosed(unittest.TestCase):
    """SubSection も regex 5本もヒットしない → set_name_official は None (推測しない)."""

    def test_nothing_matches_stays_none(self):
        html = _wrap("<div>set 情報が全く無い本文</div>")
        out = _parse_detail_html(html, card_id="9")
        self.assertIsNotNone(out)  # name はある
        self.assertIsNone(out.get("set_name_official"))


class TestExistingRegexNotBroken(unittest.TestCase):
    """SubSection が入っている新しい HTML でも、既存で正しく取れていた表記が引き続き通ること."""

    def test_subsection_overrides_regex(self):
        # 本文にも regex hit する 拡張パック「XXX」 があるが、SubSection の値が優先される
        html = _wrap("""
        <section class="SubSection">
          <div class="PopupSub">
            <ul class="List">
              <li class="List_item">「プレミアムトレーナーボックス」</li>
            </ul>
          </div>
        </section>
        <div>参考: 拡張パック「ダブルブレイズ」を含む</div>
        """)
        out = _parse_detail_html(html, card_id="10")
        # SubSection の先頭 li が優先。regex fallback ではない
        self.assertEqual(out.get("set_name_official"), "「プレミアムトレーナーボックス」")


if __name__ == "__main__":
    unittest.main()
