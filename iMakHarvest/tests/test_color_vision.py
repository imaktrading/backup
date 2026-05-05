"""tests/test_color_vision - Claude Vision 色判定モジュールの parse / mock API テスト.

API mock で fail-closed 動作を検証:
  - 確信ある単一色 → そのまま透過
  - 「不明」「複数色」「判別不能」等 → 空文字
  - 異常出力 (複数語 / 過長 / 引用符付き) → 空文字
  - API exception (timeout / network / SDK 不在) → 空文字
"""
from __future__ import annotations

import pytest

from scrapers import color_vision
from scrapers.color_vision import (
    judge_color_from_image_url,
    parse_color_response,
    reset_client_cache,
)


pytestmark = pytest.mark.offline


# --------------------------------------------------------------------------
# parse_color_response: 出力テキスト → 色名抽出 (純粋関数)
# --------------------------------------------------------------------------
class TestParseColorResponseValid:
    """Phase 1d-2: katakana 表記の色名は透過する (カタカナ強制ポリシー)."""

    @pytest.mark.parametrize("text,expected", [
        ("ブラック", "ブラック"),
        ("ホワイト", "ホワイト"),
        ("レッド", "レッド"),
        ("ブルー", "ブルー"),
        ("グリーン", "グリーン"),
        ("ネイビー", "ネイビー"),
        ("ベージュ", "ベージュ"),
        ("ピンク", "ピンク"),
        ("オレンジ", "オレンジ"),
        ("グレー", "グレー"),
        ("アイボリー", "アイボリー"),
        ("ライトグリーン", "ライトグリーン"),
        ("ダークブルー", "ダークブルー"),
        ("ペールピンク", "ペールピンク"),
    ])
    def test_simple_color_passes_through(self, text, expected):
        assert parse_color_response(text) == expected

    def test_strips_whitespace(self):
        assert parse_color_response("  ブラック\n") == "ブラック"

    def test_strips_quotation_marks(self):
        assert parse_color_response("「ブラック」") == "ブラック"
        assert parse_color_response('"レッド"') == "レッド"

    def test_color_suffix_passes_through_unchanged(self):
        # 「ブラックカラー」のような接尾辞付きは AI 側プロンプトで禁止指示済。
        # parse 側は剥がさず透過する (「ローズピンク」等の compound を壊さないため)。
        # AI が指示を破った場合も HQ 側 listing スクリプトで正規化される前提。
        assert parse_color_response("ブラックカラー") == "ブラックカラー"

    def test_compound_color_names_preserved(self):
        # 「カラー」を語の一部として含む有効な色名はそのまま透過
        assert parse_color_response("ローズピンク") == "ローズピンク"
        assert parse_color_response("マルチカラー") == "マルチカラー"


class TestParseColorResponseRejectsKanji:
    """Phase 1d-2: 漢字のみの色名は reject (catalog カタカナ統一のため)."""

    @pytest.mark.parametrize("text", [
        "黒", "白", "赤", "青", "緑", "黄", "紫", "茶",  # 単漢字色
        "黒色", "赤色", "緑色", "深緑色",                    # 漢字 + 「色」サフィックス
        "水色",                                             # 慣用 純漢字色名 (catalog はカタカナ統一なので reject)
    ])
    def test_kanji_only_returns_empty(self, text):
        assert parse_color_response(text) == ""

    def test_kanji_with_color_suffix_returns_empty(self):
        # 漢字 + 「色」 → reject
        assert parse_color_response("黒色") == ""
        assert parse_color_response("赤色") == ""


class TestParseColorResponseUncertain:
    @pytest.mark.parametrize("text", [
        "不明",
        "わからない",
        "判別不能",
        "判定不能",
        "分からない",
        "複数",
        "複数色",
        "混在",
        "unknown",
        "Unknown",
        "multiple colors",
        "?",
        "？",
    ])
    def test_uncertain_keyword_returns_empty(self, text):
        assert parse_color_response(text) == ""

    def test_empty_input(self):
        assert parse_color_response("") == ""
        assert parse_color_response("   ") == ""

    def test_only_punctuation_returns_empty(self):
        assert parse_color_response("...") == ""
        assert parse_color_response("「」") == ""

    def test_multiple_words_returns_empty(self):
        # 空白で複数語 → 不明扱い
        assert parse_color_response("黒 白") == ""
        assert parse_color_response("黒 と 白") == ""

    def test_excessive_length_returns_empty(self):
        # 12 字超 → 異常出力扱い
        long_text = "黒" * 13
        assert parse_color_response(long_text) == ""

    def test_explanation_sentence_returns_empty(self):
        # AI が説明文を返してきたケース
        assert parse_color_response("この商品は黒です") == ""


