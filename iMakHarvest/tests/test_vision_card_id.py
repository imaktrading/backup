"""tests/test_vision_card_id - Phase 2 Vision API card_id 認識 offline tests.

API key を必要としない単体テストのみ:
  - parse_card_id_response (= レスポンスバリデーション)
  - reconcile_title_and_vision (= title × Vision 合議)
  - judge_card_id_from_image_url の fail-closed 動作 (= client=None 等)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scrapers.vision_card_id import (
    CARD_ID_RE,
    NONE_MARKERS,
    judge_card_id_from_image_url,
    parse_card_id_response,
    reconcile_title_and_vision,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# parse_card_id_response
# --------------------------------------------------------------------------
class TestParseCardIdResponse:
    def test_op_format(self):
        assert parse_card_id_response("OP01-001") == "OP01-001"
        assert parse_card_id_response("OP99-999") == "OP99-999"

    def test_st_format(self):
        assert parse_card_id_response("ST16-001") == "ST16-001"

    def test_eb_format(self):
        assert parse_card_id_response("EB03-061") == "EB03-061"

    def test_p_format(self):
        assert parse_card_id_response("P-041") == "P-041"
        assert parse_card_id_response("P-001") == "P-001"

    def test_lowercase_normalized_uppercase(self):
        assert parse_card_id_response("op06-021") == "OP06-021"
        assert parse_card_id_response("st16-001") == "ST16-001"

    def test_with_quotes(self):
        assert parse_card_id_response('"OP01-001"') == "OP01-001"
        assert parse_card_id_response("「OP01-001」") == "OP01-001"

    def test_with_punctuation(self):
        assert parse_card_id_response("OP01-001.") == "OP01-001"
        assert parse_card_id_response("OP01-001、") == "OP01-001"

    def test_extract_from_sentence(self):
        # 文章内に card_id があれば regex で抽出 (= prompt は単語のみ指示だが防御的に拾う)
        assert parse_card_id_response("カードは OP01-001 です") == "OP01-001"

    def test_none_markers_uppercase(self):
        assert parse_card_id_response("NONE") == ""
        assert parse_card_id_response("none") == ""

    def test_none_markers_japanese(self):
        assert parse_card_id_response("なし") == ""
        assert parse_card_id_response("不明") == ""
        assert parse_card_id_response("判別不能") == ""
        assert parse_card_id_response("判定不能") == ""

    def test_empty(self):
        assert parse_card_id_response("") == ""
        assert parse_card_id_response("   ") == ""

    def test_other_tcg_not_matched(self):
        # 別 TCG / 別形式 → 空文字
        assert parse_card_id_response("Pokemon Pikachu") == ""
        assert parse_card_id_response("DON!! CARD") == ""
        assert parse_card_id_response("RP-009") == ""  # = GUNDAM 形式、 P-3桁じゃない (RP-)
        assert parse_card_id_response("#209") == ""

    def test_partial_st_format_rejected(self):
        # 「ST29」 だけ (= 連番なし) は regex 不一致 → 空文字
        assert parse_card_id_response("ST29") == ""
        assert parse_card_id_response("OP06") == ""


# --------------------------------------------------------------------------
# reconcile_title_and_vision
# --------------------------------------------------------------------------
class TestReconcileTitleAndVision:
    def test_both_same(self):
        assert reconcile_title_and_vision("OP01-001", "OP01-001") == "OP01-001"

    def test_both_different_vision_wins(self):
        # 不一致時は Vision 優先 (= カード本体印字が title typo より確実)
        assert reconcile_title_and_vision("OP01-001", "OP01-002") == "OP01-002"

    def test_title_only(self):
        assert reconcile_title_and_vision("OP01-001", "") == "OP01-001"
        assert reconcile_title_and_vision("OP01-001", None) == "OP01-001"

    def test_vision_only(self):
        assert reconcile_title_and_vision("", "OP01-001") == "OP01-001"
        assert reconcile_title_and_vision(None, "OP01-001") == "OP01-001"

    def test_both_empty(self):
        assert reconcile_title_and_vision("", "") == ""
        assert reconcile_title_and_vision(None, None) == ""

    def test_case_insensitive_comparison(self):
        # 大文字小文字違いでも同一とみなす (= title 一致扱い)
        assert reconcile_title_and_vision("op01-001", "OP01-001") == "OP01-001"

    def test_whitespace_handled(self):
        assert reconcile_title_and_vision("  OP01-001  ", "  OP01-001  ") == "OP01-001"


# --------------------------------------------------------------------------
# judge_card_id_from_image_url の fail-closed 動作
# --------------------------------------------------------------------------
class TestJudgeCardIdFromImageUrl:
    def test_empty_url_returns_empty(self):
        # URL 空 → 空文字 (= API 呼出さない)
        assert judge_card_id_from_image_url("") == ""
        assert judge_card_id_from_image_url(None) == ""  # type: ignore[arg-type]

    def test_client_none_returns_empty(self, monkeypatch):
        # _get_client() が None (= API key なし、 anthropic 未インストール 等) → 空文字
        from scrapers import vision_card_id
        monkeypatch.setattr(vision_card_id, "_get_client", lambda: None)
        assert judge_card_id_from_image_url("https://cdn/x.jpg") == ""

    def test_mock_client_returns_op_id(self):
        # mock client で OP01-001 を返却 → そのまま採用
        mock_block = MagicMock()
        mock_block.text = "OP01-001"
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        result = judge_card_id_from_image_url("https://cdn/x.jpg", client=mock_client)
        assert result == "OP01-001"

    def test_mock_client_returns_none(self):
        # mock client が "NONE" を返却 → 空文字
        mock_block = MagicMock()
        mock_block.text = "NONE"
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        assert judge_card_id_from_image_url("https://cdn/x.jpg", client=mock_client) == ""

    def test_mock_client_returns_other_tcg(self):
        mock_block = MagicMock()
        mock_block.text = "Pokemon"
        mock_msg = MagicMock()
        mock_msg.content = [mock_block]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        assert judge_card_id_from_image_url("https://cdn/x.jpg", client=mock_client) == ""

    def test_mock_client_raises_exception(self):
        # API 呼出で例外 → 空文字 (fail-closed)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("rate limit")
        assert judge_card_id_from_image_url("https://cdn/x.jpg", client=mock_client) == ""

    def test_mock_client_returns_no_content(self):
        # content 空 → 空文字
        mock_msg = MagicMock()
        mock_msg.content = []
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        assert judge_card_id_from_image_url("https://cdn/x.jpg", client=mock_client) == ""


# --------------------------------------------------------------------------
# Constants 健全性
# --------------------------------------------------------------------------
class TestConstants:
    def test_card_id_regex_matches_all_formats(self):
        assert CARD_ID_RE.search("OP01-001").group(1) == "OP01-001"
        assert CARD_ID_RE.search("ST16-001").group(1) == "ST16-001"
        assert CARD_ID_RE.search("EB03-061").group(1) == "EB03-061"
        assert CARD_ID_RE.search("P-041").group(1) == "P-041"

    def test_none_markers_includes_basics(self):
        # 主要な NONE marker が含まれる
        assert "NONE" in NONE_MARKERS
        assert "なし" in NONE_MARKERS
        assert "不明" in NONE_MARKERS
        assert "判別不能" in NONE_MARKERS
