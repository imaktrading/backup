"""補充の対象から外した出品は、毎回「台帳に行が無い」と出さない (2026-09-18)。

ユーザー判断「その4件はサヨナラしよう」。7〜8月に売れた古い出品で、SKU が旧形式のため
最初からシートに行が無く、仕入元も分からないので補充できない。注文APIは90日ぶん返すので、
放っておくと毎回 同じ4件が出続ける。
"""
import io
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
from sold_restock import load_retired, RETIRED_PATH


def test_コメントと空行は読み飛ばす(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text("# 覚え書き\n\n358785561911  # 理由\n358783687909\n", encoding="utf-8")
    assert load_retired(str(p)) == {"358785561911", "358783687909"}


def test_ファイルが無ければ空_従来どおり全部出す(tmp_path):
    assert load_retired(str(tmp_path / "ない.txt")) == set()


def test_本番の一覧に4件が入っている():
    got = load_retired(RETIRED_PATH)
    for iid in ("358785561911", "358785693929", "358841114399", "358783687909"):
        assert iid in got, f"{iid} が対象外リストに無い"