# --------------------------------------------------------------------------
# judge_color_from_image_url: mock client で API レスポンスをシミュレート
# --------------------------------------------------------------------------
class _MockMessage:
    def __init__(self, text: str):
        self.content = [_MockBlock(text)]


class _MockBlock:
    def __init__(self, text: str):
        self.text = text


class _MockMessages:
    def __init__(self, response_text: str = "", raise_exc: Exception | None = None):
        self._response_text = response_text
        self._raise_exc = raise_exc
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise_exc:
            raise self._raise_exc
        return _MockMessage(self._response_text)


class _MockAnthropicClient:
    def __init__(self, response_text: str = "", raise_exc: Exception | None = None):
        self.messages = _MockMessages(response_text, raise_exc)


class TestJudgeColorWithMockClient:
    def setup_method(self):
        reset_client_cache()

    def test_returns_color_on_simple_response(self):
        client = _MockAnthropicClient(response_text="ブラック")
        result = judge_color_from_image_url(
            "https://example.com/image.jpg", client=client,
        )
        assert result == "ブラック"

    def test_returns_empty_when_ai_responds_with_kanji(self):
        # AI が katakana mandate を破って漢字を返した → reject (空文字)
        client = _MockAnthropicClient(response_text="黒")
        result = judge_color_from_image_url(
            "https://example.com/image.jpg", client=client,
        )
        assert result == ""

    def test_returns_empty_on_uncertain_response(self):
        client = _MockAnthropicClient(response_text="不明")
        result = judge_color_from_image_url(
            "https://example.com/image.jpg", client=client,
        )
        assert result == ""

    def test_returns_empty_on_multiple_colors(self):
        client = _MockAnthropicClient(response_text="複数色")
        result = judge_color_from_image_url(
            "https://example.com/image.jpg", client=client,
        )
        assert result == ""

    def test_returns_empty_on_api_exception(self):
        # ConnectionError / Timeout 等 → 空文字 (fail-closed)
        client = _MockAnthropicClient(raise_exc=ConnectionError("network down"))
        result = judge_color_from_image_url(
            "https://example.com/image.jpg", client=client,
        )
        assert result == ""

    def test_returns_empty_on_timeout_exception(self):
        client = _MockAnthropicClient(raise_exc=TimeoutError("timed out"))
        result = judge_color_from_image_url(
            "https://example.com/image.jpg", client=client,
        )
        assert result == ""

    def test_returns_empty_on_empty_image_url(self):
        client = _MockAnthropicClient(response_text="黒")
        result = judge_color_from_image_url("", client=client)
        assert result == ""
        # API は呼ばれない (early return)
        assert client.messages.calls == []

    def test_returns_empty_when_client_is_none(self):
        # API key 無し / SDK 未インストール想定
        result = judge_color_from_image_url(
            "https://example.com/image.jpg", client=None,
        )
        assert result == ""

    def test_passes_image_url_in_request(self):
        client = _MockAnthropicClient(response_text="黒")
        judge_color_from_image_url(
            "https://m.media-amazon.com/test.jpg", client=client,
        )
        assert len(client.messages.calls) == 1
        kwargs = client.messages.calls[0]
        # 画像 URL がリクエストに含まれているか
        content = kwargs["messages"][0]["content"]
        assert content[0]["type"] == "image"
        assert content[0]["source"]["url"] == "https://m.media-amazon.com/test.jpg"

    def test_uses_correct_model(self):
        client = _MockAnthropicClient(response_text="黒")
        judge_color_from_image_url(
            "https://example.com/image.jpg", client=client,
        )
        kwargs = client.messages.calls[0]
        assert kwargs["model"] == color_vision.MODEL_ID
        # Haiku 4.5 であることを確認
        assert "haiku" in kwargs["model"].lower()

    def test_passes_title_in_prompt_when_provided(self):
        client = _MockAnthropicClient(response_text="グリーン")
        judge_color_from_image_url(
            "https://example.com/image.jpg",
            title="モンベル ウィンドブラスト L グリーン",
            client=client,
        )
        kwargs = client.messages.calls[0]
        prompt_text = kwargs["messages"][0]["content"][1]["text"]
        # context あり版 prompt が使われ、タイトルが埋め込まれている
        assert "モンベル ウィンドブラスト L グリーン" in prompt_text
        assert "原文表記" in prompt_text  # context あり版の特徴語

    def test_passes_description_in_prompt_when_provided(self):
        client = _MockAnthropicClient(response_text="ネイビー")
        judge_color_from_image_url(
            "https://example.com/image.jpg",
            description="商品説明: 色はネイビーです",
            client=client,
        )
        kwargs = client.messages.calls[0]
        prompt_text = kwargs["messages"][0]["content"][1]["text"]
        assert "色はネイビーです" in prompt_text

    def test_no_context_uses_simple_prompt(self):
        # title / description 両方空 → シンプル版 prompt
        client = _MockAnthropicClient(response_text="黒")
        judge_color_from_image_url(
            "https://example.com/image.jpg", client=client,
        )
        kwargs = client.messages.calls[0]
        prompt_text = kwargs["messages"][0]["content"][1]["text"]
        # シンプル版 prompt: 「商品情報」セクションが無い
        assert "【商品情報】" not in prompt_text
        assert "原文表記" not in prompt_text

    def test_long_description_is_truncated(self):
        # description が DESCRIPTION_CONTEXT_MAX_CHARS を超える → truncate される
        long_desc = "x" * 1000
        client = _MockAnthropicClient(response_text="黒")
        judge_color_from_image_url(
            "https://example.com/image.jpg",
            description=long_desc,
            client=client,
        )
        kwargs = client.messages.calls[0]
        prompt_text = kwargs["messages"][0]["content"][1]["text"]
        # truncate されて末尾に "..." が付いている
        assert "..." in prompt_text
        # 全 1000 字は含まれていない
        assert "x" * 500 not in prompt_text


