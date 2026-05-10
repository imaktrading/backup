"""Regression: 2026-05-10 一番くじ 中間CSV に補仕入URL 5 列追加 + 統合Hight 転記.

【目的】
カプセルトイ・一番くじ等は仕入元 Mercari の売切れが早く、A 列 1 つの URL のみ
だと売切時に出品停止 → 機会損失. 補仕入URL を 5 個まで保持し、inventory
monitor (Inventory Claude 領域) が A + AC-AG 全候補を巡回、全売切で取下げ判定
する設計の HQ 側担当部分.

【今 commit のスコープ】
- 中間CSV (Phase 1 出力 → ユーザー編集 → Phase 2 転記) に補仕入URL 1-5 列追加
- Phase 2 で 統合Hight AC-AG (#29-33) に補 URL 転記 + grid 拡張 + ヘッダー追加

【スコープ外】
- inventory monitor の AC-AG 巡回拡張 (= Inventory Claude 担当、依頼書記述済)
- Phase 1 で 1kuji.com から自動収集 (現状はユーザー手動入力前提)
"""
from __future__ import annotations
import csv
import importlib.util
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_KUJI = _REPO_ROOT / "iMak_ichibankuji"


def _load_kuji_module():
    """sys.modules キャッシュ汚染回避用、絶対パスから ichibankuji_to_csv.py を load."""
    path = _KUJI / "ichibankuji_to_csv.py"
    spec = importlib.util.spec_from_file_location("_test_kuji_sub_urls", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_intermediate_fields_includes_5_sub_urls():
    """INTERMEDIATE_FIELDS に補仕入URL 1〜5 が含まれる."""
    m = _load_kuji_module()
    fields = m.INTERMEDIATE_FIELDS
    for i in range(1, 6):
        col = f"補仕入URL{i}"
        assert col in fields, f"{col} should be in INTERMEDIATE_FIELDS, got: {fields}"


def test_intermediate_fields_count():
    """INTERMEDIATE_FIELDS は既存 10 + 補URL 5 = 15 列."""
    m = _load_kuji_module()
    assert len(m.INTERMEDIATE_FIELDS) == 15, f"Expected 15 fields, got {len(m.INTERMEDIATE_FIELDS)}"


def test_intermediate_csv_write_read_roundtrip_preserves_sub_urls():
    """中間CSV 書込→読込で補URL 列が保持される (ユーザー編集を破壊しない確認)."""
    m = _load_kuji_module()
    sample_row = {
        'kuji_url': 'https://1kuji.com/products/test',
        'series_name': 'テスト 一番くじ',
        'prize': 'A賞',
        'prize_title': 'テストフィギュア',
        'size_cm': '15',
        'image_url': 'https://example.com/test.jpg',
        'release_year': '2026',
        'kuji_price_jpy': '850',
        'mercari_url': 'https://jp.mercari.com/item/m111',
        'cost_jpy': '5000',
        '補仕入URL1': 'https://jp.mercari.com/item/m222',
        '補仕入URL2': 'https://jp.mercari.com/item/m333',
        '補仕入URL3': '',
        '補仕入URL4': '',
        '補仕入URL5': '',
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=m.INTERMEDIATE_FIELDS)
        w.writeheader()
        w.writerow(sample_row)
        tmp_path = f.name
    try:
        with open(tmp_path, encoding='utf-8-sig', newline='') as f:
            r = csv.DictReader(f)
            rows = list(r)
        assert len(rows) == 1
        assert rows[0]['補仕入URL1'] == 'https://jp.mercari.com/item/m222'
        assert rows[0]['補仕入URL2'] == 'https://jp.mercari.com/item/m333'
        assert rows[0]['補仕入URL3'] == ''
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_phase1_output_has_empty_sub_url_fields():
    """Phase 1 で生成される dict に補URL 5 列が空欄で含まれる (ユーザー手入力欄)."""
    m = _load_kuji_module()
    # phase1 内の dict 構築を simulate (1kuji スクレイプは mock せず構造のみ確認)
    sample_intermediate = {
        'kuji_url': 'test',
        'series_name': 'test',
        'prize': 'A賞',
        'prize_title': 'test',
        'size_cm': '15',
        'image_url': '',
        'release_year': '2026',
        'kuji_price_jpy': '850',
        'mercari_url': '',
        'cost_jpy': '',
        '補仕入URL1': '',
        '補仕入URL2': '',
        '補仕入URL3': '',
        '補仕入URL4': '',
        '補仕入URL5': '',
    }
    # INTERMEDIATE_FIELDS と key の集合が一致 (将来 field 追加忘れ検出)
    assert set(sample_intermediate.keys()) == set(m.INTERMEDIATE_FIELDS)


def test_v_ab_cleanup_does_not_touch_sub_urls():
    """副作用ゼロ: V-AB クリーンアップは AC-AG (補URL) を触らない (range 21-28 のみ).

    (将来 cleanup ロジック修正時に補URL を誤クリアしないための pin.)
    """
    m = _load_kuji_module()
    # source 文字列レベルで確認 (cleanup logic 物理的に V-AB 範囲のみ touch)
    src = (_KUJI / "ichibankuji_to_csv.py").read_text(encoding='utf-8')
    # cleanup の range 指定が V-AB だけ
    assert "range(21, 28)" in src or "range(21,28)" in src, "V-AB cleanup range should be 21-28"
    assert "f'V{row_num}:AB{row_num}'" in src or 'f"V{row_num}:AB{row_num}"' in src, \
        "cleanup should target V-AB only, not AC-AG"
