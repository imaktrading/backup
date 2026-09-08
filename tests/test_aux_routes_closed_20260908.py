# -*- coding: utf-8 -*-
"""補URL に **機械が勝手に書かない** (2026-09-08 ユーザー指示)。

    「勝手に補に追加するルートは閉じて、必ず目視を通る様にして」

2026-09-08 に「補URLが別のカードで、そのぶん安く出品されていた」事故が3件出た。
3件ともバイヤーの問い合わせ・オファーで発覚し、**どこから入ったかログから特定できなかった**
(補URLを書く経路は4つあり、3つは URL をログに出していない)。

自動経路は KEY (版まで含む) が一致する行から URL を配る。理屈は正しいが、
**元の行の KEY が誤っていれば誤った版を配る** (KEY 取り違えは 2026-09-07 に実在)。
同じ番号の別版は商品名で見分けが付かない (ST10-006 は版が8つあり全部 SR)。
"""
import os
import re
import sys

_TOOLS = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "iMakHQ", "tools"))
sys.path.insert(0, _TOOLS)

import aux_pending          # noqa: E402
import aux_url_log          # noqa: E402


def test_queue_skips_urls_already_on_the_sheet():
    """既に入っている URL は積まない (同じものを二度 目視に出さない)。"""
    rows = aux_pending.build_rows(
        {10: ["https://x/1", "https://x/2"]}, "テスト",
        existing_by_row={10: ["https://x/1"]})
    assert [r["url"] for r in rows] == ["https://x/2"]


def test_queue_keeps_who_and_when():
    rows = aux_pending.build_rows({10: ["https://x/1"]}, "2枚目の自動追記",
                                  item_of={10: "820000000001"}, today="2026-09-08")
    assert rows[0]["source"] == "2枚目の自動追記"
    assert rows[0]["itemID"] == "820000000001" and rows[0]["date"] == "2026-09-08"


def test_queue_ignores_blanks():
    assert aux_pending.build_rows({10: ["", "  "]}, "テスト") == []


def _src(name):
    return open(os.path.join(_TOOLS, name), encoding="utf-8").read()


def test_dupes_route_queues_instead_of_writing():
    """2枚目の自動追記: シート書込の前に目視待ちへ逃がしている。"""
    s = _src("hoju_url_from_dupes.py")
    assert "aux_pending" in s
    m = re.search(r'if os\.environ\.get\("AUX_AUTO_WRITE"\) != "1":(.{0,900})', s, re.S)
    assert m, "自動書込を止める分岐が無い"
    seg = m.group(1)
    assert "queue(" in seg, "目視待ちに積んでいない"
    # 分岐の中で抜けている = その下の write_aux_urls に落ちない
    assert re.search(r"\n\s+return\b", seg), "分岐から抜けていない (書込に落ちる)"


def test_newcand_aux_route_queues_instead_of_writing():
    """捨てた候補の転記 (夜間) も同じ。"""
    s = _src("psa_hoju_fill.py")
    assert "aux_pending" in s
    i = s.find('if os.environ.get("AUX_AUTO_WRITE") != "1":')
    assert i > 0
    assert "queue(" in s[i:i + 700]


def test_escape_hatch_is_documented():
    """元に戻す口を残す (止めたことを忘れて『なぜ増えない』と悩まないため)。"""
    for f in ("hoju_url_from_dupes.py", "psa_hoju_fill.py"):
        assert "AUX_AUTO_WRITE=1" in _src(f)


def test_write_log_records_source_and_url():
    """誰が入れたかを残す。今回これが無くて特定できなかった。"""
    recs = aux_url_log.build_records({10: ["https://x/1"]}, "目視", today="2026-09-08",
                                     item_of={10: "820000000001"})
    assert recs[0]["source"] == "目視" and recs[0]["url"] == "https://x/1"
    assert recs[0]["n"]           # 突合キー (正規化URL)


def test_source_of_returns_the_last_writer():
    recs = (aux_url_log.build_records({1: ["https://x/1"]}, "自動", today="2026-09-01")
            + aux_url_log.build_records({2: ["https://x/1"]}, "目視", today="2026-09-08"))
    assert aux_url_log.source_of("https://x/1", recs)["source"] == "目視"


def test_pending_is_consumed_after_being_shown():
    """見せた分は待ち行列から外す。外さないと毎回同じものが並ぶ。"""
    import json
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "pending.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        for r in ({"itemID": "1", "url": "https://x/1"},
                  {"itemID": "1", "url": "https://x/2"},
                  {"itemID": "2", "url": "https://x/3"}):
            f.write(json.dumps(r) + "\n")
    assert aux_pending.consume([("1", "https://x/1")], path=p) == 1
    left = [r["url"] for r in aux_pending.load(p)]
    assert left == ["https://x/2", "https://x/3"]


def test_consume_is_a_no_op_when_nothing_matches():
    import json
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "pending.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"itemID": "1", "url": "https://x/1"}) + "\n")
    assert aux_pending.consume([("9", "https://x/9")], path=p) == 0
    assert len(aux_pending.load(p)) == 1


def test_review_screen_merges_the_pending_queue():
    """積んだだけでは補URLが増えない。目視画面に合流していること。"""
    s = _src("psa_hoju_fill.py")
    assert "_pending_by_iid" in s and "目視待ち" in s
    assert "aux_pending.consume(_shown_pending)" in s


def test_pending_needs_a_reference_image():
    """現物画像が無い行には混ぜない (見比べる相手が無いと判定できない)。"""
    s = _src("psa_hoju_fill.py")
    assert "if _pend and ref:" in s