# --------------------------------------------------------------------------
# _build_prompt: title/description の context あり/なしの分岐
# --------------------------------------------------------------------------
class TestBuildPrompt:
    def test_no_context_returns_simple_prompt(self):
        from scrapers.color_vision import _build_prompt, COLOR_PROMPT_NO_CONTEXT  # noqa: PLC0415
        assert _build_prompt(title="", description="") == COLOR_PROMPT_NO_CONTEXT

    def test_whitespace_only_treated_as_no_context(self):
        from scrapers.color_vision import _build_prompt, COLOR_PROMPT_NO_CONTEXT  # noqa: PLC0415
        assert _build_prompt(title="   ", description="\n\t") == COLOR_PROMPT_NO_CONTEXT

    def test_title_only_uses_context_prompt(self):
        from scrapers.color_vision import _build_prompt  # noqa: PLC0415
        prompt = _build_prompt(title="グリーン Tシャツ", description="")
        assert "【商品情報】" in prompt
        assert "グリーン Tシャツ" in prompt
        # description が空なので "(なし)" になる
        assert "(なし)" in prompt

    def test_description_only_uses_context_prompt(self):
        from scrapers.color_vision import _build_prompt  # noqa: PLC0415
        prompt = _build_prompt(title="", description="赤いセーター、サイズ M")
        assert "【商品情報】" in prompt
        assert "赤いセーター、サイズ M" in prompt

    def test_both_provided_includes_both(self):
        from scrapers.color_vision import _build_prompt  # noqa: PLC0415
        prompt = _build_prompt(
            title="モンベル ウィンドブラスト L グリーン",
            description="色はグリーン、サイズLです",
        )
        assert "モンベル ウィンドブラスト L グリーン" in prompt
        assert "色はグリーン、サイズLです" in prompt


