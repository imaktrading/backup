"""backfill_key1_key2 の record key fallback test (= Phase 1s / 2026-05-28).

catalog 側 SSOT 内 key 名不統一 (= lookup_one_piece は `card_id`、 lookup_don は
`product_id`) を dedupe 側で吸収する fallback の動作確認.
"""

from unittest.mock import MagicMock, patch

import pytest

from dedupe import sheet_io

pytestmark = pytest.mark.offline


def _ws_with_values(values):
    ws = MagicMock()
    ws.get_all_values.return_value = values
    ws.col_values.side_effect = lambda c: [
        r[c - 1] if len(r) >= c else "" for r in values
    ]
    return ws


# row layout (1-based 列番号):
#   1=URL  2=itemID  3=title  4=sold  5=KEY1  6=KEY2  7=image_url  8=cert
HEADER = ["URL", "itemID", "title", "売り切れ", "KEY1", "KEY2", "image_url", "cert"]


def _row(
    url="https://jp.mercari.com/item/m99",
    item_id="",
    title="",
    sold="",
    key1="item:m99",
    key2="",
    image_url="",
    cert="146617214",
):
    return [url, item_id, title, sold, key1, key2, image_url, cert]


def _classify(v: str) -> str:
    if not v:
        return "empty"
    if v.startswith("item:") or v.startswith("shops:"):
        return "url"
    return "card"


def _noop_extractor(title, url, extra_text=""):
    return ("", None, "")


class TestBackfillRecordKeyFallback:
    def test_backfill_accepts_card_id_key(self):
        """lookup_one_piece 戻り値 `card_id` → KEY1 採用 (= Phase 1s)."""
        ws = _ws_with_values([HEADER, _row()])

        def fake_lookup_one_piece(brand, card_number, subject, verbose=False):
            # catalog lookup_one_piece 仕様: card_id key で返す
            return {
                "card_id": "OP08-002_P_LF",
                "name_en": "Marco",
            }

        with patch.object(
            sheet_io, "_safe_cell", wraps=sheet_io._safe_cell
        ), patch(
            "dedupe.iMakeBayAPI_psa_io.get_cached_psa",
            return_value={"Brand": "ONE PIECE JAPANESE PROMOS", "Subject": "MARCO"},
        ):
            result = sheet_io.backfill_key1_key2(
                ws=ws,
                key1_col=5,
                key2_col=6,
                title_col=3,
                url_col=1,
                priority_extractor2=_noop_extractor,
                dry_run=True,
                upgrade_url_to_card=True,
                key_classifier=_classify,
                cert_col=8,
                psa_lookup_fns={"lookup_one_piece": fake_lookup_one_piece},
                image_url_col=7,
            )
        # URL key → card key upgrade されたこと
        assert result["upgraded_url_to_card"] == 1

    def test_backfill_accepts_product_id_key(self):
        """lookup_don 戻り値 `product_id` → KEY1 採用 (= 既存挙動維持)."""
        ws = _ws_with_values([HEADER, _row()])

        def fake_lookup_don(brand, subject, verbose=False, image_url=None):
            return {"product_id": "DON-OP15-001"}

        with patch(
            "dedupe.iMakeBayAPI_psa_io.get_cached_psa",
            return_value={
                "Brand": "ONE PIECE JAPANESE OP15-ADVENTURE",
                "Subject": "DON!! CARD",
            },
        ):
            result = sheet_io.backfill_key1_key2(
                ws=ws,
                key1_col=5,
                key2_col=6,
                title_col=3,
                url_col=1,
                priority_extractor2=_noop_extractor,
                dry_run=True,
                upgrade_url_to_card=True,
                key_classifier=_classify,
                cert_col=8,
                psa_lookup_fns={"lookup_don": fake_lookup_don},
                image_url_col=7,
            )
        assert result["upgraded_url_to_card"] == 1

    def test_backfill_prefers_product_id_over_card_id(self):
        """両 key 持つ場合 (= 将来の catalog 統一後) product_id 優先."""
        ws = _ws_with_values([HEADER, _row()])

        # 両 key を返す record (= catalog 将来統一後の互換状態)
        def fake_lookup(brand, card_number, subject, verbose=False):
            return {
                "product_id": "OP08-002",  # ← 優先採用
                "card_id": "OP08-002_P_LF",  # ← fallback (= 採用されない)
            }

        with patch(
            "dedupe.iMakeBayAPI_psa_io.get_cached_psa",
            return_value={"Brand": "ONE PIECE", "Subject": "X"},
        ):
            result = sheet_io.backfill_key1_key2(
                ws=ws,
                key1_col=5,
                key2_col=6,
                title_col=3,
                url_col=1,
                priority_extractor2=_noop_extractor,
                dry_run=False,  # batch_update mock で書込値を直接 verify
                upgrade_url_to_card=True,
                key_classifier=_classify,
                cert_col=8,
                psa_lookup_fns={"lookup_one_piece": fake_lookup},
                image_url_col=7,
            )
        assert result["upgraded_url_to_card"] == 1
        # batch_update に渡された value が product_id 側 (= OP08-002) であること
        ws.batch_update.assert_called_once()
        updates_arg = ws.batch_update.call_args[0][0]
        written_values = [u["values"][0][0] for u in updates_arg]
        assert "OP08-002" in written_values
        assert "OP08-002_P_LF" not in written_values
