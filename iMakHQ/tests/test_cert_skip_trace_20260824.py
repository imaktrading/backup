# -*- coding: utf-8 -*-
"""枠を選ぶ前に落とした cert の痕跡を残す (2026-08-24 重複くん依頼)。

## なぜ
抽出段のふるいは「目視を減らすための前段」で、判定の権威ではない。件数の print しか
残らないと、**落ちた cert を誰も追えない**。

実害: cert168544559 が目視に出てこない件で、重複くんが「まとめ売り gate の巻き添えでは」
と疑って調査依頼を上げた (2026-08-24)。実際の理由は別 (catalog に画像が無く照合不能) で、
シートを読める出品くんが調べるまで分からなかった。痕跡があれば往復が要らない。

## 何を残すか
    reason  … どのふるいで落ちたか
    certs   … 落とした cert
    detail  … 根拠 ({cert: "連番"} 等)。あとで「なぜ」を人が読める

痕跡は補助なので、**書けなくても抽出は止めない**。
"""
import datetime
import json
import os
import sys

_TCG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "iMakTCG")
if _TCG not in sys.path:
    sys.path.insert(0, _TCG)

import psa_to_csv as P  # noqa: E402

_NOW = datetime.datetime(2026, 8, 24, 9, 0, 0)


def _read(p):
    return [json.loads(l) for l in open(p, encoding="utf-8").read().splitlines() if l.strip()]


def test_records_reason_and_certs(tmp_path):
    p = str(tmp_path / "skips.jsonl")
    assert P.record_cert_skips("multi_card_lot_by_supply_title", ["111", "222"],
                               path=p, now=_NOW) is True
    rec = _read(p)[0]
    assert rec["reason"] == "multi_card_lot_by_supply_title"
    assert rec["certs"] == ["111", "222"]
    assert rec["ts"] == "2026-08-24T09:00:00"
    assert rec["stage"] == "psa_to_csv.extract"


def test_detail_explains_why(tmp_path):
    """「なぜ落ちたか」まで残す。件数だけだと結局人が調べ直しになる。"""
    p = str(tmp_path / "skips.jsonl")
    P.record_cert_skips("multi_card_lot_by_supply_title", ["111", "222"],
                        detail={"111": "連番", "222": "2枚"}, path=p, now=_NOW)
    assert _read(p)[0]["detail"] == {"111": "連番", "222": "2枚"}


def test_detail_is_limited_to_the_certs_dropped(tmp_path):
    """落としていない cert の根拠を混ぜない。"""
    p = str(tmp_path / "skips.jsonl")
    P.record_cert_skips("x", ["111"], detail={"111": "連番", "999": "無関係"},
                        path=p, now=_NOW)
    assert "999" not in _read(p)[0]["detail"]


def test_nothing_written_when_nothing_dropped(tmp_path):
    p = str(tmp_path / "skips.jsonl")
    assert P.record_cert_skips("x", [], path=p) is False
    assert not os.path.exists(p)


def test_appends_instead_of_overwriting(tmp_path):
    """1走行で複数のふるいが働く。前の行を潰さない。"""
    p = str(tmp_path / "skips.jsonl")
    P.record_cert_skips("not_psa10_by_supply_title", ["1"], path=p, now=_NOW)
    P.record_cert_skips("multi_card_lot_by_supply_title", ["2"], path=p, now=_NOW)
    got = _read(p)
    assert [r["reason"] for r in got] == ["not_psa10_by_supply_title",
                                          "multi_card_lot_by_supply_title"]


def test_failure_to_write_does_not_stop_extraction():
    """痕跡は補助。書けなくても抽出は続ける。"""
    assert P.record_cert_skips("x", ["1"], path="Z:/no/such/dir/x.jsonl",
                               print_fn=lambda *_a: None) is False


def test_all_three_entry_gates_record():
    """3つのふるい (二重出品 / PSA10以外 / まとめ売り) が全部 記録を呼ぶこと。"""
    src = open(os.path.join(_TCG, "psa_to_csv.py"), encoding="utf-8").read()
    for reason in ("same_cert_already_listed",
                   "not_psa10_by_supply_title",
                   "multi_card_lot_by_supply_title"):
        assert f'record_cert_skips("{reason}"' in src, reason
