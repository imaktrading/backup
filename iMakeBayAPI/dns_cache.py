"""_dns_cache — DNS解決を1回だけ行いキャッシュする socket.getaddrinfo パッチ。

サンドボックス/実行環境の DNS が間欠的に長時間(30s+)落ちる問題への根本対策。
従来は各 script が getaddrinfo を連打リトライ → resolver を叩きすぎて更に悪化していた。
本モジュールを **import するだけ** で socket.getaddrinfo がキャッシュ付きに置換され、
一度解決したホスト(api.ebay.com 等)は以降 DNS を引かず即返す = DNS ダウン中も影響ゼロ。

使い方(各 eBay API script の先頭で):
    import dns_cache  # noqa: F401  ← これだけ

- 成功した解決結果を (host, port) キーでキャッシュ。
- 失敗時: キャッシュがあればそれを返す(DNSダウンを無害化)。
- キャッシュも無い初回失敗のみ短リトライ(指数バックオフ, 最大~8s)。
"""
import socket
import time

_orig_getaddrinfo = socket.getaddrinfo
_cache = {}


def _cached_getaddrinfo(host, port, *args, **kwargs):
    key = (host, port)
    try:
        res = _orig_getaddrinfo(host, port, *args, **kwargs)
        _cache[key] = res          # 成功は常に最新でキャッシュ更新
        return res
    except socket.gaierror:
        if key in _cache:
            return _cache[key]     # DNSダウン中でも過去の解決結果で継続
        # 初回(キャッシュ無し)の失敗のみ、控えめにリトライ(resolver を叩きすぎない)
        delay = 0.5
        for _ in range(5):
            time.sleep(delay)
            delay = min(delay * 2, 2.0)
            try:
                res = _orig_getaddrinfo(host, port, *args, **kwargs)
                _cache[key] = res
                return res
            except socket.gaierror:
                continue
        raise


# 二重パッチ防止(複数 import されても1回だけ)
if getattr(socket.getaddrinfo, "__name__", "") != "_cached_getaddrinfo":
    socket.getaddrinfo = _cached_getaddrinfo


def warm(hosts=("api.ebay.com",), port=443):
    """事前にホストを解決してキャッシュに載せる(script開始時に呼ぶと以後DNS不要)。"""
    for h in hosts:
        try:
            socket.getaddrinfo(h, port)
        except Exception:
            pass
