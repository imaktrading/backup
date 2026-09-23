"""モンベル公式アウトレット巡回のボタンは止めている (2026-09-24 ユーザー指示「今はやってないから停止」)。
既存行を行ごと書き直して B列・価格・取下げ印を空で上書きする疑いがあるので、直すまで戻さない。"""
import os
import re

SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control_panel.py"),
           encoding="utf-8").read()


def test_montbell_outlet_button_is_not_active():
    active = [ln for ln in SRC.splitlines()
              if re.search(r'"cmd":\s*\[.*montbell_outlet_scraper', ln) and not ln.lstrip().startswith("#")]
    assert active == []
