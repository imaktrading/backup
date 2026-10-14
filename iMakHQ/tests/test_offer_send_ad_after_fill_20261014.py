# -*- coding: utf-8 -*-
"""オファーを送る拡張: 広告を外すのは小窓に入れ終わった後 / 小窓が開かなければ1回だけ押し直す (2026-10-14)。

送れなかった2件 (820121669344・820222487994) は「小窓が開かない」で、先に外した広告だけ2日外れたままになった。
"""
import os

JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "sellerhub_grab", "content.js")


def _send_loop():
    s = open(JS, encoding="utf-8").read()
    a = s.index("async function sendOffers(")
    return s[a:s.index("\n  }\n", a)]


def test_ad_is_removed_only_after_dialog_is_filled():
    s = _send_loop()
    assert s.index("fillOffer(item)") < s.index('"/api/offers/prepare"')


def test_retries_once_when_dialog_does_not_open():
    s = _send_loop()
    assert s.count("btn.click()") == 2
    assert '"小窓が開かない"' in s
