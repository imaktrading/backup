"""profit_params の Excel フォールバック廃止を守る回帰テスト (2026-07-31).

背景:
  Excel (`iMakHQ/sheets/【NEW】利益計算シート_v2.xlsx`) は 2026-04-25 baseline から更新が
  止まっているのに `_load()` の chain で **yaml(SSOT) より先に return** していた。
  creds を持たない worktree は yaml に到達できず Excel を掴み、カテゴリ名が
  `Montbell(一般)/(ジャケット)` (yaml/コードは `Montbell(軽)/(重)`) だったため
  `get_category_params("Montbell(重)") is None` → import 時 TypeError で落ちていた。

  = 埋もれた第二 SSOT。復活させないことをテストで固定する。
"""
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "iMakeBayAPI"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import profit_params  # noqa: E402


def test_excel_loader_is_gone():
    """Excel loader そのものが存在しないこと (関数を戻すと落ちる)."""
    assert not hasattr(profit_params, "_load_from_excel"), (
        "Excel フォールバックが復活している。第二 SSOT になるので chain に戻さないこと"
    )
    assert not hasattr(profit_params, "SPREADSHEET"), (
        "Excel の path 定数が復活している"
    )


def test_fallback_is_yaml_not_excel(monkeypatch):
    """GSheet も cache も使えない環境で、fallback が yaml になること."""
    monkeypatch.setattr(profit_params, "_cache", None, raising=False)
    monkeypatch.setattr(profit_params, "_load_local_cache", lambda allow_stale=False: None)
    monkeypatch.setattr(profit_params, "_load_from_gsheet", lambda: None)

    cache = profit_params._load()
    assert cache["source"] == "fallback", f"yaml fallback に落ちていない: {cache['source']}"


@pytest.mark.parametrize("category", ["Montbell(軽)", "Montbell(重)"])
def test_yaml_category_names_resolve_in_fallback(monkeypatch, category):
    """yaml/コードが使うカテゴリ名が fallback 経路で必ず引けること.

    ここが None を返すと `iMakMercari/montbell_listing.py:368` が import 時に落ちる。
    """
    monkeypatch.setattr(profit_params, "_cache", None, raising=False)
    monkeypatch.setattr(profit_params, "_load_local_cache", lambda allow_stale=False: None)
    monkeypatch.setattr(profit_params, "_load_from_gsheet", lambda: None)

    params = profit_params.get_category_params(category)
    assert params is not None, f"{category} が fallback で引けない (第二 SSOT 混入の兆候)"
    assert params["shipping_jpy"] > 0
    assert 0 < params["fvf"] < 1


def test_montbell_listing_imports_without_creds(monkeypatch):
    """PROFIT_CATEGORY が module top-level で解決できること (collection error の再発防止)."""
    monkeypatch.setattr(profit_params, "_cache", None, raising=False)
    monkeypatch.setattr(profit_params, "_load_local_cache", lambda allow_stale=False: None)
    monkeypatch.setattr(profit_params, "_load_from_gsheet", lambda: None)

    mercari_dir = Path(__file__).resolve().parent.parent / "iMakMercari"
    src = (mercari_dir / "montbell_listing.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        if line.startswith("PROFIT_CATEGORY"):
            category = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
    else:
        pytest.skip("montbell_listing.py に PROFIT_CATEGORY が無い")

    assert profit_params.get_category_params(category) is not None, (
        f"montbell_listing.py の PROFIT_CATEGORY={category!r} が profit_params で引けない"
    )
