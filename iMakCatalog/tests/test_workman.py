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


# ============================================================================
# 2026-05-17 追加: sku_matrix dedup / size_chart parser / color_en 英訳
# ============================================================================
class TestAjaxParserMultiGroupColor(unittest.TestCase):
    """AJAX response の block-select-size-detail group が複数 (= color 別) の場合、
    各 group の色を正確に紐付け + (color,size) 重複なし.
    """

    def test_group_based_color_attribution(self):
        # 2 colors × 違う size 数 (color 0 = 2 sizes, color 1 = 3 sizes)
        fixture = """
<div class="block-variation block-color">
  <div class="block-variation--item-list block-color--item-list js-color-select">
    <dl class="block-variation--item block-color--item" title="ブラック">
      <dt><figure><img src="/img/goods/C/35840_c1.jpg" alt="ブラック"></figure></dt>
      <dd><span>ブラック</span></dd>
    </dl>
    <dl class="block-variation--item block-color--item" title="グリーン">
      <dt><figure><img src="/img/goods/C/35840_c2.jpg" alt="グリーン"></figure></dt>
      <dd><span>グリーン</span></dd>
    </dl>
  </div>
</div>
<div class="block-select-size js-select-size">
  <div class="block-select-size-detail js-variation-size">
    <div class="block-select-size-detail--item block-pattern">
      <div class="block-pattern--size-text">Ｓ</div>
      <a href="?sku=2300035840014">stock</a>
    </div>
    <div class="block-select-size-detail--item block-pattern no-stock">
      <div class="block-pattern--size-text">Ｍ</div>
      <a href="?sku=2300035840021">stock</a>
    </div>
  </div>
  <div class="block-select-size-detail js-variation-size">
    <div class="block-select-size-detail--item block-pattern">
      <div class="block-pattern--size-text">Ｓ</div>
      <a href="?sku=2300035840151">stock</a>
    </div>
    <div class="block-select-size-detail--item block-pattern">
      <div class="block-pattern--size-text">Ｍ</div>
      <a href="?sku=2300035840168">stock</a>
    </div>
    <div class="block-select-size-detail--item block-pattern">
      <div class="block-pattern--size-text">Ｌ</div>
      <a href="?sku=2300035840175">stock</a>
    </div>
  </div>
</div>
"""
        result = workman._parse_ajax_response(fixture, "2300035840090", "T0")
        # color 紐付け確認: 最初の 2 件は ブラック、後 3 件は グリーン
        sm = result["sku_matrix"]
        self.assertEqual(len(sm), 5)
        self.assertEqual(sm[0]["color_jp"], "ブラック")
        self.assertEqual(sm[1]["color_jp"], "ブラック")
        self.assertEqual(sm[2]["color_jp"], "グリーン")
        self.assertEqual(sm[3]["color_jp"], "グリーン")
        self.assertEqual(sm[4]["color_jp"], "グリーン")
        # dedup: 同 (color, size) なし
        combos = set((m["color_jp"], m["size_normalized"]) for m in sm)
        self.assertEqual(len(combos), 5)


class TestSizeChartParser(unittest.TestCase):
    """fetch_size_chart parser + 正規化."""

    def test_normalize_chart_value(self):
        self.assertEqual(workman._normalize_chart_value("76-84"), "76-84")
        self.assertEqual(workman._normalize_chart_value("７６〜８４"), "76-84")  # 全角
        self.assertEqual(workman._normalize_chart_value("100 cm"), "100")
        self.assertEqual(workman._normalize_chart_value("100センチ"), "100")
        self.assertEqual(workman._normalize_chart_value("-"), "")
        self.assertEqual(workman._normalize_chart_value(""), "")

    def test_extract_cells(self):
        row = "<tr><th>ウエスト</th><td>76-84</td><td>84-92</td></tr>"
        cells = workman._extract_cells(row)
        self.assertEqual(cells, ["ウエスト", "76-84", "84-92"])


class TestColorEnglishCoverage(unittest.TestCase):
    """全 集約 entry の color_variants で color_en が英訳済か (= ja 残ゼロ)."""

    def test_color_en_no_jp_residual(self):
        conn = sqlite3.connect(str(api._DB_PATH))
        conn.row_factory = sqlite3.Row
        bad = []
        for r in conn.execute("""SELECT product_id, specs FROM products WHERE category='workman'
                                 AND product_id LIKE 'workman:series:%'""").fetchall():
            s = json.loads(r["specs"] or "{}")
            for cv in s.get("color_variants", []):
                ce = cv.get("color_en", "")
                # ASCII alpha 含まない (= 英訳されてない)
                if not any(c.isascii() and c.isalpha() for c in ce):
                    bad.append((r["product_id"], cv.get("color_jp"), ce))
        conn.close()
        if bad:
            msg = f"color_en untranslated: {len(bad)} 件\n"
            for pid, cj, ce in bad[:10]:
                msg += f"  {pid}: jp={cj!r} en={ce!r}\n"
            self.fail(msg)


class TestSkuMatrixDedup(unittest.TestCase):
    """catalog 内 集約 entry で同 (color_jp, size_normalized) 重複なしを保証."""

    def test_no_duplicate_combos(self):
        conn = sqlite3.connect(str(api._DB_PATH))
        conn.row_factory = sqlite3.Row
        bad = []
        for r in conn.execute("""SELECT product_id, specs FROM products WHERE category='workman'
                                 AND product_id LIKE 'workman:series:%'""").fetchall():
            s = json.loads(r["specs"] or "{}")
            seen = set()
            for m in s.get("sku_matrix", []):
                key = (m.get("color_jp", ""), m.get("size_normalized", ""))
                if key in seen:
                    bad.append((r["product_id"], key, m.get("variant_sku_mpn")))
                seen.add(key)
        conn.close()
        if bad:
            msg = f"sku_matrix duplicates: {len(bad)} 件\n"
            for pid, key, mpn in bad[:10]:
                msg += f"  {pid}: {key} mpn={mpn}\n"
            self.fail(msg)


if __name__ == "__main__":
    unittest.main()
