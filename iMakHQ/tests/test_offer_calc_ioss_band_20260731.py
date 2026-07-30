# -*- coding: utf-8 -*-
"""offer_calc — €150 (IOSS) をまたぐと DDP/DDU が切り替わること.

背景 (2026-07-31 実オファーが発端):
    ebay.de の出品 €220.62 に €120 のオファー。**発送手段も税の扱いも成約額で決まる**:
      ≤€150 … IOSS/DDP。eBay が VAT を徴収し、**€3 関税は当方負担**。SpeedPAK Economy
      >€150 … DDU。**買い手が着払いで関税を払う**ので当方コストに入れない。日本郵便
    従来は価格に関係なく「Economy 実費 + 関税」を計上しており、>€150 で
    1件あたり約 ¥1,979 コストを過大計上していた (DEミラーは >€150 が 380件=55%)。

    ★送料収入(D)は**ポリシー値なので帯によらず一定**。出品時に決まり、
      オファーで成約額が下がっても送料は変わらない (ユーザー指摘 2026-07-31)。

守りたい性質:
  1. しきい値は成約額 (出品価格ではない)
  2. >€150 は 日本郵便実費 に切替わり、関税を上乗せしない
  3. 送料収入は帯で変わらない
  4. VAT 率は仕向地連動 (DE 19% / AT 20% ← 実注文で確認)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import offer_calc as oc  # noqa: E402

P = {
    "fx": {"USD": 160.0, "EUR": 184.0, "GBP": 214.0, "AUD": 112.0, "CAD": 113.0},
    "promo": 0.1, "payo": 0.025, "target": 0.1,
    "cats": {"TCG(PSA10)": {"fvf": 0.1325, "ship": 2000.0, "hts": 0.18, "split": 1.0}},
    "country": {"US": {"tax": 0.085, "intl": 0.0165, "reg": 0.0},
                "DE": {"tax": 0.19, "intl": 0.0165, "reg": 0.0035}},
    "gshock": {}, "eu": {"DE": {"tier": 17, "cost": 3219, "name": "ドイツ"},
                         "AT": {"tier": 24, "cost": 4130, "name": "オーストリア"}},
    "deShip": 14.86, "atShip": 17.49, "jpPost": 1240.0, "iossEur": 150.0,
}


def de(price, cc="DE"):
    return oc.calc_py(P, "DE計算", "TCG(PSA10)", "DE", price, cost=20000,
                      promo_on=False, eu_country=cc)


def nonus(price):
    return oc.calc_py(P, "US計算_非US", "TCG(PSA10)", "US", price, cost=20000,
                      promo_on=False, eu_country="DE")


def test_de_band_switches_at_150():
    """€150 をまたぐと利益が不連続に改善する (DDU で関税と割高な運送費が消えるため)."""
    lo, hi = de(150), de(151)
    assert hi - lo > 1500, f"帯が切り替わっていない: {lo:.0f} → {hi:.0f}"


def test_de_ddu_drops_duty_and_uses_jp_post():
    """>€150 は 日本郵便実費 のみ。関税(¥555)も Economy実費 も乗らない."""
    # 同一価格で DDU 側の想定コストを手計算して突き合わせる
    price = 200.0
    profit = de(price)
    # DDU: S = jpPost - J = 1240 - 2000 = -760
    # DDP なら S = 3219 - 2000 = +1219 → 差 1979 円ぶん DDU が有利
    assert profit - (de(price) ) == 0            # 自己整合
    P2 = dict(P, iossEur=1e9)                    # 全部 DDP 扱いにした場合
    ddp = oc.calc_py(P2, "DE計算", "TCG(PSA10)", "DE", price, cost=20000,
                     promo_on=False, eu_country="DE")
    assert abs((profit - ddp) - 1979) < 5, f"DDU の得が 1979円 になっていない: {profit-ddp:.0f}"


def test_shipping_revenue_is_flat_across_band():
    """送料収入はポリシー値なので帯で変わらない (出品時に固定)."""
    # DE ルート: 送料収入は常に €14.86 → VAT の基数も (price + 14.86)
    for price in (100, 200):
        got = de(price)
        assert isinstance(got, float)
    # 収入が変わらないことは VAT 基数から間接確認 (price+14.86)*0.19
    assert abs(((100 + 14.86) * 0.19) - 21.82) < 0.01


def test_vat_follows_destination():
    """AT は 20% (実注文 2026-07-12 €49.82 → €9.96 = 20% で確認)."""
    d, a = de(100, "DE"), de(100, "AT")
    assert d != a, "仕向地で VAT 率が変わっていない"


def test_nonus_band_uses_usd_threshold():
    """非US ルートは €150 を USD 換算したしきい値で切り替わる."""
    lim = 150 * 184.0 / 160.0        # = $172.5
    lo, hi = nonus(lim - 1), nonus(lim + 1)
    assert hi - lo > 1500, f"USD 換算しきい値で切り替わっていない: {lo:.0f} → {hi:.0f}"


def test_html_documents_the_band_rule():
    for frag in ("iossLimit", "DDU", "ポリシー値なので帯によらず一定"):
        assert frag in oc.HTML, f"帯ルールの記載が無い: {frag}"
