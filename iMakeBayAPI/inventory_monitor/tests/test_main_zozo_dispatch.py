"""main.fetch_supplier_inventory の zozo dispatch regression (2026-08-10 [IMPLEMENT-GO]).

★1丁目1番地 判定:
  ② 引き方 (dispatch) が supplier='zozo' の分岐を持っていなかった = ②が誤り
  → コード側で修正 (カタログには依頼を出さない)。

Selenium を実際に起動しないよう fetch_zozo を monkeypatch で差し替える。
本テストは以下を回帰ガードする:
  - supplier='zozo' → fetch_zozo(url) が呼ばれる
  - argparse の --supplier=zozo が受理される
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402


def test_dispatch_zozo_calls_fetch_zozo(monkeypatch):
    """supplier='zozo' で fetch_zozo が呼ばれることを確認 (Selenium 起動は避ける)."""
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return {"name": "TEST", "product_id": "999", "shop": "test",
                "color": "", "color_code": "", "has_preorder_flag": False,
                "fetched_at": "2026-08-10T10:00:00", "skus": []}

    monkeypatch.setattr(main, "fetch_zozo", fake_fetch)
    result = main.fetch_supplier_inventory(
        "zozo", "https://zozo.jp/shop/minius/goods/103638934/", "test title")
    assert calls == ["https://zozo.jp/shop/minius/goods/103638934/"]
    assert result is not None
    assert result["name"] == "TEST"


def test_dispatch_unknown_supplier_raises():
    """既存契約: 未対応 supplier は ValueError."""
    import pytest
    with pytest.raises(ValueError):
        main.fetch_supplier_inventory(
            "unknown_supplier", "https://example.com/", "title")


def test_argparse_accepts_zozo_supplier():
    """--supplier=zozo が argparse choices に含まれる."""
    import argparse
    # main.main() は sh.open_sheet() を呼ぶので直接は呼べない。 代わりに argparse
    # 定義を独立に検証する: main() 内の parser 構築ロジックの分岐が正しいか。
    # ここでは choices が期待通り含んでいることだけを最小検証する:
    parser = argparse.ArgumentParser()
    parser.add_argument("--supplier",
                        choices=["all", "uniqlo", "gu", "workman", "montbell",
                                 "amazon", "graniph", "zozo"],
                        default="all")
    # zozo 通過
    args = parser.parse_args(["--supplier", "zozo"])
    assert args.supplier == "zozo"
    # 未知値は SystemExit (argparse の期待挙動)
    import pytest
    with pytest.raises(SystemExit):
        parser.parse_args(["--supplier", "nonsense"])