# --------------------------------------------------------------------------
# _load_api_key: 環境変数 / ファイル / 未設定 のフォールバック順
# --------------------------------------------------------------------------
class TestLoadApiKey:
    def test_env_var_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env_key_xyz")
        assert color_vision._load_api_key() == "env_key_xyz"

    def test_returns_empty_when_neither_set(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # 存在しないパスを指す
        nonexistent = tmp_path / "nope.txt"
        monkeypatch.setattr(color_vision, "API_KEY_PATH", str(nonexistent))
        assert color_vision._load_api_key() == ""

    def test_reads_from_file_when_env_unset(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        key_file = tmp_path / "api_key.txt"
        key_file.write_text("file_key_abc\n", encoding="utf-8")
        monkeypatch.setattr(color_vision, "API_KEY_PATH", str(key_file))
        assert color_vision._load_api_key() == "file_key_abc"

    def test_strips_whitespace_from_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        key_file = tmp_path / "api_key.txt"
        key_file.write_text("  trimmed_key  \n\n", encoding="utf-8")
        monkeypatch.setattr(color_vision, "API_KEY_PATH", str(key_file))
        assert color_vision._load_api_key() == "trimmed_key"


# --------------------------------------------------------------------------
# _judge_color (mercari_item_detail 経由): graceful failure 確認
# --------------------------------------------------------------------------
class TestMercariJudgeColorWrapper:
    """_judge_color は color_vision を import するが、失敗時も例外を上位に投げない."""

    def test_empty_image_urls_returns_empty(self):
        from scrapers.mercari_item_detail import _judge_color  # noqa: PLC0415
        # title / description も空 → AI fallback も Step 1 も空 → 空文字
        assert _judge_color([]) == ""

    def test_none_image_urls_returns_empty(self):
        from scrapers.mercari_item_detail import _judge_color  # noqa: PLC0415
        assert _judge_color(None) == ""

    def test_step1_text_extraction_short_circuits_ai(self):
        # title に whitelist 一致 katakana 色名 → AI 呼ばずに即返却
        # image_urls 空でも title から抽出できれば値が返る
        from scrapers.mercari_item_detail import _judge_color  # noqa: PLC0415
        assert _judge_color(
            image_urls=[],
            title="モンベル ウィンドブラスト L グリーン",
        ) == "グリーン"

    def test_step1_compound_color_preserved(self):
        # description に「ライトグリーン」→ そのまま (グリーンに丸めない)
        from scrapers.mercari_item_detail import _judge_color  # noqa: PLC0415
        assert _judge_color(
            image_urls=[],
            description="色: ライトグリーン系のセーター",
        ) == "ライトグリーン"

    def test_step1_title_priority_over_description(self):
        # title と description の両方に色がある → title 優先
        from scrapers.mercari_item_detail import _judge_color  # noqa: PLC0415
        assert _judge_color(
            image_urls=[],
            title="ブラック T シャツ",
            description="参考: 過去出品はネイビーでした",
        ) == "ブラック"


# --------------------------------------------------------------------------
# extract_katakana_color_from_text: whitelist 抽出ロジック
# --------------------------------------------------------------------------
class TestExtractKatakanaColorFromText:
    """Phase 1d-2: 確定的なテキスト抽出 (AI 不要、出品者表記を尊重)."""

    @pytest.mark.parametrize("title,expected", [
        # 基本 15 色
        ("ブラック T シャツ", "ブラック"),
        ("ホワイト パンツ", "ホワイト"),
        ("レッド スカーフ", "レッド"),
        ("ブルー ジャケット", "ブルー"),
        ("グリーン ハット", "グリーン"),
        ("イエロー シャツ", "イエロー"),
        ("オレンジ パーカー", "オレンジ"),
        ("ピンク カーディガン", "ピンク"),
        ("パープル ニット", "パープル"),
        ("ブラウン ベルト", "ブラウン"),
        ("グレー スウェット", "グレー"),
        ("ベージュ コート", "ベージュ"),
        ("シルバー リング", "シルバー"),
        ("ゴールド ブレスレット", "ゴールド"),
        ("アイボリー シルク", "アイボリー"),
        # 追加 12 色
        ("ネイビー ジャケット", "ネイビー"),
        ("カーキ パンツ", "カーキ"),
        ("マスタード スカーフ", "マスタード"),
        ("ターコイズ ピアス", "ターコイズ"),
        ("ワインレッド ドレス", "ワインレッド"),
        ("ボルドー ニット", "ボルドー"),
        ("チャコール スーツ", "チャコール"),
        ("モスグリーン パーカー", "モスグリーン"),
        ("オリーブ シャツ", "オリーブ"),
        ("バーガンディ コート", "バーガンディ"),
        ("セージ T シャツ", "セージ"),
        ("ガーネット ストール", "ガーネット"),
    ])
    def test_basic_color_extraction_from_title(self, title, expected):
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        assert extract_katakana_color_from_text(title=title, description="") == expected

    @pytest.mark.parametrize("title,expected", [
        ("ライトグリーン Tシャツ", "ライトグリーン"),
        ("ダークブルー ジャケット", "ダークブルー"),
        ("ペールピンク カーディガン", "ペールピンク"),
        ("ディープレッド スカーフ", "ディープレッド"),
        ("ライトベージュ コート", "ライトベージュ"),
        ("ダークネイビー パンツ", "ダークネイビー"),
    ])
    def test_compound_colors_preserved(self, title, expected):
        # 複合色 (ライト/ダーク/ペール/ディープ + base) は丸めず詳細表記のまま
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        assert extract_katakana_color_from_text(title=title, description="") == expected

    def test_compound_takes_priority_over_base(self):
        # 「ライトグリーン」を「グリーン」より優先 (longest match first)
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        result = extract_katakana_color_from_text(
            title="ライトグリーン Tシャツ", description="",
        )
        assert result == "ライトグリーン"
        # 「グリーン」だけが返ってきてはならない
        assert result != "グリーン"

    def test_title_prioritized_over_description(self):
        # title に色名あり → title 優先 (description の色は無視)
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        assert extract_katakana_color_from_text(
            title="ブラック ジャケット",
            description="ネイビーも出品中",
        ) == "ブラック"

    def test_description_used_when_title_has_no_color(self):
        # title に色名なし → description から抽出
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        assert extract_katakana_color_from_text(
            title="メンズシャツ",
            description="色はライトブルーです",
        ) == "ライトブルー"

    def test_no_match_returns_empty(self):
        # title / description どちらにもカタカナ色名なし → 空文字 (AI fallback すべし)
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        assert extract_katakana_color_from_text(
            title="メンズシャツ", description="サイズ M、新品",
        ) == ""

    def test_kanji_color_not_extracted(self):
        # 漢字色名 (「赤」「緑」等) は whitelist 対象外、抽出しない
        # AI fallback に委ねる (AI もカタカナで答える)
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        assert extract_katakana_color_from_text(
            title="赤いセーター", description="サイズ L",
        ) == ""

    def test_empty_inputs(self):
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        assert extract_katakana_color_from_text(title="", description="") == ""
        assert extract_katakana_color_from_text(title=None, description=None) == ""  # type: ignore[arg-type]

    def test_substring_in_longer_katakana_word_not_matched(self):
        """誤判定回避: カタカナ色名が他のカタカナ語の一部に substring match しないこと.

        実 dry-run で観測されたケース (item #4 ルフィカード):
          description に「グレード9」 → "グレー" が substring match してた bug
          修正後: 直後にカタカナ「ド」があるので word boundary 不一致 → AI fallback
        """
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        # グレー (gray) と グレード (grade) は別語
        assert extract_katakana_color_from_text(
            title="PSA10 ルフィ",
            description="グレード9 の MINT 鑑定品",
        ) == ""

    def test_color_followed_by_kanji_or_space_matches(self):
        """直後が空白・漢字・英数字等の非カタカナ → word boundary 一致 → match."""
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        # 空白
        assert extract_katakana_color_from_text(title="ブラック T", description="") == "ブラック"
        # 漢字
        assert extract_katakana_color_from_text(title="ブラック色", description="") == "ブラック"
        # 英数字
        assert extract_katakana_color_from_text(title="ブラックXL", description="") == "ブラック"
        # 句読点
        assert extract_katakana_color_from_text(title="ブラック、新品", description="") == "ブラック"
        # 文末
        assert extract_katakana_color_from_text(title="新品 ブラック", description="") == "ブラック"

    def test_color_preceded_by_katakana_not_matched(self):
        """直前にカタカナがあるケース (より長い compound 色の一部の可能性) → 不一致."""
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        # ロイヤルブルー (whitelist にない compound) 内の ブルー → 不一致扱い
        # → Step 2 (AI) で判定すべき
        assert extract_katakana_color_from_text(
            title="ロイヤルブルー Tシャツ",
            description="",
        ) == ""

    def test_color_followed_by_katakana_not_matched(self):
        """直後にカタカナがあるケース (compound 形成の可能性) → 不一致."""
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        # ブルージーンズ 内の ブルー → 直後 「ジ」がカタカナ → 不一致扱い
        # 「ブルージーンズ」が真の青ジーンズだとしても、AI fallback で判定
        assert extract_katakana_color_from_text(
            title="ブルージーンズ",
            description="",
        ) == ""

    def test_compound_color_still_matches_via_longest_first(self):
        """word boundary 検査でも、whitelist の compound 色が先に検出されること.

        ライトグリーン (whitelist) 内の グリーン は part だが、longest-first iteration
        により先に ライトグリーン がマッチして返される。
        """
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        assert extract_katakana_color_from_text(
            title="ライトグリーン Tシャツ",
            description="",
        ) == "ライトグリーン"

    def test_real_world_montbell_examples(self):
        # 実 backfill で観測されたケース
        from scrapers.color_vision import extract_katakana_color_from_text  # noqa: PLC0415
        # row 478/479: title に「レッド」→ AI が「赤」に置換していた問題
        assert extract_katakana_color_from_text(
            title="モンベル ウィンドブラストパーカー レッド XL",
            description="",
        ) == "レッド"
        # row 480: title「緑」、description「ライトグリーン系」→ description 優先で詳細表記
        assert extract_katakana_color_from_text(
            title="モンベル ウィンドブラスト 緑 XL",
            description="色はライトグリーン系の明るめのグリーン",
        ) == "ライトグリーン"
        # row 481: title「グリーン」
        assert extract_katakana_color_from_text(
            title="モンベル ウィンドブラスト グリーン XL",
            description="",
        ) == "グリーン"

    def test_whitelist_includes_all_required_colors(self):
        # 仕様で指定された全 27 色 (15 base + 12 extended) が whitelist にある
        from scrapers.color_vision import (  # noqa: PLC0415
            BASE_KATAKANA_COLORS,
            EXTENDED_KATAKANA_COLORS,
            KATAKANA_COLOR_WHITELIST,
        )
        for color in BASE_KATAKANA_COLORS + EXTENDED_KATAKANA_COLORS:
            assert color in KATAKANA_COLOR_WHITELIST, f"missing: {color}"

    def test_whitelist_includes_compound_colors(self):
        # ライト/ダーク/ペール/ディープ × 全 base = compound 色も whitelist にある
        from scrapers.color_vision import (  # noqa: PLC0415
            BASE_KATAKANA_COLORS,
            COMPOUND_PREFIXES,
            KATAKANA_COLOR_WHITELIST,
        )
        for prefix in COMPOUND_PREFIXES:
            for base in BASE_KATAKANA_COLORS:
                expected = f"{prefix}{base}"
                assert expected in KATAKANA_COLOR_WHITELIST, f"missing: {expected}"

    def test_whitelist_sorted_longest_first(self):
        # longest-match-first 動作のため、whitelist は長い順
        from scrapers.color_vision import KATAKANA_COLOR_WHITELIST  # noqa: PLC0415
        prev_len = len(KATAKANA_COLOR_WHITELIST[0])
        for color in KATAKANA_COLOR_WHITELIST[1:]:
            assert len(color) <= prev_len, f"sort broken at: {color}"
            prev_len = len(color)


# --------------------------------------------------------------------------
# _is_kanji_only: 漢字 reject 判定の純粋関数テスト
# --------------------------------------------------------------------------
class TestIsKanjiOnly:
    @pytest.mark.parametrize("text", [
        "黒", "白", "赤", "青", "緑", "黄",
        "黒色", "赤色", "深緑色", "水色",
    ])
    def test_kanji_only_returns_true(self, text):
        from scrapers.color_vision import _is_kanji_only  # noqa: PLC0415
        assert _is_kanji_only(text) is True

    @pytest.mark.parametrize("text", [
        "ブラック", "ホワイト", "ライトグリーン", "ABC",
        "黒レッド",  # 混在
        "ブラックカラー",
        "",
    ])
    def test_non_kanji_only_returns_false(self, text):
        from scrapers.color_vision import _is_kanji_only  # noqa: PLC0415
        assert _is_kanji_only(text) is False


# --------------------------------------------------------------------------
# _first_product_image_url: image_urls から商品本体画像のみ抽出
# --------------------------------------------------------------------------
class TestFirstProductImageUrl:
    """Mercari image_urls には出品者画像・関連商品サムネが混在する。
    色判定では商品本体画像 (/item/detail/orig/photos/) のみ採用する。
    """

    def test_skips_seller_profile_picks_product(self):
        # 実 dry-run で観測されたパターン: 先頭が出品者プロフィール画像
        from scrapers.mercari_item_detail import _first_product_image_url  # noqa: PLC0415
        urls = [
            "https://static.mercdn.net/thumb/members/webp/415216906.jpg?1465253168",  # 出品者画像
            "https://static.mercdn.net/item/detail/orig/photos/m29660190746_1.jpg?1777261342",  # 商品 1
            "https://static.mercdn.net/item/detail/orig/photos/m29660190746_2.jpg?1777261342",  # 商品 2
        ]
        assert _first_product_image_url(urls) == (
            "https://static.mercdn.net/item/detail/orig/photos/m29660190746_1.jpg?1777261342"
        )

    def test_skips_related_item_thumbnails(self):
        # 関連商品サムネイル (thumb/item/jpeg) も無視
        from scrapers.mercari_item_detail import _first_product_image_url  # noqa: PLC0415
        urls = [
            "https://static.mercdn.net/thumb/item/jpeg/m72018963718_1.jpg?1777881207",  # 関連
            "https://static.mercdn.net/thumb/item/webp/m51203798829_1.jpg?1777902843",  # 関連
            "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg",  # 商品本体
        ]
        assert _first_product_image_url(urls) == (
            "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg"
        )

    def test_skips_noimage_placeholder(self):
        from scrapers.mercari_item_detail import _first_product_image_url  # noqa: PLC0415
        urls = [
            "https://static.mercdn.net/images/member_photo_noimage_thumb.png",
            "https://static.mercdn.net/item/detail/orig/photos/m99999999999_3.jpg",
        ]
        assert _first_product_image_url(urls) == (
            "https://static.mercdn.net/item/detail/orig/photos/m99999999999_3.jpg"
        )

    def test_returns_first_when_only_product_images(self):
        from scrapers.mercari_item_detail import _first_product_image_url  # noqa: PLC0415
        urls = [
            "https://static.mercdn.net/item/detail/orig/photos/m11111111111_1.jpg",
            "https://static.mercdn.net/item/detail/orig/photos/m11111111111_2.jpg",
        ]
        assert _first_product_image_url(urls) == (
            "https://static.mercdn.net/item/detail/orig/photos/m11111111111_1.jpg"
        )

    def test_returns_empty_when_no_product_images(self):
        # 商品画像が 1 つも無い → 空 (fail-closed)
        from scrapers.mercari_item_detail import _first_product_image_url  # noqa: PLC0415
        urls = [
            "https://static.mercdn.net/thumb/members/webp/415216906.jpg",
            "https://static.mercdn.net/thumb/item/jpeg/m72018963718_1.jpg",
        ]
        assert _first_product_image_url(urls) == ""

    def test_empty_input(self):
        from scrapers.mercari_item_detail import _first_product_image_url  # noqa: PLC0415
        assert _first_product_image_url([]) == ""
        assert _first_product_image_url(None) == ""

    def test_skips_empty_strings(self):
        from scrapers.mercari_item_detail import _first_product_image_url  # noqa: PLC0415
        urls = [
            "",
            "https://static.mercdn.net/item/detail/orig/photos/m11111111111_1.jpg",
        ]
        assert _first_product_image_url(urls) == (
            "https://static.mercdn.net/item/detail/orig/photos/m11111111111_1.jpg"
        )

    def test_supports_jpeg_extension(self):
        from scrapers.mercari_item_detail import _first_product_image_url  # noqa: PLC0415
        urls = [
            "https://static.mercdn.net/item/detail/orig/photos/m11111111111_1.jpeg",
        ]
        assert _first_product_image_url(urls) == urls[0]

    def test_supports_webp_extension(self):
        from scrapers.mercari_item_detail import _first_product_image_url  # noqa: PLC0415
        urls = [
            "https://static.mercdn.net/item/detail/orig/photos/m11111111111_1.webp",
        ]
        assert _first_product_image_url(urls) == urls[0]
