"""price_ledger (値段変更回数の台帳) のテスト."""
from revise.price_ledger import _UP_OK, build_ledger


def test_counts_only_confirmed_and_usd_rows(tmp_path, monkeypatch):
    import revise.price_ledger as pl
    monkeypatch.setattr(pl, "_review_path", lambda ts: tmp_path / ts)
    reviews = {
        "20260901_043000": [("A", False, 50.0, 45.0, "USD のみ"),          # 下げ
                            ("B", False, 30.0, 30.0, "Policy のみ"),       # 変更なし
                            ("V", True, 20.0, 22.0, "USD+Policy"),         # variation (送れていない)
                            ],
        "20260902_043000": [("A", False, 45.0, 47.0, "USD+Policy"),        # 上げ
                            ("C", False, 10.0, 12.0, ""),                  # 保留 (USD 無し) → 数えない
                            ("V", True, 20.0, 18.0, "USD のみ"),
                            ("V", True, 21.0, 19.0, "USD のみ")],
    }
    runs = {"20260901_043000": {"single"}, "20260902_043000": {"single", "variation"}}
    led = build_ledger(runs, review_reader=lambda p: reviews[p.name],
                       snapshot=("20260902_043500", {"A": 47.0, "D": 9.0}))["items"]
    assert led["A"] == {"changes": 2, "downs": 1, "ups": 1, "first_price": 50.0,
                        "now_price": 47.0, "last_change": "2026-09-02"}
    assert led["B"]["changes"] == 0
    assert led["C"]["changes"] == 0
    assert led["V"]["changes"] == 1 and led["V"]["downs"] == 1 and led["V"]["now_price"] == 18.0
    assert led["D"] == {"changes": 0, "downs": 0, "ups": 0, "first_price": 9.0,
                        "now_price": 9.0, "last_change": None}


def test_log_pattern():
    m = _UP_OK.search("2026-10-01 04:35:55 [daily] UP 成功 [variation価格] revise_variation_price_20261001_043403.csv (attempt 1/3)")
    assert m.group(1) == "variation価格" and m.group(2) == "20261001_043403"
    assert not _UP_OK.search("UP 成功 [variation送料] revise_variation_shipping_20261001_043403.csv")
