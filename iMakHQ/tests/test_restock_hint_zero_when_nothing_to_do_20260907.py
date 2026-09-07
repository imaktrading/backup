"""①②③ の残数は「押せば進む件数」。進まないものは 0 にする (2026-09-07 ユーザー指示).

> であれば、残数は０で、黒文字やろ。主旨を理解しろ

②は cert の有無しか見ておらず、**生成に回らない行を「押せば出る」と数えていた**
(仕入値 ¥132,500 が上限超えで生成不可なのに 1件と表示)。
さらに「CSV は作れるが上げられない」行 (カタログで同定できず必須項目が空) も数え続け、
押しても永久に進まない 1件が残っていた。
"""
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import psa_restock_build as B  # noqa: E402

ROWS = [["itemID", "最安¥", "仕入URL", "RESTOCK状態"],
        ["111", "1000", "u1", "入稿待ち(qty=0)"],
        ["222", "999999", "u2", "入稿待ち(qty=0)"],      # 仕入値が上限超え
        ["333", "3000", "u3", "入稿待ち(qty=0)"]]
CERTS = {"111": "c1", "222": "c2", "333": "c3"}


def test_cost_over_cap_is_not_actionable():
    """生成に回らない行 (仕入値 上限超え) は「押せば出る」に数えない."""
    w = B.count_workload(ROWS, itemid_to_cert=CERTS)
    assert w["actionable"] == 2, w
    assert w["blocked"] == 1, w


def test_undeliverable_rows_are_blocked(tmp_path, monkeypatch):
    """CSV は作れるが上げられないと分かっている行も 0 側に置く."""
    led = tmp_path / "nd.json"
    led.write_text(json.dumps({"111": "カタログで同定できない"}), encoding="utf-8")
    monkeypatch.setattr(B, "_UNDELIVERABLE", str(led))
    monkeypatch.setattr(B, "undeliverable", lambda path=str(led): json.loads(
        led.read_text(encoding="utf-8")))
    w = B.count_workload(ROWS, itemid_to_cert=CERTS)
    assert w["actionable"] == 1, w
    assert w["blocked"] == 2, w


def test_mark_and_read_roundtrip(tmp_path):
    p = tmp_path / "nd.json"
    B.mark_undeliverable("999", "理由", path=str(p))
    assert B.undeliverable(str(p)) == {"999": "理由"}


def test_hint_uses_the_same_gate_as_the_button():
    """数える側が本体 (build_restock_input) を通していること = 弾く理由が増えても付いてくる."""
    src = (TOOLS / "psa_restock_build.py").read_text(encoding="utf-8")
    i = src.index("def count_workload(")
    body = src[i:src.index("\ndef ", i + 10)]
    assert "build_restock_input(" in body
