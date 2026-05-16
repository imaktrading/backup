"""Workman scraper の unit test + catalog 整合性."""
from __future__ import annotations
import json, sqlite3, sys, unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scrapers"))

from scrapers import workman  # noqa
import api  # noqa


class TestHinbanFromFullId(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(workman._hinban_from_full_id("g2300018604015"), "18604")
        self.assertEqual(workman._hinban_from_full_id("g2300035345090"), "35345")
        self.assertEqual(workman._hinban_from_full_id("g2300067171032"), "67171")

    def test_invalid(self):
        self.assertIsNone(workman._hinban_from_full_id(""))
        self.assertIsNone(workman._hinban_from_full_id("g123"))
        self.assertIsNone(workman._hinban_from_full_id("not_g"))


class TestHinbanFromImageUrl(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            workman._hinban_from_image_url("https://workman.jp/img/goods/S/35345_t1.jpg"),
            "35345",
        )
        self.assertEqual(
            workman._hinban_from_image_url("https://workman.jp/img/goods/L/18604_main.jpg"),
            "18604",
        )

    def test_invalid(self):
        self.assertIsNone(workman._hinban_from_image_url(""))
        self.assertIsNone(workman._hinban_from_image_url("https://example.com/foo.jpg"))


class TestWorkmanCatalogIntegrity(unittest.TestCase):
    """catalog 内 workman entry の必須 field を保証."""

    def test_all_have_hinban_and_name(self):
        conn = sqlite3.connect(str(api._DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT product_id, name, specs FROM products WHERE category='workman'")
        bad = []
        for pid, name, sj in cur.fetchall():
            specs = json.loads(sj or "{}")
            if not pid.startswith("workman:"):
                bad.append((pid, "product_id 形式不正"))
            if not specs.get("hinban") and not specs.get("is_series_aggregate"):
                bad.append((pid, "hinban 欠落 (個別 entry)"))
            if not name:
                bad.append((pid, "name 欠落"))
        conn.close()
        if bad:
            msg = "workman entry integrity issues:\n"
            for pid, err in bad[:20]:
                msg += f"  {pid}: {err}\n"
            self.fail(msg)


# ============================================================================
# Phase 2: AJAX parser + 集約 entry + parent_series_id 整合性
# ============================================================================
class TestParentMpnFromUrl(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            workman._parent_mpn_from_url("https://workman.jp/shop/g/g2300067335038/"),
            "2300067335038",
        )

    def test_invalid(self):
        self.assertIsNone(workman._parent_mpn_from_url(""))
        self.assertIsNone(workman._parent_mpn_from_url("https://example.com"))


class TestJpColorToEbay(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(workman._jp_color_to_ebay("ブラック"), "Black")
        self.assertEqual(workman._jp_color_to_ebay("オフホワイト"), "White")
        self.assertEqual(workman._jp_color_to_ebay("ネイビー"), "Blue")
        self.assertEqual(workman._jp_color_to_ebay("チャコール"), "Gray")
        self.assertEqual(workman._jp_color_to_ebay("オレンジ"), "Orange")

    def test_partial_match(self):
        # 「ブラック×ホワイト」のような複合表記 → 最初の match
        self.assertEqual(workman._jp_color_to_ebay("ブラック×ホワイト"), "Black")
        self.assertEqual(workman._jp_color_to_ebay("ブラック：スタンダード"), "Black")

    def test_unknown(self):
        self.assertEqual(workman._jp_color_to_ebay("謎色"), "")
        self.assertEqual(workman._jp_color_to_ebay(""), "")


class TestNormalizeSize(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(workman._normalize_size("Ｓ"), "S")
        self.assertEqual(workman._normalize_size("Ｍ"), "M")
        self.assertEqual(workman._normalize_size("Ｌ"), "L")
        self.assertEqual(workman._normalize_size("ＬＬ"), "LL")
        self.assertEqual(workman._normalize_size("３Ｌ"), "3L")
        self.assertEqual(workman._normalize_size("フリー"), "Free")
        # 半角既存 はそのまま
        self.assertEqual(workman._normalize_size("S"), "S")
        self.assertEqual(workman._normalize_size("LL"), "LL")


class TestAjaxParser(unittest.TestCase):
    """AJAX response HTML 断片 → variation dict 抽出 (fixture ベース)."""

    def test_parse_3color_5size(self):
        # フューチャーテックレインスーツ 67335 を模した最小 fixture
        fixture = """
<div class="block-variation block-color">
  <div class="block-variation--item-list block-color--item-list js-color-select">
    <dl class="block-variation--item block-color--item color-enable-stock" title="ブラック">
      <dt><figure><img src="/img/goods/C/67335_c3.jpg" alt="ブラック"></figure></dt>
      <dd><span>ブラック</span></dd>
    </dl>
    <dl class="block-variation--item block-color--item color-enable-stock" title="グリーン">
      <dt><figure><img src="/img/goods/C/67335_c2.jpg" alt="グリーン"></figure></dt>
      <dd><span>グリーン</span></dd>
    </dl>
  </div>
</div>
<div class="block-select-size js-select-size">
  <div class="block-select-size-detail js-variation-size">
    <div class="block-select-size-detail--item block-pattern no-stock">
      <div class="block-pattern--size-text">Ｓ</div>
      <a href="?goods=2300067335038&sku=2300067335021">stock</a>
    </div>
    <div class="block-select-size-detail--item block-pattern">
      <div class="block-pattern--size-text">Ｍ</div>
      <a href="?goods=2300067335038&sku=2300067335038">stock</a>
    </div>
  </div>
  <div class="block-select-size-detail js-variation-size">
    <div class="block-select-size-detail--item block-pattern">
      <div class="block-pattern--size-text">Ｓ</div>
      <a href="?goods=2300067335038&sku=2300067335120">stock</a>
    </div>
    <div class="block-select-size-detail--item block-pattern no-stock">
      <div class="block-pattern--size-text">Ｍ</div>
      <a href="?goods=2300067335038&sku=2300067335137">stock</a>
    </div>
  </div>
</div>
"""
        result = workman._parse_ajax_response(fixture, "2300067335038", "2026-05-16T20:00:00")
        self.assertEqual(result["representative_hinban"], "67335")
        self.assertEqual(len(result["color_variants"]), 2)
        self.assertEqual(result["color_variants"][0]["color_jp"], "ブラック")
        self.assertEqual(result["color_variants"][0]["ebay_color"], "Black")
        self.assertEqual(result["color_variants"][1]["ebay_color"], "Green")
        self.assertEqual(result["size_variants"], ["S", "M"])
        # sku_matrix: 4 件 (2 color × 2 size)
        self.assertEqual(len(result["sku_matrix"]), 4)
        # 在庫状態 確認
        self.assertFalse(result["sku_matrix"][0]["in_stock"])  # ブラック S = no-stock
        self.assertTrue(result["sku_matrix"][1]["in_stock"])   # ブラック M = in_stock
        # color 紐付け
        self.assertEqual(result["sku_matrix"][0]["color_jp"], "ブラック")
        self.assertEqual(result["sku_matrix"][2]["color_jp"], "グリーン")


class TestPhase2Integrity(unittest.TestCase):
    """catalog 内 workman entry の Phase 2 整合性."""

    def test_individual_entries_have_parent_series_id(self):
        """全 individual entry に parent_series_id があり、それが catalog に存在."""
        conn = sqlite3.connect(str(api._DB_PATH))
        rows = conn.execute("""SELECT product_id, specs FROM products WHERE category='workman'
                               AND product_id NOT LIKE 'workman:series:%'""").fetchall()
        bad = []
        for pid, sj in rows:
            s = json.loads(sj or "{}")
            psid = s.get("parent_series_id")
            if not psid:
                bad.append((pid, "parent_series_id 欠落"))
                continue
            exists = conn.execute(
                "SELECT 1 FROM products WHERE category='workman' AND product_id=?",
                (psid,)).fetchone()
            if not exists:
                bad.append((pid, f"parent_series_id={psid} が catalog に存在せず"))
        conn.close()
        if bad:
            msg = "individual entry parent_series_id issues:\n"
            for pid, err in bad[:20]:
                msg += f"  {pid}: {err}\n"
            self.fail(msg)

    def test_series_aggregates_have_required_fields(self):
        """集約 entry に is_series_aggregate=True + color_variants が存在."""
        conn = sqlite3.connect(str(api._DB_PATH))
        rows = conn.execute("""SELECT product_id, specs FROM products WHERE category='workman'
                               AND product_id LIKE 'workman:series:%'""").fetchall()
        bad = []
        for pid, sj in rows:
            s = json.loads(sj or "{}")
            if not s.get("is_series_aggregate"):
                bad.append((pid, "is_series_aggregate 欠落"))
            if "color_variants" not in s:
                bad.append((pid, "color_variants 欠落"))
            if "size_variants" not in s:
                bad.append((pid, "size_variants 欠落"))
            if "parent_mpn" not in s:
                bad.append((pid, "parent_mpn 欠落"))
        conn.close()
        if bad:
            msg = "series aggregate entry issues:\n"
            for pid, err in bad[:20]:
                msg += f"  {pid}: {err}\n"
            self.fail(msg)

    def test_hinban_all_5digit(self):
        """全 individual entry の hinban が 5 桁以上 (4 桁 bug 再発防止)."""
        conn = sqlite3.connect(str(api._DB_PATH))
        rows = conn.execute("""SELECT product_id, specs FROM products WHERE category='workman'
                               AND product_id NOT LIKE 'workman:series:%'""").fetchall()
        bad = []
        for pid, sj in rows:
            s = json.loads(sj or "{}")
            hb = s.get("hinban", "")
            if len(hb) < 5:
                bad.append((pid, f"hinban={hb!r} < 5 桁"))
        conn.close()
        if bad:
            msg = "hinban length issues:\n"
            for pid, err in bad[:20]:
                msg += f"  {pid}: {err}\n"
            self.fail(msg)


class TestUpdateActiveStatus(unittest.TestCase):
    """api.update_active_status() 動作確認."""

    def test_returns_false_for_unknown(self):
        # 存在しない product_id
        result = api.update_active_status("workman", "workman:series:99999999", False, "test")
        self.assertFalse(result)

    def test_updates_existing(self):
        """既存 entry の is_active_msrp + deactivation_reason を更新."""
        conn = sqlite3.connect(str(api._DB_PATH))
        # 1 件 sample 取得
        row = conn.execute("""SELECT product_id FROM products WHERE category='workman'
                              AND product_id LIKE 'workman:series:%' LIMIT 1""").fetchone()
        conn.close()
        if not row:
            self.skipTest("No workman series aggregate to test")
        pid = row[0]
        # 廃番化
        ok = api.update_active_status("workman", pid, False, "test_inactive")
        self.assertTrue(ok)
        rec = api.lookup("workman", pid)
        self.assertEqual(rec["specs"]["is_active_msrp"], False)
        self.assertEqual(rec["specs"]["deactivation_reason"], "test_inactive")
        # active 復元
        ok2 = api.update_active_status("workman", pid, True)
        self.assertTrue(ok2)
        rec2 = api.lookup("workman", pid)
        self.assertEqual(rec2["specs"]["is_active_msrp"], True)
        self.assertNotIn("deactivation_reason", rec2["specs"])
        # specs の他 field 保護 (color_variants が消えてないか)
        self.assertIn("color_variants", rec2["specs"])
        self.assertGreater(len(rec2["specs"]["color_variants"]), 0)


if __name__ == "__main__":
    unittest.main()
