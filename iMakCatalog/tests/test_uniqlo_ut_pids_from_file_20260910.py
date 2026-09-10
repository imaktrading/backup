# -*- coding: utf-8 -*-
"""外部から貰った品番リストを読む pids_from_file() の回帰テスト (2026-09-10).

回答書 `requests/2026-09-09_ut_supply_urls_for_catalog_response.md`: HQ が仕入元URL
135件 (UNIQLO 105 / GU 30) を渡してきた。元の依頼 (`hq/requests/2026-09-09_..._for_catalog.md`)
は「catalog に無い商品番号があれば、そちらも取りに行きます」だったので、CSV から品番を
拾って `uniqlo_ut_discover.py --pids-file` で確かめられるようにする。

守ること: 同じ CSV に gu-global.com の行が混ざっていても、この scraper (uniqlo_ut) は
**uniqlo.com の行だけ**拾う (GU は別 scraper の担当)。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scrapers"))

import uniqlo_ut_discover as D  # noqa: E402

CSV_SAMPLE = (
    "FLG,item_id,title,supply_url,ebay_url\n"
    "1,357401200653,test1,https://www.uniqlo.com/jp/ja/products/E483933-000/00?"
    "colorDisplayCode=09&sizeDisplayCode=004,https://www.ebay.com/itm/357401200653\n"
    "1,357515407308,test2,https://www.gu-global.com/jp/ja/products/E999999-000/00,"
    "https://www.ebay.com/itm/357515407308\n"
    "1,357448285020,test3,https://www.uniqlo.com/jp/ja/products/E480857-000/00,"
    "https://www.ebay.com/itm/357448285020\n"
)


def test_extracts_uniqlo_pids_only(tmp_path):
    f = tmp_path / "dump.csv"
    f.write_text(CSV_SAMPLE, encoding="utf-8")
    pids = D.pids_from_file(str(f))
    assert pids == {"E483933-000", "E480857-000"}
    assert "E999999-000" not in pids, "gu-global.com の行を拾ってはいけない"


def test_plain_one_per_line_list(tmp_path):
    f = tmp_path / "list.txt"
    f.write_text("E478827-000\nE480694-000\n\nE480696-000\n", encoding="utf-8")
    pids = D.pids_from_file(str(f))
    assert pids == {"E478827-000", "E480694-000", "E480696-000"}


def test_real_hq_dump_yields_the_4_known_missing_pids():
    """実際の依頼書添付CSVを読み、既知の未収録4件が拾えること (回帰の実データ確認)."""
    csv_path = Path("C:/dev/iMak_data/catalog/requests/_uniqlo_gu_supply_urls_dump.csv")
    if not csv_path.exists():
        import pytest
        pytest.skip("依頼書添付CSVが無い環境")
    pids = D.pids_from_file(str(csv_path))
    assert len(pids) == 101, "UNIQLO 側のユニーク品番は101件のはず"
    for missing in ("E478827-000", "E480694-000", "E480696-000", "E480698-000"):
        assert missing in pids
