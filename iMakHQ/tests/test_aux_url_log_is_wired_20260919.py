"""補URL の書込は必ず台帳に残ること (2026-09-19)。

aux_url_log.py は 2026-09-08 に作られていたが **一度も呼ばれておらず**、台帳ファイルすら
出来ていなかった。そのため「補URLが消えて同じ候補がまた出る」(itemID 820041238874) を
追った時、9/16 に3本あった補が1本に減った経緯を誰も辿れなかった。
"""
import os

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
SRC = open(os.path.join(TOOLS, "sheet_io.py"), encoding="utf-8").read()


def test_write_aux_urls_が台帳を呼ぶ():
    body = SRC.split("def write_aux_urls(")[1].split("\ndef ")[0]
    assert "aux_url_log" in body, "補URL の書込が台帳を呼んでいない"
    assert ".record(" in body


def test_記録の失敗で書込を止めない():
    body = SRC.split("def write_aux_urls(")[1].split("\ndef ")[0]
    i = body.index("aux_url_log")
    assert "except Exception" in body[i:i + 400]      # 記録は本業ではない
