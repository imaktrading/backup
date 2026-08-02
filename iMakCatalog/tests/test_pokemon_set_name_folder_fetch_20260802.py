"""Pokemon `set_name_official` folder-fetch (Phase 1) 回帰 test.

依頼: `2026-08-02_pokemon_set_name_official_316_setcode_fetch_response.md` §A/C
判定: ① 誤 / ② 正 → ①だけ直す (草案 & 窓口確定)

対象:
  - `_pokemon_set_name_official_folder_fetch.py` の folder 分類 / 除外 / 代表選定
  - `pokemon_tcg._parse_detail_html` の regex fallback に "強化拡張パック「X」" 先出しが
    入っていること (Finding 6, SM9a-067 型の regression 防止)

fixture は実 DB に依存せず (in-memory sqlite) / 実 fetch なし。
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO.parent))
sys.path.insert(0, str(_REPO))

from iMakCatalog.scrapers import pokemon_set_name_official_folder_fetch as _fetch  # noqa: E402
from iMakCatalog.scrapers.pokemon_tcg import _parse_detail_html  # noqa: E402


# ============================================================================
# in-memory DB helpers
# ============================================================================
def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            product_id TEXT NOT NULL,
            name TEXT NOT NULL,
            set_name_official TEXT,
            specs TEXT NOT NULL,
            images TEXT,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(category, product_id)
        )
    """)
    return conn


def _insert(conn, product_id, folder, cardID, set_name_official=None, name="X"):
    """Insert a fixture row with image URL matching /large/{folder}/{cardID}_*.jpg."""
    img_url = f"https://www.pokemon-card.com/assets/images/card_images/large/{folder}/{cardID}_p.jpg"
    conn.execute(
        "INSERT INTO products (category, product_id, name, set_name_official, "
        "specs, images, source, created_at, updated_at) VALUES "
        "('pokemon_tcg', ?, ?, ?, '{}', ?, 'test', '2026-01-01', '2026-01-01')",
        (product_id, name, set_name_official, json.dumps([img_url])),
    )


# ============================================================================
# folder 抽出
# ============================================================================
class TestFolderExtraction(unittest.TestCase):

    def test_folder_from_image_url_simple(self):
        j = json.dumps(["https://www.pokemon-card.com/assets/images/card_images/large/SV1a/042966_p.jpg"])
        self.assertEqual(_fetch._folder_of_image(j), "SV1a")

    def test_folder_from_image_url_dashed_folder(self):
        # BW1-Bb / S8a-G / XY11-Br 等の dual-release/multi-variant folder
        j = json.dumps(["https://www.pokemon-card.com/assets/images/card_images/large/BW1-Bb/027101_p.jpg"])
        self.assertEqual(_fetch._folder_of_image(j), "BW1-Bb")

    def test_folder_empty_when_no_folder_in_path(self):
        # /large//XXX_p.jpg (SL/BW-P 等 folder 無しラベル画像) → 空文字列
        j = json.dumps(["https://www.pokemon-card.com/assets/images/card_images/large//012345_p.jpg"])
        self.assertEqual(_fetch._folder_of_image(j), "")

    def test_folder_none_when_no_images(self):
        self.assertEqual(_fetch._folder_of_image(None), "")
        self.assertEqual(_fetch._folder_of_image("[]"), "")

    def test_cardid_extract_zero_padded(self):
        # 5桁ゼロパディング (公式 cardID) をそのまま取る
        j = json.dumps(["https://www.pokemon-card.com/assets/images/card_images/large/SD/038273_p.jpg"])
        self.assertEqual(_fetch._cardid_of_image(j), "038273")


