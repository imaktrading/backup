"""sell token の scope 運用 (2026-08-14).

1. 広告 (Promoted Listings) を API で読むため `sell.marketing.readonly` を持つ
2. refresh は **同意済み scope** (token 自身の値) を送る
   — SCOPES を直接送ると、コードに scope を足した瞬間、再同意が済むまで refresh が
     全部落ちる。refresh は eBaymag 配送書換え等が2時間ごとに使う稼働経路。
3. 書込系の広告 scope (`sell.marketing` = readonly でない) は要求しない
"""
import io
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "iMakeBayAPI", "oauth_sell_setup.py")


def _src():
    return io.open(SRC, encoding="utf-8").read()


def test_marketing_readonly_scope_present():
    assert "sell.marketing.readonly" in _src()


def test_marketing_write_scope_present():
    """★2026-08-18 方針変更: 入稿後の「プロモを8%に」を API でやるため **書込も取る**。

    2026-08-14 時点は「読取だけ・誤操作の余地を作らない」だったが、手作業を無くす方が
    価値が高いとユーザーが判断 (同日 同意取得済)。誤操作の防止は scope を持たないことでは
    なく、**道具側の作り**で担保する (ads_add_new_listings: 既定 dry-run / 既存の率は
    書き換えない) → test_ads_add_new_listings_20260818。
    """
    assert '"https://api.ebay.com/oauth/api_scope/sell.marketing",' in _src()


def test_existing_scopes_kept():
    """既存の稼働経路を落とさない (足すだけ・消さない)."""
    src = _src()
    for s in ("sell.analytics.readonly", "sell.fulfillment.readonly",
              "sell.account", "sell.inventory"):
        assert s in src, f"{s} が消えている"


def test_refresh_uses_granted_scope_not_hardcoded_list():
    src = _src()
    assert 'granted = (tok.get("scope") or "")' in src, "refresh が同意済み scope を使っていない"
    # refresh の data に SCOPES を直接埋めていないこと
    i = src.find("def cmd_refresh")
    j = src.find("\ndef ", i + 1)
    body = src[i:j if j > 0 else len(src)]
    assert '"scope": granted' in body
    assert '"scope": " ".join(SCOPES)' not in body, "refresh が SCOPES を直接送っている"
