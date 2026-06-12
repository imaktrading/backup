"""checker.py 純関数の unit tests (offline)."""

import pytest

from dedupe.checker import (
    FLAG_DUP_CARD_ID,
    FLAG_DUP_MODEL,
    FLAG_DUP_URL,
    FLAG_NEW,
    FLAG_UNKNOWN,
    KEY_TYPE_CARD,
    KEY_TYPE_MODEL,
    KEY_TYPE_NONE,
    KEY_TYPE_URL,
    ExistingIndex,
    build_existing_index,
    classify_existing_key,
    classify_row,
    extract_priority_key,
    extract_priority_key2,
)

pytestmark = pytest.mark.offline


class TestBuildIndex:
    def test_empty(self):
        idx = build_existing_index([])
        assert idx.url_keys == frozenset()
        assert idx.tcg_ids == frozenset()
        assert idx.gshock_models == frozenset()

    def test_mixed_titles(self):
        rows = [
            ("ワンピース #OP01-016 シャンクス", "https://jp.mercari.com/item/m111"),
            ("DW-5600-1JF Casio G-Shock", "https://jp.mercari.com/item/m222"),
            ("無関係なタイトル", ""),
        ]
        idx = build_existing_index(rows)
        assert "OP01-016" in idx.tcg_ids
        assert "DW-5600-1JF" in idx.gshock_models
        assert "item:m111" in idx.url_keys
        assert "item:m222" in idx.url_keys


class TestClassify:
    @pytest.fixture
    def existing(self):
        return ExistingIndex(
            url_keys=frozenset({"item:m999"}),
            tcg_ids=frozenset({"OP01-016"}),
            gshock_models=frozenset({"DW-5600-1JF"}),
        )

    def test_url_duplicate(self, existing):
        flag = classify_row(
            title="任意のタイトル",
            url="https://jp.mercari.com/item/m999?afid=x",
            existing=existing,
        )
        assert flag == FLAG_DUP_URL

    def test_card_id_duplicate(self, existing):
        flag = classify_row(
            title="ワンピース #OP01-016 シャンクス SR",
            url="https://jp.mercari.com/item/m_other",
            existing=existing,
        )
        assert flag == FLAG_DUP_CARD_ID

    def test_model_duplicate(self, existing):
        flag = classify_row(
            title="Casio G-Shock DW-5600-1JF",
            url="https://jp.mercari.com/item/m_other",
            existing=existing,
        )
        assert flag == FLAG_DUP_MODEL

    def test_new_when_id_extracted_but_not_in_existing(self, existing):
        flag = classify_row(
            title="ワンピース #OP09-001 別カード",
            url="https://jp.mercari.com/item/m_other",
            existing=existing,
        )
        assert flag == FLAG_NEW

    def test_unknown_when_no_id_extracted(self, existing):
        """extractor hit せず → fail-closed = 不明."""
        flag = classify_row(
            title="ポケモン センター限定 メタルキーホルダー",
            url="https://example.com/something",
            existing=existing,
        )
        assert flag == FLAG_UNKNOWN

    def test_url_takes_priority(self, existing):
        """URL も card_id も既存 hit するなら URL を優先 (= 確度最高)."""
        flag = classify_row(
            title="ワンピース #OP01-016 (= card_id 重複)",
            url="https://jp.mercari.com/item/m999",  # URL も重複
            existing=existing,
        )
        assert flag == FLAG_DUP_URL

    def test_extracted_id_param_used(self, existing):
        """中間スプシで抽出くんが既に書込んだ id を引数で渡せば、 title 再抽出しなくても OK."""
        flag = classify_row(
            title="title から抽出できないノイズ string",
            url="https://example.com/x",
            existing=existing,
            extracted_id="OP01-016",
        )
        assert flag == FLAG_DUP_CARD_ID


