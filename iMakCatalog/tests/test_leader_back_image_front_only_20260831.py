"""両面カード規約の回帰テスト — catalog は表面 (front) のみ持つ.

依頼: iMak_data/catalog/requests/
      2026-08-09_card_images_leader_back_and_pokemon_missing_response.md
      窓口(HQ) 昇格 §Q1 「案(c) で確定。明文化してください」[IMPLEMENT-GO]

Q1 の実装 (CLAUDE.md への規約追記) は commit 1eef38b で入ったが、規約を守り続ける
回帰テストが無かった。ここで固定する。

守る不変条件:
  A) CLAUDE.md の規約本文が消えていない (指示の解体防止)
  B) catalog に裏面 URL (dbs-cardgame.com の `_b.webp`) が 1件も入っていない
  C) 表面 URL (`_f.webp`) は残っている — 「裏面ゼロ」を両面カード削除で達成していない
  D) bandai-tcg-plus の `_B.png` は **絵柄 variant** であって裏面ではない。
     将来「_b を消す」掃除が入った時に、実在する表面画像を巻き込ませない
  E) 公式 detail の parse が裏面 URL を派生生成しない (派生は listing 側の責務)

ネットワークは使わない。現状の DB と parse ロジックだけを見る。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scrapers"))

import api  # type: ignore  # noqa: E402
import _dbfw_official_local_fetch as DBFW  # type: ignore  # noqa: E402

# 公式が両面カード (LEADER) に付ける表/裏の suffix。裏は catalog に持たない
_DBS_FRONT = re.compile(r"_f\.webp$")
_DBS_BACK = re.compile(r"_b\.webp$")
# bandai-tcg-plus の末尾 _B は「別絵柄 variant」。裏面ではない (混同禁止)
_BANDAI_VARIANT_B = re.compile(r"_B\.(png|jpg)$")

_CLAUDE_MD = _REPO / "CLAUDE.md"


def _all_image_urls():
    """(category, product_id, url) を全件返す."""
    db = sqlite3.connect(str(api._DB_PATH))
    try:
        for cat, pid, imgs in db.execute(
                "SELECT category, product_id, images FROM products"):
            for u in json.loads(imgs or "[]"):
                yield cat, pid, u
    finally:
        db.close()


class TestLeaderBackImageFrontOnly(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.urls = list(_all_image_urls())

    # --- A) 規約本文が消えていない ---------------------------------------

    def test_docs_rule_present(self):
        text = _CLAUDE_MD.read_text(encoding="utf-8")
        self.assertIn(
            "catalog は表面 (front) のみ持つ", text,
            "CLAUDE.md から両面カード規約の本文が消えている (窓口GO §Q1)")
        self.assertIn(
            "画像 (images) の役割分担", text,
            "CLAUDE.md から両面カード規約の節見出しが消えている")

    def test_docs_rule_names_listing_side_as_owner(self):
        """裏面導出の責務が listing 側であることが明記されている."""
        text = _CLAUDE_MD.read_text(encoding="utf-8")
        self.assertRegex(
            text, r"listing 側.*(派生|規則導出)|(派生|規則導出).*listing 側",
            "裏面導出が listing 側の責務である旨が CLAUDE.md から消えている")

    # --- B) 裏面 URL は catalog に無い -----------------------------------

    def test_no_back_face_url_stored(self):
        back = [(c, p, u) for c, p, u in self.urls
                if "dbs-cardgame.com" in u and _DBS_BACK.search(u)]
        self.assertEqual(
            [], back,
            f"裏面 URL (_b.webp) が catalog に入っている: {back[:5]}。"
            "裏面は listing 側で _f→_b 派生する規約 (catalog に持たない)")

    # --- C) 表面 URL は残っている (削除で不変条件を満たしていない) --------

    def test_front_face_urls_still_present(self):
        front = [u for _, _, u in self.urls
                 if "dbs-cardgame.com" in u and _DBS_FRONT.search(u)]
        self.assertGreaterEqual(
            len(front), 50,
            f"両面カードの表面 URL (_f.webp) が {len(front)} 件しかない "
            "(2026-08-31 実測 71 件)。裏面ゼロを両面カード削除で達成していないか確認")

    # --- D) bandai の _B は variant であって裏面ではない -------------------

    def test_bandai_variant_B_suffix_is_not_a_back_face(self):
        """`_B.png` を裏面と誤認して消すと、実在する表面画像を失う."""
        variant = [(c, p, u) for c, p, u in self.urls
                   if "bandai-tcg-plus.com" in u and _BANDAI_VARIANT_B.search(u)]
        self.assertGreaterEqual(
            len(variant), 100,
            f"bandai-tcg-plus の _B 絵柄 variant が {len(variant)} 件 "
            "(2026-08-31 実測 107 件)。裏面掃除で巻き込んで消していないか確認")
        # variant は dbs-cardgame の裏面規約の対象外であることを明示
        for _, _, u in variant:
            self.assertNotIn(
                "dbs-cardgame.com", u,
                f"_B suffix が dbs-cardgame 側に現れた: {u} (裏面規約の再検討が要る)")

    # --- E) parse が裏面 URL を派生生成しない -----------------------------

    def test_parse_detail_html_keeps_front_url_verbatim(self):
        html = (
            '<html><body>'
            '<img class="lazy" data-src="../../images/cards/card/jp/FB09-001_f.webp">'
            '<h1>孫悟空</h1></body></html>'
        )
        out = DBFW.parse_detail_html(html, "FB09-001")
        self.assertEqual(
            "https://www.dbs-cardgame.com/fw/images/cards/card/jp/FB09-001_f.webp",
            out.get("image_url"),
            "公式 img の URL をそのまま保存していない")

    def test_parse_detail_html_emits_no_back_url(self):
        html = (
            '<html><body>'
            '<img class="lazy" data-src="../../images/cards/card/jp/FB09-001_f.webp">'
            '</body></html>'
        )
        out = DBFW.parse_detail_html(html, "FB09-001")
        for k, v in out.items():
            if isinstance(v, str):
                self.assertNotRegex(
                    v, r"_b\.webp",
                    f"parse が裏面 URL を派生生成している ({k}={v!r})。"
                    "派生は listing 側の責務")

    def test_catalog_code_has_no_back_url_derivation(self):
        """catalog 本体コードに _f→_b 変換が無いこと (二重管理を作らない)."""
        pat = re.compile(r"""_f["']\s*,\s*["']_b|_f\.webp["']\s*,\s*["']_b\.webp""")
        hits = []
        for d in ("scrapers", "migrations", "integrations", "tools"):
            for py in (_REPO / d).rglob("*.py"):
                if pat.search(py.read_text(encoding="utf-8", errors="replace")):
                    hits.append(str(py.relative_to(_REPO)))
        self.assertEqual(
            [], hits,
            f"catalog 側に裏面 URL の派生変換がある: {hits}。"
            "裏面導出は listing 側 (post_psa_review / CSV 生成器) の責務")


if __name__ == "__main__":
    unittest.main()
