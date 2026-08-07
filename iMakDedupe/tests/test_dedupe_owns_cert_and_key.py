"""dedupe が KEー と cert を両方持つ判定 の test (= 2026-08-07 実装).

依頼書: `2026-08-07_dedupe_owns_both_key_and_cert_response.md` (IMPLEMENT-GO)

要件:
- **cert 一致** → 無条件除外 (同一物理 slab、二度売れたら履行不能 = BAN リスク)
- **KEY 一致** → 除外 (同一カード種類の重複防止)
- 判定順序 **cert → KEY**、 上位確定 row は下位を評価しない (SSOT)
- token (タイトル部分一致) は落とさない (= 別セット同番号巻き込み防止 = 8/04 GO 済)
- 除外理由の内訳を **result["removed_by_type"]** に保持 (= 台帳監査用)
- HIGH/LOW シート集約 + live cache SKU 補完 の union が既存 cert set (依頼書 §5 制約)

eBay / Google Sheets を叩かない (= 全 mock)。
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dedupe import checker, csv_check, sheet_io

pytestmark = pytest.mark.offline


# ---------------------------------------------------------------------------
# sheet_io.read_existing_certs / certs_from_sku_map / load_live_cert_set_from_skus
# ---------------------------------------------------------------------------


def _ws(values):
    ws = MagicMock()
    ws.get_all_values.return_value = values
    return ws


HEADER_HIGH = [
    "URL", "itemID", "title", "sold",
    "e", "f", "g", "h",
    "cert",       # I=9
    "j", "k", "l", "m", "n", "o", "p", "q",
    "cat",        # R=18
]


def _row_high(
    url="", item_id="", title="", sold="", cert="", category="",
    fill_cols=18,
):
    """HIGH シートの row を作る helper (= I=cert / R=category)."""
    row = [""] * fill_cols
    row[0] = url
    row[1] = item_id
    row[2] = title
    row[3] = sold
    row[8] = cert  # I = 9 → index 8
    row[17] = category  # R = 18 → index 17
    return row


class TestReadExistingCerts:
    def test_returns_cert_for_live_tcg_rows_only(self):
        """live 出品済 かつ R='TCG' の row の cert のみ集約."""
        ws = _ws([
            HEADER_HIGH,
            _row_high(item_id="111", cert="150000001", category="TCG"),
            _row_high(item_id="222", cert="150000002", category="TCG"),
            _row_high(item_id="333", cert="150000003", category="G-shock"),  # ★ 非 TCG → skip
            _row_high(item_id="444", cert="150000004", category="TCG"),   # ★ live cache に無い → skip
        ])
        live = frozenset({"111", "222", "333"})  # 444 は eBay 側で終了
        out = sheet_io.read_existing_certs(
            ws,
            cert_col=9,
            item_id_col=2,
            live_itemid_set=live,
            category_col=18,
            category_value="TCG",
        )
        # 333 は非 TCG (montbell 型番同居問題防止)、 444 は非 live で除外
        assert out == frozenset({"150000001", "150000002"})

    def test_skips_empty_cert_cells(self):
        """cert 空の row は集約しない (= 未 PSA row)."""
        ws = _ws([
            HEADER_HIGH,
            _row_high(item_id="111", cert="", category="TCG"),
            _row_high(item_id="222", cert="150000002", category="TCG"),
        ])
        live = frozenset({"111", "222"})
        out = sheet_io.read_existing_certs(
            ws, cert_col=9, item_id_col=2, live_itemid_set=live,
            category_col=18, category_value="TCG",
        )
        assert out == frozenset({"150000002"})

    def test_skips_orphan_rows_itemid_empty(self):
        """itemID 空 (= orphan / 未出品) は集約しない."""
        ws = _ws([
            HEADER_HIGH,
            _row_high(item_id="", cert="150000001", category="TCG"),  # orphan
            _row_high(item_id="222", cert="150000002", category="TCG"),
        ])
        live = frozenset({"222"})
        out = sheet_io.read_existing_certs(
            ws, cert_col=9, item_id_col=2, live_itemid_set=live,
            category_col=18, category_value="TCG",
        )
        assert out == frozenset({"150000002"})

    def test_category_filter_optional(self):
        """category_col/value 未指定なら全 row の cert を集約 (= filter しない)."""
        ws = _ws([
            HEADER_HIGH,
            _row_high(item_id="111", cert="1", category="TCG"),
            _row_high(item_id="222", cert="2", category="G-shock"),
        ])
        live = frozenset({"111", "222"})
        out = sheet_io.read_existing_certs(
            ws, cert_col=9, item_id_col=2, live_itemid_set=live,
        )
        assert out == frozenset({"1", "2"})

    def test_montbell_type_number_isolation_needs_tcg_filter(self):
        """依頼書 §5 実害: montbell が I 列に型番を入れていて、 R='TCG' filter 無いと誤集約.

        1103247 は montbell 型番だが cert 6桁以上と長さ的にはマッチ可能。
        TCG filter で **物理的に除外** することを検証。
        """
        ws = _ws([
            HEADER_HIGH,
            _row_high(item_id="111", cert="1103247", category="montbell"),
            _row_high(item_id="222", cert="1103247", category="montbell"),
            _row_high(item_id="333", cert="1103247", category="montbell"),
            _row_high(item_id="444", cert="150000001", category="TCG"),
        ])
        live = frozenset({"111", "222", "333", "444"})
        # TCG filter 有り
        out = sheet_io.read_existing_certs(
            ws, cert_col=9, item_id_col=2, live_itemid_set=live,
            category_col=18, category_value="TCG",
        )
        assert out == frozenset({"150000001"})
        # filter 無しだと montbell 型番も混入 (= 依頼書指摘の危険挙動、 filter 必須)
        out_no_filter = sheet_io.read_existing_certs(
            ws, cert_col=9, item_id_col=2, live_itemid_set=live,
        )
        assert "1103247" in out_no_filter

    def test_empty_ws_returns_empty(self):
        assert sheet_io.read_existing_certs(_ws([]), 9, 2, frozenset()) == frozenset()

    def test_header_only_returns_empty(self):
        assert sheet_io.read_existing_certs(_ws([HEADER_HIGH]), 9, 2, frozenset({"1"})) == frozenset()


class TestCertsFromSkuMap:
    def test_extracts_psa10_prefix_cert(self):
        skus = {
            "358001": "PSA10-150000001",
            "358002": "PSA10-150000002",
            "358003": "m73494307129",       # ★ 別形式 → skip
            "358004": "005-PSA10",          # ★ 別形式 → skip
            "358005": "",                    # ★ 空 → skip
            "358006": None,                  # ★ None → skip
        }
        out = sheet_io.certs_from_sku_map(skus)
        assert out == frozenset({"150000001", "150000002"})

    def test_case_insensitive(self):
        skus = {"358001": "psa10-150000001", "358002": "Psa10-150000002"}
        out = sheet_io.certs_from_sku_map(skus)
        assert out == frozenset({"150000001", "150000002"})

    def test_none_or_empty_returns_empty(self):
        assert sheet_io.certs_from_sku_map(None) == frozenset()
        assert sheet_io.certs_from_sku_map({}) == frozenset()

    def test_min_length_6(self):
        skus = {"1": "PSA10-12345", "2": "PSA10-123456"}
        out = sheet_io.certs_from_sku_map(skus)
        assert out == frozenset({"123456"})  # 5桁は除外、 6桁のみ


class TestLoadLiveCertSetFromSkus:
    def test_returns_certs_from_cache_skus(self, tmp_path):
        p = tmp_path / "cache.json"
        p.write_text(json.dumps({
            "generated_at": datetime.now().isoformat(),
            "titles": {"358001": "t"},
            "skus": {"358001": "PSA10-150000001"},
        }), encoding="utf-8")
        out = sheet_io.load_live_cert_set_from_skus(cache_path=str(p))
        assert out == frozenset({"150000001"})

    def test_missing_cache_returns_empty_not_raise(self, tmp_path):
        """補完用途なので raise しない (= load_live_itemid_set の fail-closed とは別責務)."""
        p = tmp_path / "nope.json"
        assert sheet_io.load_live_cert_set_from_skus(cache_path=str(p)) == frozenset()

    def test_no_skus_field_returns_empty(self, tmp_path):
        p = tmp_path / "cache.json"
        p.write_text(json.dumps({"titles": {"1": "t"}}), encoding="utf-8")
        assert sheet_io.load_live_cert_set_from_skus(cache_path=str(p)) == frozenset()

    def test_corrupt_json_returns_empty_not_raise(self, tmp_path):
        p = tmp_path / "cache.json"
        p.write_text("{not valid json", encoding="utf-8")
        assert sheet_io.load_live_cert_set_from_skus(cache_path=str(p)) == frozenset()


# ---------------------------------------------------------------------------
# csv_check.check_csv_canonical + existing_cert_set
# ---------------------------------------------------------------------------


COL_CERT = "CDA:Certification Number - (ID: 27503)"


def _write_csv(path: Path, rows: list) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["*Title"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        w.writerows(rows)


def _rwc_dict(k):
    from dedupe.key_format import parse_key
    cat, pid = parse_key(k)
    return {"product_id": pid, "category": cat or ""}


def _rwc_side(keys):
    it = iter(keys)

    def _fn(row, purpose="dedup"):
        return _rwc_dict(next(it))
    return _fn


class TestCheckCsvCanonicalCertMatch:
    """cert 一致は無条件除外 = 依頼書 Q2 の核."""

    def test_cert_match_removes_row(self, tmp_path):
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "dup by cert", COL_CERT: "150000001", "C:Card Number": "OP99-999"},
            {"*Title": "new row",     COL_CERT: "150000999", "C:Card Number": "OP01-002"},
        ])
        with patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side(["one_piece_tcg:OP99-999", "one_piece_tcg:OP01-002"]),
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset(),  # KEY 側は空
                existing_cert_set=frozenset({"150000001"}),
                dry_run=True,
            )
        assert result["removed"] == 1
        assert result["kept"] == 1
        assert result["removed_by_type"] == {"cert": 1, "key": 0}
        assert result["removed_certs"] == ["150000001"]
        # cert 除外 row は KEY 判定を実行しない (= SSOT)、 removed_canonical_keys に載らない
        assert result["removed_canonical_keys"] == []

    def test_no_cert_set_disables_cert_check(self, tmp_path):
        """existing_cert_set=None なら cert 判定 skip (= 既存 KEY 一致 test の互換確認)."""
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "dup", COL_CERT: "150000001", "C:Card Number": "OP07-109"},
        ])
        with patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side(["one_piece_tcg:OP07-109"]),
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset({"one_piece_tcg:OP07-109"}),
                dry_run=True,
            )
        # cert set 未指定 → KEY 一致で除外される (= 従来挙動維持)
        assert result["removed"] == 1
        assert result["removed_by_type"] == {"cert": 0, "key": 1}

    def test_cert_short_circuits_key_check(self, tmp_path):
        """判定順序 cert → KEY: cert で確定した row は KEY 判定を通らない (SSOT)."""
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "dup both", COL_CERT: "150000001", "C:Card Number": "OP07-109"},
        ])
        with patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side(["one_piece_tcg:OP07-109"]),
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset({"one_piece_tcg:OP07-109"}),
                existing_cert_set=frozenset({"150000001"}),
                dry_run=True,
            )
        # 除外は 1 件だけ (重複計上しない、 cert で確定して KEY 判定は実行しない)
        assert result["removed"] == 1
        assert result["removed_by_type"] == {"cert": 1, "key": 0}
        assert result["removed_certs"] == ["150000001"]
        assert result["removed_canonical_keys"] == []

    def test_empty_cert_cell_never_matches(self, tmp_path):
        """CSV row の cert が空欄なら cert 判定 skip (= 空同士のマッチ事故を防ぐ)."""
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "no cert", COL_CERT: "", "C:Card Number": "OP01-002"},
        ])
        with patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side(["one_piece_tcg:OP01-002"]),
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset(),
                existing_cert_set=frozenset({""}),  # 空文字列が入っていても
                dry_run=True,
            )
        assert result["removed"] == 0
        assert result["removed_by_type"] == {"cert": 0, "key": 0}

    def test_mixed_cert_and_key_removals(self, tmp_path):
        """cert 一致 / KEY 一致 / 新規 / unresolved が混在する現実的な CSV.

        note: cert 一致 row (row1) は resolver を呼ばない (short-circuit)。
        よって resolver side_effect は row2..row4 の 3 件分だけ。
        """
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "cert dup",  COL_CERT: "150000001", "C:Card Number": "AAA-001"},
            {"*Title": "key dup",   COL_CERT: "150000999", "C:Card Number": "BBB-002"},
            {"*Title": "new",       COL_CERT: "150000888", "C:Card Number": "CCC-003"},
            {"*Title": "unresolved",COL_CERT: "",           "C:Card Number": ""},
        ])
        with patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side([
                # row1 は cert 短絡 → resolver 呼ばれない (list に入れない)
                "one_piece_tcg:BBB-002",  # row2
                "one_piece_tcg:CCC-003",  # row3
                "",                        # row4 unresolved
            ]),
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset({"one_piece_tcg:BBB-002"}),
                existing_cert_set=frozenset({"150000001"}),
                dry_run=True,
            )
        assert result["total"] == 4
        assert result["removed"] == 2
        assert result["removed_by_type"] == {"cert": 1, "key": 1}
        assert result["removed_certs"] == ["150000001"]
        assert result["removed_canonical_keys"] == ["one_piece_tcg:BBB-002"]
        assert result["kept"] == 2
        assert result["unknown"] == 1

    def test_token_title_partial_match_not_removed(self, tmp_path):
        """依頼書 Q2 / 8/04 GO 済: タイトル token 一致では **落とさない**.

        別セット同番号 (OP05-119 vs OP05-119_PRB01_1) は canonical KEY が別で
        cert も違えば残る = **警告のみ** の位置づけ (= 呼出側の UX 処理)。
        """
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "OP05-119 PRB reprint",  COL_CERT: "999000001",
             "C:Card Number": "OP05-119"},
            {"*Title": "OP05-119 english p8",   COL_CERT: "999000002",
             "C:Card Number": "OP05-119"},
        ])
        # 既存には bare 'OP05-119' がある。 だが resolver は個別に別 KEY 解決するので落ちない。
        with patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side([
                "one_piece_tcg:OP05-119_PRB01_1",
                "one_piece_tcg:OP05-119_p8",
            ]),
        ):
            result = csv_check.check_csv_canonical(
                csv_path=path,
                existing_canonical_keys=frozenset({"one_piece_tcg:OP05-119"}),
                existing_cert_set=frozenset(),
                dry_run=True,
            )
        # token 一致 ("OP05-119" 含む) では落とさない = 警告のみ
        assert result["removed"] == 0
        assert result["removed_by_type"] == {"cert": 0, "key": 0}
        assert result["kept"] == 2


# ---------------------------------------------------------------------------
# checker.run_check_csv_canonical (統合): cert 集約 → 除外 → 台帳書出
# ---------------------------------------------------------------------------


def _fake_ws(values):
    ws = MagicMock()
    ws.get_all_values.return_value = values
    return ws


class TestRunCheckCsvCanonicalWiring:
    """CLI 経路 = HIGH/LOW から cert 集約 + live cache SKU 補完 + check_csv_canonical 実走."""

    def test_cert_removal_via_high_sheet_ends_up_in_ledger_with_type(self, tmp_path):
        """HIGH の R='TCG' × live row の cert を集約 → 同一 cert の候補を除外 → 台帳に種別つき."""
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "PSA10 dup", COL_CERT: "150000001",
             "C:Card Number": "OP07-109"},
        ])

        ws_high = _fake_ws([
            HEADER_HIGH,
            _row_high(item_id="358510552338", cert="150000001", category="TCG", sold="○"),
        ])
        ws_low = _fake_ws([HEADER_HIGH])  # LOW 空
        live_set = frozenset({"358510552338"})

        def _open(sid, client=None):
            m = MagicMock()
            m.worksheet.return_value = ws_high if sid == sheet_io.HIGH_SHEET_ID else ws_low
            return m

        def _find_key(ws):
            return 5 if ws is ws_high else None

        with patch(
            "dedupe.sheet_io.load_live_itemid_set", return_value=live_set
        ), patch(
            "dedupe.sheet_io.authorize_client", return_value=MagicMock()
        ), patch(
            "dedupe.sheet_io.open_spreadsheet", side_effect=_open
        ), patch(
            "dedupe.sheet_io.find_canonical_key_column", side_effect=_find_key
        ), patch(
            "dedupe.sheet_io.load_live_cert_set_from_skus", return_value=frozenset()
        ), patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            return_value=_rwc_dict("one_piece_tcg:OP07-109"),
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=False)

        assert rc == 0
        ledger_path = tmp_path / "in.csv.removed.json"
        assert ledger_path.exists()
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert data["removed"] == 1
        assert data["removed_by_type"] == {"cert": 1, "key": 0}
        assert data["removed_certs"] == ["150000001"]
        assert data["existing_cert_count"] >= 1

    def test_sku_supplement_adds_orphan_cert(self, tmp_path):
        """依頼書 §5 制約: シート itemID が orphan でも live cache SKU から cert 回収 → 除外.

        HIGH シートに該当 cert は無い (orphan)。 だが HQ live cache の SKUs から
        `PSA10-<cert>` を読み込んで補完 → 候補を除外できる。
        """
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "orphan cert dup", COL_CERT: "150000999",
             "C:Card Number": "OP03-100"},
        ])

        ws_high = _fake_ws([HEADER_HIGH])  # HIGH に cert 無し
        ws_low = _fake_ws([HEADER_HIGH])
        live_set = frozenset({"358999999"})  # orphan (シートに row 無い) だが eBay 側 live
        sku_certs = frozenset({"150000999"})  # SKU 補完で回収

        def _open(sid, client=None):
            m = MagicMock()
            m.worksheet.return_value = ws_high if sid == sheet_io.HIGH_SHEET_ID else ws_low
            return m

        with patch(
            "dedupe.sheet_io.load_live_itemid_set", return_value=live_set
        ), patch(
            "dedupe.sheet_io.authorize_client", return_value=MagicMock()
        ), patch(
            "dedupe.sheet_io.open_spreadsheet", side_effect=_open
        ), patch(
            "dedupe.sheet_io.find_canonical_key_column", return_value=None
        ), patch(
            "dedupe.sheet_io.load_live_cert_set_from_skus", return_value=sku_certs
        ), patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            return_value=_rwc_dict("one_piece_tcg:OP03-100"),
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=False)

        assert rc == 0
        ledger_path = tmp_path / "in.csv.removed.json"
        assert ledger_path.exists()
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        # HIGH シート 0 件 + SKU 補完 1 件 = 除外 1 件
        assert data["removed"] == 1
        assert data["removed_by_type"]["cert"] == 1
        assert data["existing_cert_sku_supplement_count"] == 1
        assert "150000999" in data["removed_certs"]

    def test_key_and_cert_both_captured_in_ledger(self, tmp_path):
        """cert と KEY の両方で除外される混在ケース: 台帳に種別内訳が正しく載る."""
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "cert dup", COL_CERT: "150000001", "C:Card Number": "AAA-001"},
            {"*Title": "key dup",  COL_CERT: "999000000", "C:Card Number": "BBB-002"},
            {"*Title": "new",      COL_CERT: "999000001", "C:Card Number": "CCC-003"},
        ])

        ws_high = _fake_ws([
            HEADER_HIGH,
            # HIGH に 既存 KEY と cert の両方あり (別 row でも良い)
            _row_high(item_id="111", cert="150000001", category="TCG"),
            _row_high(item_id="222", cert="", category="TCG"),
        ])
        ws_low = _fake_ws([HEADER_HIGH])
        live_set = frozenset({"111", "222"})

        def _open(sid, client=None):
            m = MagicMock()
            m.worksheet.return_value = ws_high if sid == sheet_io.HIGH_SHEET_ID else ws_low
            return m

        def _find_key(ws):
            # HIGH は E=5 に KEY、 LOW は KEY 列無し
            return 5 if ws is ws_high else None

        # HIGH 111 の E 列に "one_piece_tcg:BBB-002" が入っている想定にする
        ws_high.get_all_values.return_value = [
            HEADER_HIGH,
            ["u1", "111", "t1", "", "one_piece_tcg:BBB-002",
             "", "", "", "150000001",
             "", "", "", "", "", "", "", "",
             "TCG"],
            ["u2", "222", "t2", "", "",
             "", "", "", "",
             "", "", "", "", "", "", "", "",
             "TCG"],
        ]

        with patch(
            "dedupe.sheet_io.load_live_itemid_set", return_value=live_set
        ), patch(
            "dedupe.sheet_io.authorize_client", return_value=MagicMock()
        ), patch(
            "dedupe.sheet_io.open_spreadsheet", side_effect=_open
        ), patch(
            "dedupe.sheet_io.find_canonical_key_column", side_effect=_find_key
        ), patch(
            "dedupe.sheet_io.load_live_cert_set_from_skus", return_value=frozenset()
        ), patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side([
                "one_piece_tcg:AAA-001",  # cert 一致で除外 (KEY 判定は実行しない)
                "one_piece_tcg:BBB-002",  # KEY 一致で除外
                "one_piece_tcg:CCC-003",  # 新規 keep
            ]),
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=False)

        assert rc == 0
        ledger_path = tmp_path / "in.csv.removed.json"
        assert ledger_path.exists()
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert data["removed"] == 2
        assert data["removed_by_type"] == {"cert": 1, "key": 1}
        assert data["removed_certs"] == ["150000001"]
        assert data["removed_canonical_keys"] == ["one_piece_tcg:BBB-002"]

    def test_cache_stale_still_fails_closed(self, tmp_path):
        """cache が LiveCacheError で落ちれば cert 集約に到達せず 非ゼロ exit (= 従来 fail-closed 継続)."""
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "x", COL_CERT: "150000001", "C:Card Number": "AAA-001"},
        ])
        original = path.read_bytes()

        with patch(
            "dedupe.sheet_io.load_live_itemid_set",
            side_effect=sheet_io.LiveCacheError("mock: stale"),
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=False)

        assert rc != 0
        assert path.read_bytes() == original
        assert not (tmp_path / "in.csv.removed.json").exists()
        assert not (tmp_path / "in.csv.bak").exists()


class TestRunCheckCsvCanonicalNoRegressionOnKeyOnly:
    """既存 KEY-only ケース (依頼書 前段の 8/04 GO 済) の挙動が変わっていない."""

    def test_existing_key_only_flow_unaffected(self, tmp_path):
        path = tmp_path / "in.csv"
        _write_csv(path, [
            {"*Title": "dup row", COL_CERT: "",  "C:Card Number": "OP07-109"},
            {"*Title": "new row", COL_CERT: "",  "C:Card Number": "OP99-001"},
        ])
        ws_high = _fake_ws([
            HEADER_HIGH,
            ["u", "358510552338", "existing", "○", "one_piece_tcg:OP07-109",
             "", "", "", "", "", "", "", "", "", "", "", "", "TCG"],
        ])
        ws_low = _fake_ws([HEADER_HIGH])

        def _open(sid, client=None):
            m = MagicMock()
            m.worksheet.return_value = ws_high if sid == sheet_io.HIGH_SHEET_ID else ws_low
            return m

        def _find_key(ws):
            return 5 if ws is ws_high else None

        with patch(
            "dedupe.sheet_io.load_live_itemid_set",
            return_value=frozenset({"358510552338"}),
        ), patch(
            "dedupe.sheet_io.authorize_client", return_value=MagicMock()
        ), patch(
            "dedupe.sheet_io.open_spreadsheet", side_effect=_open
        ), patch(
            "dedupe.sheet_io.find_canonical_key_column", side_effect=_find_key
        ), patch(
            "dedupe.sheet_io.load_live_cert_set_from_skus", return_value=frozenset()
        ), patch(
            "dedupe.resolver_io.resolve_csv_row_with_category",
            side_effect=_rwc_side([
                "one_piece_tcg:OP07-109",
                "one_piece_tcg:OP99-001",
            ]),
        ):
            rc = checker.run_check_csv_canonical(csv_path=str(path), dry_run=False)

        assert rc == 0
        ledger_path = tmp_path / "in.csv.removed.json"
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert data["removed"] == 1
        assert data["removed_by_type"] == {"cert": 0, "key": 1}
        assert data["removed_canonical_keys"] == ["one_piece_tcg:OP07-109"]
