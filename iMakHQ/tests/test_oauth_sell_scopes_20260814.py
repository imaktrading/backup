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


def test_marketing_write_scope_not_requested():
    """読取だけでよい。広告の書換え権限は取らない (誤操作の余地を作らない)."""
    src = _src()
    for line in src.splitlines():
        s = line.strip()
        if not s.startswith('"https://api.ebay.com/oauth/api_scope/sell.marketing'):
            continue
        assert "readonly" in s, f"広告の書込 scope を要求している: {s}"


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