# ============================================================================
# folder 分類 (single / all_null / multi / no_folder)
# ============================================================================
class TestClassifyFolders(unittest.TestCase):

    def test_dual_release_pack_stays_separate(self):
        """BW1 が product_id 群として集約されても image folder では BW1-Bb / BW1-Bw に
        分離されているため multi にならない (窓口回答書 §A の中核)."""
        conn = _make_conn()
        _insert(conn, "BW1-Bb-001", "BW1-Bb", "027101", "拡張パック「ブラックコレクション」")
        _insert(conn, "BW1-Bb-002", "BW1-Bb", "027102", "拡張パック「ブラックコレクション」")
        _insert(conn, "BW1-Bw-001", "BW1-Bw", "027201", "拡張パック「ホワイトコレクション」")
        idx = _fetch.build_folder_index(conn)
        cls = _fetch.classify_folders(idx)
        # 2 folder / 各 single
        self.assertIn("BW1-Bb", cls["single"])
        self.assertIn("BW1-Bw", cls["single"])
        self.assertNotIn("BW1-Bb", cls["multi"])
        self.assertNotIn("BW1-Bw", cls["multi"])

    def test_multi_value_folder_detected(self):
        """SMP のように同 folder 内に複数商品が同居する folder は multi 判定."""
        conn = _make_conn()
        _insert(conn, "SMP-001", "SMP", "030001", "拡張パック「フルメタルウォール」")
        _insert(conn, "SMP-002", "SMP", "030002", "拡張パック「ダブルブレイズ」")
        idx = _fetch.build_folder_index(conn)
        cls = _fetch.classify_folders(idx)
        self.assertIn("SMP", cls["multi"])
        self.assertNotIn("SMP", cls["single"])

    def test_all_null_folder_detected(self):
        conn = _make_conn()
        _insert(conn, "SD-001", "SD", "038273", None)
        _insert(conn, "SD-002", "SD", "038274", None)
        idx = _fetch.build_folder_index(conn)
        cls = _fetch.classify_folders(idx)
        self.assertIn("SD", cls["all_null"])

    def test_no_folder_bucket(self):
        """image URL に folder が無い行 (/large//XXX_p.jpg 型) は no_folder に集約."""
        conn = _make_conn()
        _insert(conn, "S-P-001", "", "010001", "プロモカードパック 25th ANNIVERSARY edition")
        idx = _fetch.build_folder_index(conn)
        cls = _fetch.classify_folders(idx)
        self.assertIn("", cls["no_folder"])


# ============================================================================
# Phase 1 対象 = single + (all_null - 5 deck)
# ============================================================================
class TestPhase1TargetFolders(unittest.TestCase):

    def test_excludes_5_deck_folders(self):
        """deck 5 folder (SD/SVD/SVM/SMH/SGG) は all-NULL であっても Phase 1 対象から除外."""
        conn = _make_conn()
        for f in ("SD", "SVD", "SVM", "SMH", "SGG"):
            _insert(conn, f"{f}-001", f, "099999", None)
        _insert(conn, "SV1a-001", "SV1a", "042966", "拡張パック「トリプレットビート」")
        idx = _fetch.build_folder_index(conn)
        target = _fetch.phase1_target_folders(idx)
        for f in ("SD", "SVD", "SVM", "SMH", "SGG"):
            self.assertNotIn(f, target, f"deck folder {f} must be excluded from Phase 1")
        self.assertIn("SV1a", target)

    def test_excludes_multi_value_folders(self):
        conn = _make_conn()
        _insert(conn, "SMP-001", "SMP", "030001", "拡張パック「A」")
        _insert(conn, "SMP-002", "SMP", "030002", "拡張パック「B」")
        _insert(conn, "SV1a-001", "SV1a", "042966", "拡張パック「トリプレットビート」")
        idx = _fetch.build_folder_index(conn)
        target = _fetch.phase1_target_folders(idx)
        self.assertNotIn("SMP", target)
        self.assertIn("SV1a", target)

    def test_excludes_empty_no_folder_bucket(self):
        """image URL に folder が無い行群 ('' key) は Phase 1 対象外."""
        conn = _make_conn()
        _insert(conn, "no-folder-1", "", "099998", "何か")
        _insert(conn, "SV1a-001", "SV1a", "042966", "拡張パック「トリプレットビート」")
        idx = _fetch.build_folder_index(conn)
        target = _fetch.phase1_target_folders(idx)
        self.assertNotIn("", target)
        self.assertIn("SV1a", target)

    def test_includes_all_null_non_deck(self):
        """SD 以外の all-NULL folder は Phase 1 対象 (公式が値を持てば埋められる)."""
        conn = _make_conn()
        _insert(conn, "NEWFOLDER-001", "NEWFOLDER", "099997", None)
        idx = _fetch.build_folder_index(conn)
        target = _fetch.phase1_target_folders(idx)
        self.assertIn("NEWFOLDER", target)


