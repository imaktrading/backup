# -*- coding: utf-8 -*-
"""仕入値がありえない額なら出品しない (2026-09-03 ユーザー指示で新設)。

## 実害
仕入元 (メルカリ) の出品者が付けたダミー価格 **¥1,111,111** をそのまま拾い、
cost-plus で **$11,707.98** の行を作った。その出品の現在価格は $83.98 で **139倍**。
CSV監査くんも check_csv も「✅ 問題なし」で通した。

## なぜ素通りしたか
2026-08-13 に相場ゲート (market_lookup) を止めた時、**値段を見る門が1つも
残らなかった**。価格の妥当性が相場ゲートに相乗りしていたため。

## 直し方
- 判定は `pricing_engine.cost_sanity` の1か所。しきい値は global.yaml
- 門は **相場の on/off と無関係に常に走る**。API を叩かないので degrade しない
- 門は3枚: ① 再仕入れの入力を作る所 ② CSV監査くん ③ 各カテゴリの check_csv
"""
import io
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (os.path.join(_ROOT, "iMakeBayAPI"), os.path.join(_ROOT, "iMakHQ", "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pricing_engine import cost_sanity            # noqa: E402


# ── 実際に事故った値 ────────────────────────────────────────
def test_the_real_dummy_price_is_rejected():
    """¥1,111,111 = 2026-09-03 に $11,707.98 を作った当の値。"""
    assert cost_sanity(1111111)


def test_the_real_good_prices_pass():
    """同じ走行で正常だった5件は通す (門を締めすぎない)。"""
    for c in (10400, 29999, 15200, 17899, 18899):
        assert cost_sanity(c) is None, c


# ── 形ごとの判定 ────────────────────────────────────────────
def test_zero_and_tiny_are_rejected():
    """取得失敗を0で埋めた行を「タダで仕入れた」と読ませない。"""
    assert cost_sanity(0)
    assert cost_sanity(99)


def test_repdigit_under_the_ceiling_is_rejected():
    """¥111,111 は上限内だが、同じ数字が並ぶ = 売る気のない値段。"""
    assert cost_sanity(111111)


def test_missing_cost_is_not_an_error():
    """仕入値なしは **ここでは** 異常にしない (別経路で落ちる)。嘘の理由を付けない。"""
    assert cost_sanity(None) is None


def test_non_numeric_is_rejected():
    assert cost_sanity("#REF!")


def test_ratio_against_the_live_price():
    """再仕入れ: 現在価格の何倍にもなる = 元データが壊れている合図。

    ★2026-09-04 に上限を 7万 に下げたので、比較には **上限内の値**を使う
    (10万は上限で先に落ちてしまい、倍率の判定を通らない)。
    """
    assert cost_sanity(60000, live_price_usd=15.0)       # 40倍超
    assert cost_sanity(60000, live_price_usd=400.0) is None


# ── 門が実際に閉まるか ──────────────────────────────────────
def test_restock_build_drops_the_row_entirely():
    """再仕入れの入力を作る所で落とす = デスクトップの Revise CSV に載らない。"""
    from psa_restock_build import build_restock_input
    rows = [{"itemID": "1", "cost": 10400, "supply_url": "u1"},
            {"itemID": "2", "cost": 1111111, "supply_url": "u2"},
            {"itemID": "3", "cost": 29999, "supply_url": "u3"}]
    i2c = {"1": "c1", "2": "c2", "3": "c3"}
    i2k = {"1": "K1", "2": "K2", "3": "K3"}
    d, skipped = build_restock_input(rows, i2c, i2k)
    assert d["certs"] == ["c1", "c3"]
    assert "c2" not in d["cost"] and "c2" not in d["forced"]
    assert [s[0] for s in skipped] == ["2"]
    assert "1,111,111" in skipped[0][1]


def test_auditor_gate_does_not_depend_on_the_market_switch():
    """相場を止めた日に値段の門まで消える、を二度とやらない。"""
    src = io.open(os.path.join(_ROOT, "iMakHQ", "tools", "csv_auditor.py"),
                  encoding="utf-8").read()
    i = src.index("cost_bad = cost_sanity_exclusions(")
    j = src.index("deep = with_market")
    # 呼び出しは deep (相場スイッチ) の内側ではなく、合流部で無条件に走る
    assert i > j
    seg = src[j:i]
    assert "cost_sanity_exclusions" not in seg   # deep 側に紛れていない
    assert "exclude_idx.append(idx)" in src[i:i + 700]


def test_all_four_checkers_call_the_shared_rule():
    """カテゴリごとに基準を書かない (基準は check_csv_core の1か所)。"""
    for rel in ("iMakTCG/check_csv.py", "iMakG-shock/check_csv.py",
                "iMakMercari/check_csv.py", "iMak_ichibankuji/check_csv.py"):
        s = io.open(os.path.join(_ROOT, *rel.split("/")), encoding="utf-8").read()
        assert "cost_issues" in s, rel


def test_thresholds_live_in_yaml_not_code():
    """しきい値は global.yaml。コードに数字を書き足さない (呪文①)。"""
    y = io.open(os.path.join(_ROOT, "iMakeBayAPI", "config", "global.yaml"),
                encoding="utf-8").read()
    assert "cost_sanity:" in y
    for k in ("max_jpy", "min_jpy", "repdigit_len", "max_ratio_vs_live"):
        assert k in y, k
