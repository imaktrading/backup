"""gshock_to_csv.py のスプシ駆動連携テスト (2026-05-05).

設計思想:
  抽出くん (LOW スプシ R='G-shock') と出品くん (gshock_to_csv) の自動連動を
  永久保証する. 漏れた商品が出ない構造的解決を保護.

memory:
  - dropshipping_model_premise (抽出くん収集 → 出品くん自動連動)
  - no_modification_chain (URL ファイル fallback で既存運用破壊しない)
  - bug=test 追加運用
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GS_PATHS = [
    str(_REPO_ROOT / "iMakG-shock"),
    str(_REPO_ROOT / "iMakG-shock" / "casio_finder"),
]
_KEEP_PATHS = [
    str(_REPO_ROOT / "iMakeBayAPI"),
    str(_REPO_ROOT / "iMakCatalog" / "integrations"),
]
for p in _GS_PATHS + _KEEP_PATHS:
    if p not in sys.path:
        sys.path.insert(0, p)

import gshock_to_csv  # noqa: E402

for p in _GS_PATHS:
    while p in sys.path:
        sys.path.remove(p)


# ============================================================================
# build_casio_url (型番 → CASIO 公式 URL)
# ============================================================================
def test_build_casio_url_basic():
    assert gshock_to_csv.build_casio_url("GA-2100-1A1JF") == \
        "https://www.casio.com/jp/watches/gshock/product.GA-2100-1A1JF/"


def test_build_casio_url_complex_model():
    assert gshock_to_csv.build_casio_url("GMW-B5000BT-1") == \
        "https://www.casio.com/jp/watches/gshock/product.GMW-B5000BT-1/"


# ============================================================================
# extract_model_from_text (タイトル/説明文 → CASIO 型番抽出)
# ============================================================================
def test_extract_model_full_jf_suffix():
    """JF/JR suffix 付きフル型番を抽出."""
    text = "[カシオ] 腕時計 ジーショック GA-B010BEG-1AJF メンズ ブラック"
    assert gshock_to_csv.extract_model_from_text(text) == "GA-B010BEG-1AJF"


def test_extract_model_jr_suffix():
    """JR suffix 付き型番."""
    text = "「赤提灯」デザイン 環境配慮素材採用 DW-6900AKA-4JR メンズ レッド"
    assert gshock_to_csv.extract_model_from_text(text) == "DW-6900AKA-4JR"


def test_extract_model_complex_pattern():
    """GMW-B5000BT-1 のような複雑型番."""
    text = "G-Shock Domestic Genuine] Metal Covered GMW-B5000BT-1 Men's Black"
    result = gshock_to_csv.extract_model_from_text(text)
    assert result is not None
    assert "GMW-B5000BT" in result


def test_extract_model_no_match():
    """型番なしテキストでは None."""
    assert gshock_to_csv.extract_model_from_text("普通の文字列") is None
    assert gshock_to_csv.extract_model_from_text("") is None


def test_extract_model_short_pattern_rejected():
    """ハイフン無しや短すぎるパターンは拒否 (誤抽出防止)."""
    # "G123" のような短い文字列は拒否
    result = gshock_to_csv.extract_model_from_text("商品名 G123 です")
    # ハイフン必須 + 6 文字以上の制約で拒否される
    assert result is None or '-' in result


# ============================================================================
# load_targets_from_low_sheet (LOW スプシ取込、mock)
# ============================================================================
def _make_mock_sheet_rows(rows_data):
    """[(url, item_id, title_jp, sold, ..., category, ...), ...] から
    全 18+ 列の mock 行を作る."""
    out = [['URL', 'itemID', 'タイトル', '売り切れ', '状態', '商品価格', '写真URL',
            '商品説明', 'Title', 'Description', '出品する価格', 'ConditionID',
            '価格上昇有無', '仕入れ価格', '売り切れチェック時間', 'CTR', 'FLG',
            'カテゴリ', '色', 'サイズ']]
    for r in rows_data:
        row = [''] * 20
        for i, v in r.items():
            row[i] = v
        out.append(row)
    return out


def test_load_targets_filters_by_category_gshock():
    """R='G-shock' のみ、それ以外 (Tシャツ等) は除外."""
    mock_rows = _make_mock_sheet_rows([
        {0: 'https://amazon.co.jp/dp/B001', 2: 'GA-2100-1A1JF メンズ', 17: 'G-shock'},
        {0: 'https://mercari.com/m1', 2: 'Uniqlo Tシャツ', 17: 'Tシャツ'},
        {0: 'https://amazon.co.jp/dp/B002', 2: 'DW-5600AKA-4JR レッド', 17: 'G-shock'},
    ])
    with patch('gshock_to_csv._os.path.exists', return_value=True), \
         patch('gshock_to_csv.GSHEET_CREDS', '/fake/path'):
        # gspread / Credentials を mock
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = mock_rows
        mock_sh = MagicMock()
        mock_sh.get_worksheet_by_id.return_value = mock_ws
        mock_gc = MagicMock()
        mock_gc.open_by_key.return_value = mock_sh
        with patch('gspread.authorize', return_value=mock_gc), \
             patch('google.oauth2.service_account.Credentials.from_service_account_file',
                   return_value=MagicMock()):
            targets = gshock_to_csv.load_targets_from_low_sheet()
    # G-shock 2 件のみ
    assert len(targets) == 2
    models = [m for _, m in targets]
    assert 'GA-2100-1A1JF' in models
    assert 'DW-5600AKA-4JR' in models


def test_load_targets_excludes_sold_out():
    """D 列='○' (売り切れ) は除外."""
    mock_rows = _make_mock_sheet_rows([
        {0: 'https://amazon.co.jp/dp/B001', 2: 'GA-2100-1A1JF', 3: '○', 17: 'G-shock'},
        {0: 'https://amazon.co.jp/dp/B002', 2: 'DW-5600AKA-4JR', 3: '', 17: 'G-shock'},
    ])
    with patch('gshock_to_csv._os.path.exists', return_value=True), \
         patch('gshock_to_csv.GSHEET_CREDS', '/fake/path'):
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = mock_rows
        mock_sh = MagicMock()
        mock_sh.get_worksheet_by_id.return_value = mock_ws
        mock_gc = MagicMock()
        mock_gc.open_by_key.return_value = mock_sh
        with patch('gspread.authorize', return_value=mock_gc), \
             patch('google.oauth2.service_account.Credentials.from_service_account_file',
                   return_value=MagicMock()):
            targets = gshock_to_csv.load_targets_from_low_sheet()
    assert len(targets) == 1
    assert targets[0][1] == 'DW-5600AKA-4JR'


def test_load_targets_excludes_listed():
    """B 列 itemID あり (出品済) は除外."""
    mock_rows = _make_mock_sheet_rows([
        {0: 'https://amazon.co.jp/dp/B001', 1: '356123456789', 2: 'GA-2100-1A1JF', 17: 'G-shock'},
        {0: 'https://amazon.co.jp/dp/B002', 1: '', 2: 'DW-5600AKA-4JR', 17: 'G-shock'},
    ])
    with patch('gshock_to_csv._os.path.exists', return_value=True), \
         patch('gshock_to_csv.GSHEET_CREDS', '/fake/path'):
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = mock_rows
        mock_sh = MagicMock()
        mock_sh.get_worksheet_by_id.return_value = mock_ws
        mock_gc = MagicMock()
        mock_gc.open_by_key.return_value = mock_sh
        with patch('gspread.authorize', return_value=mock_gc), \
             patch('google.oauth2.service_account.Credentials.from_service_account_file',
                   return_value=MagicMock()):
            targets = gshock_to_csv.load_targets_from_low_sheet()
    assert len(targets) == 1
    assert targets[0][1] == 'DW-5600AKA-4JR'


def test_load_targets_skips_no_model_extracted():
    """型番抽出失敗の行は SKIP (Precision 100% 原則)."""
    mock_rows = _make_mock_sheet_rows([
        {0: 'https://amazon.co.jp/dp/B001', 2: '型番なし腕時計', 17: 'G-shock'},
        {0: 'https://amazon.co.jp/dp/B002', 2: 'GA-2100-1A1JF メンズ', 17: 'G-shock'},
    ])
    with patch('gshock_to_csv._os.path.exists', return_value=True), \
         patch('gshock_to_csv.GSHEET_CREDS', '/fake/path'):
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = mock_rows
        mock_sh = MagicMock()
        mock_sh.get_worksheet_by_id.return_value = mock_ws
        mock_gc = MagicMock()
        mock_gc.open_by_key.return_value = mock_sh
        with patch('gspread.authorize', return_value=mock_gc), \
             patch('google.oauth2.service_account.Credentials.from_service_account_file',
                   return_value=MagicMock()):
            targets = gshock_to_csv.load_targets_from_low_sheet()
    assert len(targets) == 1
    assert targets[0][1] == 'GA-2100-1A1JF'


def test_load_targets_returns_empty_when_creds_missing():
    """認証ファイルなし → 空リスト + 警告メッセージ (URL ファイル fallback 動作)."""
    with patch('gshock_to_csv._os.path.exists', return_value=False):
        targets = gshock_to_csv.load_targets_from_low_sheet()
    assert targets == []