class TestExtractPriorityKey:
    """KEY 列 (= Phase 1a) 書込値抽出. 優先順序 card_id > 型番 > URL."""

    def test_card_id_wins_over_url(self):
        """card_id と URL 両方ある場合は card_id を優先."""
        key, t = extract_priority_key(
            title="ワンピース #OP01-016 シャンクス",
            url="https://jp.mercari.com/item/m12345",
        )
        assert key == "OP01-016"
        assert t == KEY_TYPE_CARD

    def test_model_wins_over_url(self):
        """G-shock 型番 と URL 両方ある場合は 型番 を優先."""
        key, t = extract_priority_key(
            title="Casio DW-5600-1JF G-Shock",
            url="https://jp.mercari.com/item/m99999",
        )
        assert key == "DW-5600-1JF"
        assert t == KEY_TYPE_MODEL

    def test_url_when_no_id_in_title(self):
        """title から id 取れない PSA10 系は URL key にフォールバック."""
        key, t = extract_priority_key(
            title="PSA10 アルセウスV RR S9 スターバース 5918",
            url="https://jp.mercari.com/item/m77777",
        )
        assert key == "item:m77777"
        assert t == KEY_TYPE_URL

    def test_fail_closed(self):
        """全 extractor hit せず → (None, "")."""
        key, t = extract_priority_key(
            title="ノーマルカード 標準 set code なし",
            url="https://example.com/foo",
        )
        assert key is None
        assert t == KEY_TYPE_NONE


class TestClassifyExistingKey:
    """既存スプシ KEY 列 値の type 判定 (= Phase 1b で index 振分け)."""

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("item:m12345", KEY_TYPE_URL),
            ("shops:abc-def", KEY_TYPE_URL),
            ("OP01-016", KEY_TYPE_CARD),
            ("SV1A-001", KEY_TYPE_CARD),
            ("LIOV-EN042", KEY_TYPE_CARD),
            ("DW-5600-1JF", KEY_TYPE_MODEL),
            ("GA-2100-1A", KEY_TYPE_MODEL),
            ("MTG-B3000B-1A", KEY_TYPE_MODEL),
        ],
    )
    def test_classifies(self, key, expected):
        assert classify_existing_key(key) == expected

    @pytest.mark.parametrize("key", ["", "  ", None])
    def test_empty(self, key):
        assert classify_existing_key(key) == KEY_TYPE_NONE

    def test_unknown_free_form(self):
        """手動補完で自由文字列入った場合は 'unknown' (= index に入れない)."""
        assert classify_existing_key("free form note") == "unknown"


class TestExtractPriorityKey2:
    """Phase 1f: (KEY1, KEY1_type, KEY2_variant) 3-tuple 抽出."""

    def test_card_with_variant(self):
        """title に card_id + variant keyword 両方 → (card, card, variant)."""
        k1, t1, k2 = extract_priority_key2(
            "One Piece Card Uta OP02-120 Secret Alternate Art PSA 10", ""
        )
        assert k1 == "OP02-120"
        assert t1 == KEY_TYPE_CARD
        assert k2 == "sec"

    def test_card_normal_no_variant(self):
        """title に card_id だけ + variant なし → (card, card, "")."""
        k1, t1, k2 = extract_priority_key2(
            "PSA10 #OP01-016 シャンクス Leader", ""
        )
        assert k1 == "OP01-016"
        assert t1 == KEY_TYPE_CARD
        assert k2 == ""

    def test_model_with_variant(self):
        k1, t1, k2 = extract_priority_key2(
            "Casio G-Shock DW-5600-1JF Special edition", ""
        )
        assert k1 == "DW-5600-1JF"
        assert t1 == KEY_TYPE_MODEL
        assert k2 == "spc"

    def test_url_key_drops_variant(self):
        """URL 型 KEY1 は variant 概念なし → KEY2 = "" (= 推測しない)."""
        k1, t1, k2 = extract_priority_key2(
            "PSA10 マルコ #002 Promo card 7214",
            "https://jp.mercari.com/item/m12345",
        )
        assert k1 == "item:m12345"
        assert t1 == KEY_TYPE_URL
        assert k2 == ""

    def test_extra_text_used_when_title_misses_variant(self):
        """title に variant 無 + extra_text (= Subject aspect) に variant あり → 取れる."""
        k1, t1, k2 = extract_priority_key2(
            title="OP08-106 Nami",
            url="",
            extra_text="ONE PIECE CARD GAME / OP08-106 NAMI / SECRET RARE",
        )
        assert k1 == "OP08-106"
        assert t1 == KEY_TYPE_CARD
        assert k2 == "sec"

    def test_fail_closed_no_key1(self):
        """KEY1 取れなければ KEY2 も "" (= 全部 fail-closed)."""
        k1, t1, k2 = extract_priority_key2(
            "Some random Alt Art title with no card_id", ""
        )
        assert k1 is None
        assert t1 == KEY_TYPE_NONE
        assert k2 == ""
