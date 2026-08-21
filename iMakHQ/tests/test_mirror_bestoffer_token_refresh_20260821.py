"""長時間ループでトークンを取り直す (2026-08-21).

実害: UK/AU/CA のベストオファー 3,504件を1件ずつ ReviseFixedPriceItem で送ったところ、
2時間を超えて最初のトークンが失効し **1,717件が丸ごと失敗** した
(`IAF token supplied is expired`)。取り直す作りになっていなかった。
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")
import mirror_promo_bestoffer as M  # noqa: E402


class FakeFx:
    def __init__(self):
        self.n = 0

    def token(self):
        return "tok%d" % self.n

    def refresh(self):
        self.n += 1


def test_token_is_reused_while_fresh():
    fx = FakeFx()
    t = M.TradingToken(fx)
    assert t.get() == "tok0"
    assert t.get() == "tok0"
    assert t.refreshed == 0


def test_token_is_refreshed_when_old():
    """★本命: 一定時間が経ったら自分で取り直す."""
    fx = FakeFx()
    t = M.TradingToken(fx)
    t.at = time.time() - M.TOKEN_MAX_AGE_SEC - 1
    assert t.get() == "tok1"
    assert t.refreshed == 1


def test_force_refresh_gets_a_new_one():
    fx = FakeFx()
    t = M.TradingToken(fx)
    t.force()
    assert t.get() == "tok1"


def test_max_age_is_well_under_two_hours():
    """~2h 有効なので、余裕を持って短くしておくこと."""
    assert 0 < M.TOKEN_MAX_AGE_SEC <= 60 * 60


def test_expired_message_is_detected():
    assert M._is_token_error("NG: IAF token supplied is expired.")
    assert M._is_token_error("NG: Auth token is invalid.")


def test_other_errors_are_not_treated_as_token_error():
    """失効以外を失効と誤認すると、無駄に取り直して同じ失敗を繰り返す."""
    assert not M._is_token_error("OK")
    assert not M._is_token_error("NG: System error. Unable to process your request.")
    assert not M._is_token_error("")


def test_loop_refreshes_and_retries_once_on_expiry():
    """失効を掴んだら その場で取り直して1回やり直す (次の周回に送らない)."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools",
                            "mirror_promo_bestoffer.py"), encoding="utf-8").read()
    assert "if _is_token_error(res):" in src
    assert "trading.force()" in src
    assert "res = enable_best_offer(fx, trading.get(), key, i)" in src


def test_progress_is_recorded_per_item():
    """途中で落ちても どこまで済んだか残す."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools",
                            "mirror_promo_bestoffer.py"), encoding="utf-8").read()
    assert "_log_progress(key, i, res)" in src


# ---- ベストオファーの状態は GetSellerList で見る (2026-08-21) ----
# ActiveList は BestOfferEnabled を返さない。それに気づかず全件「付いていない」と判定し、
# 毎回 3,504件を送り直す作りになっていた (前回 1,787件は実際には成功済みだった)。

def _items(n=2):
    return [{"item_id": "1", "site": "uk", "best_offer": False, "title": ""},
            {"item_id": "2", "site": "uk", "best_offer": False, "title": ""}][:n]


def test_bo_state_overrides_activelist():
    """状態表がある時は そちらを真とする."""
    got = M.plan(_items(), advertised=set(), only="uk", bo_state={"1": True, "2": False})
    assert got["uk"]["bo"] == ["2"]
    assert got["uk"]["bo_exists"] == 1


def test_unknown_item_is_treated_as_needing_it():
    """表に無い = 分からない → 付ける側に倒す (付け直しは無害・付け漏れは機会損失)."""
    got = M.plan(_items(), advertised=set(), only="uk", bo_state={"1": True})
    assert got["uk"]["bo"] == ["2"]


def test_without_state_table_falls_back_to_item_flag():
    """状態表を渡さない旧来の呼び方も壊さない."""
    its = _items()
    its[0]["best_offer"] = True
    got = M.plan(its, advertised=set(), only="uk")
    assert got["uk"]["bo"] == ["2"] and got["uk"]["bo_exists"] == 1


def test_state_fetch_uses_getsellerlist_not_activelist():
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools",
                            "mirror_promo_bestoffer.py"), encoding="utf-8").read()
    i = src.find("def fetch_best_offer_state")
    assert i > 0
    body = src[i:i + 2000]
    assert "GetSellerList" in body
    assert "GranularityLevel" in body


def test_duplicate_item_ids_are_dropped():
    """ActiveList が同じ出品を複数ページに返す。重複のまま bulk API に渡すと
    `errorId 35018 duplicate listing` でチャンク丸ごと 400 になり1件も追加されない."""
    dup = [{"item_id": "1", "site": "uk", "best_offer": False, "title": ""},
           {"item_id": "1", "site": "uk", "best_offer": False, "title": ""},
           {"item_id": "2", "site": "uk", "best_offer": False, "title": ""}]
    got = M.plan(dup, advertised=set(), only="uk", bo_state={})
    assert got["uk"]["bo"] == ["1", "2"]
    assert got["uk"]["promo"] == ["1", "2"]


def test_ads_are_chunked_and_missing_responses_are_ng():
    src = open(os.path.join(os.path.dirname(__file__), "..", "tools",
                            "mirror_promo_bestoffer.py"), encoding="utf-8").read()
    assert "ADS_CHUNK" in src
    i = src.find("def add_ads")
    body = src[i:i + 2200]
    assert "for k in range(0, len(item_ids), ADS_CHUNK)" in body
    assert "応答に含まれず" in body, "返ってこなかった分を成功に数えている"
