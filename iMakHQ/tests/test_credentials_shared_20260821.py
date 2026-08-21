# -*- coding: utf-8 -*-
"""鍵とトークンの場所は1か所で決める (2026-08-21 カタログ依頼).

★eBay のトークンは使うたびに更新されて書き戻される。2か所に置いたまま
  片方だけ更新されると腐る。同じ日に「変換表が2か所にあって片方だけ直る」で
  1日つぶしたのと同じ形。

決まり: 共有 `C:/dev/iMak_data/credentials/` が本物 / 無ければ従来の場所 /
       両方あって中身が違えば **警告する** (黙って古い方を使わない)。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, r"C:\dev\iMak\iMakeBayAPI")

import credentials as C                                        # noqa: E402


class TestPick:
    def _pick(self, has_s, has_l, same, warns):
        return C.pick("S", "L",
                      lambda p: has_s if p == "S" else has_l,
                      lambda p: "x" if (same or p == "S") else "y",
                      warns.append)

    def test_共有があれば共有(self):
        w = []
        assert self._pick(True, True, True, w) == "S" and not w

    def test_中身が違えば警告して共有を使う(self):
        """★黙って古い方に落ちない。落ちると腐ったトークンで動き続ける."""
        w = []
        assert self._pick(True, True, False, w) == "S"
        assert w and "2か所" in w[0]

    def test_共有が無ければ従来(self):
        w = []
        assert self._pick(False, True, True, w) == "L"

    def test_どちらも無ければ共有を返す(self):
        """エラーは呼び出し側で出す (ここで握り潰さない)."""
        assert self._pick(False, False, True, []) == "S"


class TestPaths:
    def test_共有を見ている(self):
        for p in (C.keys_path(), C.token_path("sell"), C.token_path("trading")):
            assert p.replace("\\", "/").startswith(C.SHARED_DIR), p

    def test_知らない種類は例外(self):
        """推測でファイル名を作らない."""
        import pytest
        with pytest.raises(ValueError):
            C.token_path("unknown")

    def test_鍵が読める(self):
        k = C.ebay_keys()
        assert k.get("AppID") and k.get("AppSecret")


class TestSingleSource:
    """★2026-08-21 夜: 全 worktree が共有側を見たので、本体側のファイルを消して
    二重書きもやめた。書き先が2か所に戻ったら、いつか片方だけ古くなる."""

    def test_本体側にファイルが無い(self):
        for n in ("ebay keys.txt", "ebay_oauth_token_sell.json", "ebay_oauth_token.json"):
            p = os.path.join(r"C:\dev\iMak\iMakeBayAPI", n)
            assert not os.path.exists(p), "本体側に残っている: " + p

    def test_書き先は1か所だけ(self):
        import io as _io
        src = _io.open(r"C:\dev\iMak\iMakeBayAPI\oauth_sell_setup.py", encoding="utf-8").read()
        body = src[src.index("def save_token"):src.index("def basic_auth")]
        assert "_token_path" in body
        assert "for path in" not in body, "二重書きに戻っている"


class TestParse:
    def test_key_value形式(self):
        assert C.parse_keys("AppID=a\nAppSecret=b\n# comment\n") == {"AppID": "a", "AppSecret": "b"}

    def test_空でも壊れない(self):
        assert C.parse_keys("") == {} and C.parse_keys(None) == {}


class TestCallers:
    """★参照先を戻したら気づけるようにする (カタログ依頼の主旨)."""

    def test_主要な呼び出しが自前でパスを組み立てていない(self):
        import io
        for rel in ("iMakeBayAPI/check_csv_core.py", "iMakeBayAPI/ebay_sold_finder.py",
                    "iMakeBayAPI/ebay_getitem_images.py", "iMakeBayAPI/oauth_sell_setup.py",
                    "iMakeBayAPI/fix_de_speedpak_shipping.py",
                    "iMakHQ/tools/ads_add_new_listings.py", "iMakHQ/tools/ads_coverage.py",
                    "iMakHQ/control_panel.py", "iMakG-shock/check_csv.py"):
            p = os.path.join(r"C:\dev\iMak", rel.replace("/", os.sep))
            src = io.open(p, encoding="utf-8").read()
            assert "credentials import" in src, rel
