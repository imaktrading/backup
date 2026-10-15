# -*- coding: utf-8 -*-
"""SpeedPAK の送料を読むために開いた CPaSS のタブは、開いてから3分で必ず閉じる (2026-10-15 ユーザー
「誰かが Cpass を開けて閉じてない。開けたら閉じるように」)。読めない時 (ログイン切れ等) にタブが残っていた。"""
import json
import os

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "sellerhub_grab")


def test_cpass_tab_is_closed_by_alarm():
    bg = open(os.path.join(D, "background.js"), encoding="utf-8").read()
    assert 'chrome.alarms.create("imak-ship-close-"' in bg
    assert "chrome.alarms.onAlarm.addListener" in bg and "chrome.tabs.remove" in bg
    assert "alarms" in json.load(open(os.path.join(D, "manifest.json"), encoding="utf-8"))["permissions"]
