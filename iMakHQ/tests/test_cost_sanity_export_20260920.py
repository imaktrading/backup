"""仕入上限の写しが yaml とずれていないか見張る (2026-09-20)。

抽出くんの作業場所には `cost_sanity` が無い (4/25 の古い pricing_engine)。規約上
他の作業場所は読めず、自前で ¥70,000 と書くのも禁止。そこで HQ が共有データ領域に
**写しを置く**ことにした。

★数字を二重に持つと必ずずれる。**このテストが唯一の防波堤**。
  値を決めるのは `iMakeBayAPI/config/global.yaml` の1か所だけ。
"""
import json
import os
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "tools"))
import export_cost_sanity as E                                # noqa: E402


def test_写しが存在する():
    assert os.path.exists(E.OUT), "python iMakHQ/tools/export_cost_sanity.py を実行してください"


def test_写しと_yaml_が一致する():
    """★ずれたらここで落ちる。落ちたら書き出し直すこと。"""
    with open(E.OUT, encoding="utf-8") as f:
        saved = json.load(f)
    now = E.build()
    for k in ("enabled", "max_jpy", "min_jpy", "repdigit_len", "max_ratio_vs_live"):
        assert saved.get(k) == now.get(k), f"{k} がずれています (書き出し直してください)"


def test_出どころが書いてある():
    with open(E.OUT, encoding="utf-8") as f:
        saved = json.load(f)
    assert "global.yaml" in saved.get("_source", "")
    assert "fail-closed" in saved.get("_note", "")        # 無ければ走らない、と書く


def test_自前の数字を持たない():
    """★ここで 70000 と書いたら、値が2か所になる。"""
    src = open(os.path.join(HQ, "tools", "export_cost_sanity.py"), encoding="utf-8").read()
    body = src.split("def build(")[1].split("\ndef ")[0]
    assert "70000" not in body
    assert "config_loader.get_cost_sanity()" in body
