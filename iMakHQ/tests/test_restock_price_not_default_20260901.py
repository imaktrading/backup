# -*- coding: utf-8 -*-
"""再出品くん (RESTOCK fork) の値付け 回帰テスト (2026-09-01)。

実害: 2026-09-01 の ♻ 走行が出した CSV は1行で、価格が **$100.00** だった。
仕入 ¥150,000 / 現行出品 $253.98 のカードで、売れたら大損する値段。

原因: 本家 psa_to_csv には 2026-08-13 に「相場停止 → cost-plus で値付け」が入っているが、
**この fork だけ未適用**だった。価格更新は `if ebay_token:` の中にしか無く、
eBay API のキーが無い走行では丸ごと飛ばされ、DEFAULT_PRICE=$100 のまま CSV になっていた。

規約: 価格は cost-plus (pricing_engine) が SSOT。相場は止まっている。
      **API は価格に一切使わない**。仕入値が無ければ値を推測せず行ごと落とす。
"""
import io
import os
import sys

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_FORK = os.path.join(_ROOT, "iMakTCG", "psa_restock_csv.py")
_MAIN = os.path.join(_ROOT, "iMakTCG", "psa_to_csv.py")


def _src(p):
    return io.open(p, encoding="utf-8").read()


def test_pricing_does_not_depend_on_the_ebay_token():
    """値付けループが token 有りの時だけ走る形に戻っていないこと。"""
    s = _src(_FORK)
    assert "if not ebay_token:" in s, "token が無い時に cost-plus で値付けする経路が無い"
    i = s.index("if not ebay_token:")
    body = s[i:i + 1400]
    assert "_cost_plus_price" in body, "cost-plus の値付けを呼んでいない"
    assert "price_col_idx" in body, "StartPrice を書き換えていない"


def test_market_lookup_gate_is_read_from_yaml():
    """相場を見るかどうかは global.yaml が SSOT (fork が自前で判断しない)。"""
    s = _src(_FORK)
    assert "is_market_lookup_enabled" in s
    assert "load_ebay_keys() if _market_lookup else {}" in s, (
        "相場が止まっている時に eBay のキーを読みに行かないこと")


def test_missing_cost_is_dropped_not_priced_at_100():
    """仕入値が無い行は **$100 で出さず、行ごと落とす** (fail-closed)。"""
    s = _src(_FORK)
    i = s.index("def _cost_plus_price")
    body = s[i:s.index(chr(10) + "    if not ebay_token:", i)]
    assert "return None" in body, "仕入値なしで None を返していない"
    assert "return 100" not in body and "100.00" not in body, "既定価格を返してはいけない"
    assert "no_cost_certs" in s and "if no_cost_certs:" in s, "落とす配線が無い"


def test_default_price_is_never_the_final_price():
    """DEFAULT_PRICE は build_row への種であって、出力価格ではない。

    出力前に必ず上書きされる (= cost-plus か market のどちらか) ことを、
    上書き経路が2つとも在ることで担保する。
    """
    s = _src(_FORK)
    assert "DEFAULT_PRICE = 100.00" in s, "種の定数は在ってよい (build_row の引数)"
    assert s.count("rows[_idx][price_col_idx] = _price") == 1, "cost-plus の上書きが無い"
    assert "if ebay_token:" in s, "相場ありの上書き経路も残っていること"


def test_fork_matches_the_main_generator_rule():
    """本家と同じ規約であること (fork だけ古い、を二度とやらない)。"""
    for p in (_FORK, _MAIN):
        s = _src(p)
        assert "is_market_lookup_enabled" in s, os.path.basename(p) + " に相場ゲートが無い"
        assert "def _cost_plus_price" in s, os.path.basename(p) + " に cost-plus が無い"