# ============================================================================
# 代表 cardID 選定
# ============================================================================
class TestRepresentativeCardIDPick(unittest.TestCase):

    def test_pick_smallest_product_id(self):
        """安定順で最小 product_id の cardID を代表として返す."""
        conn = _make_conn()
        _insert(conn, "SV1a-005", "SV1a", "042970", "拡張パック「トリプレットビート」")
        _insert(conn, "SV1a-001", "SV1a", "042966", "拡張パック「トリプレットビート」")
        _insert(conn, "SV1a-010", "SV1a", "042975", "拡張パック「トリプレットビート」")
        idx = _fetch.build_folder_index(conn)
        cid = _fetch.pick_representative_cardid(idx, "SV1a")
        self.assertEqual(cid, "042966")

    def test_returns_none_when_no_cardID(self):
        conn = _make_conn()
        # image に folder はあるが cardID が抽出できない fixture (image=empty)
        conn.execute(
            "INSERT INTO products (category, product_id, name, set_name_official, "
            "specs, images, source, created_at, updated_at) VALUES "
            "('pokemon_tcg', 'X-001', 'X', NULL, '{}', NULL, 't', '2026-01-01', '2026-01-01')"
        )
        idx = _fetch.build_folder_index(conn)
        self.assertIsNone(_fetch.pick_representative_cardid(idx, "MISSING"))


# ============================================================================
# fallback regex に "強化拡張パック「X」" 先出し (Finding 6, SM9a-067 型)
# ============================================================================
class TestKyokaKakuchouRegexFallback(unittest.TestCase):
    r"""SubSection が無い古い HTML でも "強化拡張パック「X」" が拾えること.

    Finding 6: `|` の順序で「強化拡張」を先に試すことで、SM9a-067 型 (公式値
    「強化拡張パック「バトルリージョン」」) を拾える。
    旧 regex は `拡張パック\s*「[^」]+」` 単独だったため「強化」を落として
    「拡張パック「バトルリージョン」」になっていた。
    """

    def _wrap_no_subsection(self, body):
        return f"""<html><body>
          <h1>テスト</h1>
          <img src="/assets/images/card_images/large/TEST/00001_p.jpg"/>
          {body}
        </body></html>"""

    def test_kyoka_kakuchou_pack_takes_precedence_over_kakuchou_pack(self):
        # SubSection なし → regex fallback へ. 「強化」を落とさない
        html = self._wrap_no_subsection(
            '<div>これは強化拡張パック「バトルリージョン」に収録されるカードです</div>'
        )
        out = _parse_detail_html(html, card_id="1")
        self.assertIsNotNone(out)
        self.assertEqual(
            out.get("set_name_official"),
            "強化拡張パック「バトルリージョン」",
        )

    def test_plain_kakuchou_pack_still_works(self):
        html = self._wrap_no_subsection(
            '<div>拡張パック「シャイニースターV」に収録</div>'
        )
        out = _parse_detail_html(html, card_id="2")
        self.assertEqual(out.get("set_name_official"), "拡張パック「シャイニースターV」")

    def test_subsection_still_wins_over_fallback_regex(self):
        # SubSection に "強化拡張パック「X」" があれば SubSection 優先
        html = f"""<html><body>
          <h1>テスト</h1>
          <img src="/assets/images/card_images/large/TEST/00001_p.jpg"/>
          <section class="SubSection">
            <div class="PopupSub">
              <ul class="List">
                <li class="List_item">強化拡張パック「バトルリージョン」</li>
              </ul>
            </div>
          </section>
          <div>参考: 拡張パック「別のセット」も</div>
        </body></html>"""
        out = _parse_detail_html(html, card_id="3")
        self.assertEqual(
            out.get("set_name_official"),
            "強化拡張パック「バトルリージョン」",
        )


# ============================================================================
# smoke test 5 件が定数として維持されていること (窓口回答書 §C の指定)
# ============================================================================
class TestSmokeTargetsPinned(unittest.TestCase):
    """回答書で指定された 5 件が消えていないことを固定する.

    - SV1a-001 (単値 folder / a接尾辞)
    - SD-001   (deck / all NULL)
    - S8a-001  (multi-product folder の base pack)
    - S8a-G-001 (multi-product folder の別商品)
    - BW1-Bb-001 (dual-release pack の片方)
    """

    def test_smoke_targets_exact_set(self):
        self.assertEqual(
            _fetch.SMOKE_TARGETS,
            ["SV1a-001", "SD-001", "S8a-001", "S8a-G-001", "BW1-Bb-001"],
        )

    def test_deck_folders_pinned(self):
        # Phase 2 で per-card にする 5 deck folder が消えないこと
        self.assertEqual(
            _fetch.DECK_FOLDERS,
            frozenset({"SD", "SVD", "SVM", "SMH", "SGG"}),
        )

    def test_source_tag_pinned(self):
        # 回答書「全 Phase 共通の条件」の source tag
        self.assertEqual(_fetch.SOURCE_TAG, "official_setcode_fetch_20260802")


if __name__ == "__main__":
    unittest.main()
