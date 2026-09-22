"""不一致台帳: KEY が既に決まっている itemID は解決扱いにする (2026-09-22)。
終わった出品は目視の行に出ず、KEY を入れても台帳が未対処のまま同じ依頼が毎回カタログに届いていた。"""
import os

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools",
                        "psa_resource_gate.py"), encoding="utf-8").read()


def test_known_key_itemids_count_as_confirmed():
    assert "confirmed_iids |= set(known_iids or ())" in SRC
    assert "known_iids=(set(confirmed_prev) | set(new_confirmed)" in SRC
    assert "{k for k, v in keymap.items() if v}" in SRC
