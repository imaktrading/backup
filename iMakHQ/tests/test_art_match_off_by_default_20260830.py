# -*- coding: utf-8 -*-
"""絵柄の自動判定は既定オフ (2026-08-30 ユーザー確定)。

「目視したらいいだけなら、無駄な課金はやめたい」「悩むときは、個別に聞くわ」

- 新しい判定はしない (API を叩かない = 課金しない)
- **判定済みキャッシュ (1,544組) は enabled と無関係に使う** = 無料で効き続ける
- 止めていることが画面で分かるように、理由に「停止中」を入れて返す
  (黙って消えると切れていることに気づけない。8/2〜8/30 に実際そうなった)
- 悩んだ時の1件だけは `--pair` で回せる (この呼び方は既定オフを無視する)

止めると候補が約25%多く並ぶ (実測: 判定済み1,544組のうち different 388組)。
"""
from __future__ import annotations

import io
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))

import psa_art_match as A                                          # noqa: E402


def _cfg(tmp_path, body):
    p = tmp_path / "global.yaml"
    io.open(p, "w", encoding="utf-8").write(body)
    return str(p)


class TestSwitch:
    def test_既定はオフ(self, tmp_path):
        assert A.art_match_enabled(_cfg(tmp_path, "other: 1\n")) is False

    def test_yamlでオンにできる(self, tmp_path):
        assert A.art_match_enabled(_cfg(tmp_path, "art_match:\n  enabled: true\n")) is True

    def test_yamlが読めなければオフ(self):
        # 迷ったら課金しない側
        assert A.art_match_enabled("/no/such/file.yaml") is False


class TestNoChargeWhenOff:
    def test_APIを叩かずに返す(self, monkeypatch):
        called = []
        monkeypatch.setattr(A, "art_match_enabled", lambda *a, **k: False)
        monkeypatch.setattr(A, "_load_key", lambda: called.append(1) or "dummy")
        r = A.compare_art("https://x/a.jpg", "https://x/b.jpg")
        assert r["verdict"] == "unsure"
        assert "停止中" in r["reason"]        # 黙って消さない
        assert not called                     # キーすら読まない = 課金経路に入らない

    def test_キャッシュが在ればオフでも使う(self, monkeypatch):
        monkeypatch.setattr(A, "art_match_enabled", lambda *a, **k: False)
        k = A._cache_key("https://x/a.jpg", "https://x/b.jpg", "")
        cache = {k: {"verdict": "different", "reason": "構図が違う"}}
        r = A.compare_art("https://x/a.jpg", "https://x/b.jpg", cache=cache)
        assert r["verdict"] == "different" and r["cached"] is True
