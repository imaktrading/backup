"""オファー判定ツールの回帰 (2026-07-30).

利益計算タブが6つあり、**選び間違えると判断を誤る**。特に US サイトは
バイヤーが米国内か国外かでタブが変わる (関税を払うか払わないか)。
無条件に US計算 で見ると実態より悪く出て、**通せるオファーを落とす**。

★数式はスプレッドシート(v9)の各タブ15行の移植。ここで固定するのは
  「移植した式の骨格」と「値の読み方」。実データとの一致は `offer_calc.py --verify`
  (シートに書いて読み戻す) で担保する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import offer_calc as oc  # noqa: E402

P = {
    "fx": {"USD": 163.45, "EUR": 187.305, "GBP": 218.3245, "AUD": 113.7385, "CAD": 116.42},
    "promo": 0.10, "payo": 0.025, "target": 0.10,
    "cats": {"TCG(PSA10)": {"fvf": 0.1325, "ship": 2000, "hts": 0.18, "split": 1},
             "G-SHOCK": {"fvf": 0.1375, "ship": 2000, "hts": 0.18, "split": 1}},
    "country": {"US": {"tax": 0.085, "intl": 0.0165, "reg": 0},
                "CA": {"tax": 0, "intl": 0.0165, "reg": 0},
                "UK": {"tax": 0.2, "intl": 0.0165, "reg": 0.0045}},
    "gshock": {"US": 0.155, "UK": 0.1375, "その他": 0.1375},
    "shipMode": "FedEx7",
}


def test_us_buyer_pays_duty_so_profit_is_thinner_than_non_us():
    """同じ価格でも **米国内向けは関税ぶん利益が薄い**。ここを取り違えると判断を誤る。"""
    us = oc.calc_py(P, "US計算", "TCG(PSA10)", "US", 100, 1800)
    non_us = oc.calc_py(P, "US計算_非US", "TCG(PSA10)", "US", 100, 1800)
    assert non_us > us, "米国外の方が利益が厚いはず (関税を払わないため)"


def test_ca_beats_uk_at_the_same_revenue():
    """CA は VAT を乗せない = 同じ売上なら手取りが厚い。

    ★通貨が違うので **金額をそのまま比べない**。£100 と C$100 では売上が倍近く違い、
      それで比べると逆の結論が出る (最初これで誤ったテストを書いた)。
      売上(円)が揃う価格に換算してから比べる。
    """
    uk_price = 100.0
    uk_rev = uk_price * 1.2 * P["fx"]["GBP"]            # VAT 込みで eBay を通る額
    ca_price = uk_rev / P["fx"]["CAD"]                  # 同じ売上になる CAD 価格
    ca = oc.calc_py(P, "CA計算", "TCG(PSA10)", "CA", ca_price, 1800)
    uk = oc.calc_py(P, "UK計算", "TCG(PSA10)", "UK", uk_price, 1800)
    assert ca > uk, "同じ売上なら CA の方が手取りが厚いはず"


def test_promo_off_improves_profit():
    """承諾時はプロモを外す運用。外した方が必ず利益が増える (実例で誤判定した経緯あり)。"""
    on = oc.calc_py(P, "CA計算", "TCG(PSA10)", "CA", 100, 1800, promo_on=True)
    off = oc.calc_py(P, "CA計算", "TCG(PSA10)", "CA", 100, 1800, promo_on=False)
    assert off > on


def test_points_reduce_cost():
    """ポイント還元は仕入コストから引く (実質仕入値)。"""
    a = oc.calc_py(P, "CA計算", "TCG(PSA10)", "CA", 100, 1800, pt=0)
    b = oc.calc_py(P, "CA計算", "TCG(PSA10)", "CA", 100, 1800, pt=500)
    assert round(b - a) == 500


def test_gshock_uses_country_override():
    """G-SHOCK は国別の FVF 上書きを使う (US 15.5% など)。"""
    tcg = oc.calc_py(P, "US計算", "TCG(PSA10)", "US", 100, 1800)
    gs = oc.calc_py(P, "US計算", "G-SHOCK", "US", 100, 1800)
    assert gs != tcg, "カテゴリで手数料率が変わっていない"


def test_panel_button_exists():
    """コントロールパネルから開けること (CLI を覚えなくてよい状態を維持)。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "control_panel.py"), encoding="utf-8").read()
    assert "offer_calc.py" in src and "オファー判定" in src
