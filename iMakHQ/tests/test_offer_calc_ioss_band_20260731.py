# -*- coding: utf-8 -*-
"""offer_calc — €150 (IOSS) をまたぐと DDP/DDU が切り替わること.

背景 (2026-07-31 実オファーが発端):
    ebay.de の出品 €220.62 に €120 のオファー。**発送手段も税の扱いも成約額で決まる**:
      ≤€150 … IOSS/DDP。eBay が VAT を徴収し、**関税は当方負担**。SpeedPAK Economy
      >€150 … DDU。**買い手が着払いで関税を払う**ので当方コストに入れない。国際エアパケット

★2026-08-09: **DE 経路 (DE計算タブ) を撤去**したため、DE 建ての test を削除した。
    DEミラーが 0件になった (live 4,343件の通貨内訳 USD/AUD/CAD/GBP のみ、**EUR 0**)。
    存在しない経路の計算機を残すと、実在しない条件で採算を判断してしまう。

    **EU送料マスタ (P.eu / iossEur) と eucty セレクタは残っている。**
    `US計算_非US` (US出品を米国外へ発送) が同じ値で DDP を計算しているため。
    → 帯の切り替わりは **非US ルートで引き続き固定する** (下の
      `test_nonus_band_uses_usd_threshold`)。ここが落ちたら EU送料マスタ側の退行。

守りたい性質:
  1. しきい値は 成約額 (コスト側) / 出品価格 (送料収入側)
  2. >€150 は関税を上乗せしない
  3. 非US ルートのしきい値は €150 を **USD 換算**した値
  4. DE 経路が復活していないこと (撤去の固定)
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


def nonus(price, cc="DE"):
    return oc.calc_py(P, "US計算_非US", "TCG(PSA10)", "US", price, cost=20000,
                      promo_on=False, eu_country=cc)


def test_nonus_band_uses_usd_threshold():
    """非US ルートは €150 を USD 換算したしきい値で切り替わる (実測 +487.8円)."""
    lim = 150 * 184.0 / 160.0        # = $172.5
    lo, hi = nonus(lim - 1), nonus(lim + 1)
    gain = hi - lo
    assert gain > 0, f"USD 換算しきい値で切り替わっていない: {lo:.0f} → {hi:.0f}"
    assert 350 < gain < 650, f"改善幅が想定外 (期待 ≈488円): {gain:.0f}"


def test_nonus_ddu_drops_duty():
    """>€150 は関税を当方コストに乗せない (買い手が着払い)。

    全部 DDP 扱い (iossEur を無限大) にした場合と比べて DDU 側が有利であること。
    """
    price = 300.0                     # $172.5 の帯より上
    ddu = nonus(price)
    ddp = oc.calc_py(dict(P, iossEur=1e9), "US計算_非US", "TCG(PSA10)", "US", price,
                     cost=20000, promo_on=False, eu_country="DE")
    assert ddu > ddp, f"DDU が不利になっている: DDU={ddu:.0f} / DDP={ddp:.0f}"


def test_nonus_cost_follows_destination():
    """仕向国で EU送料マスタ の実費が変わる (DE ¥3,219 / AT ¥4,130)."""
    d, a = nonus(100, "DE"), nonus(100, "AT")
    assert d != a, "仕向地で DDP コストが変わっていない (EU送料マスタが効いていない)"
    assert d > a, "実費の高い AT の方が利益が大きくなっている"


def test_de_route_is_gone():
    """★DE 経路を復活させない (2026-08-09 撤去)。

    EUR 建ての出品が 0 件なので、DE の計算機は「実在しない条件」を計算してしまう。
    復活させるなら、まず EUR 建て出品が実在することを実測してから。
    """
    assert "DE" not in oc.ROUTES, "ROUTES に DE が戻っている"
    assert "DE計算" not in oc.TABS, "TABS に DE計算 が戻っている"
    assert "EUR" not in oc.CUR2DEST, "CUR2DEST に EUR が戻っている"
    assert "tab === 'DE計算'" not in oc.HTML, "JS に DE計算 分岐が戻っている"


def test_eu_master_is_kept_for_nonus():
    """★EU送料マスタと eucty セレクタは **消さない**。

    US計算_非US が p['eu'] / p['iossEur'] を使う。消すと生きている経路が壊れる
    (残務 №95 の起票時に出品専任が明示した条件)。
    """
    assert "eucty" in oc.HTML, "EU仕向国セレクタが消えている"
    assert "P.eu" in oc.HTML, "EU送料マスタの参照が消えている"
    assert "iossEur" in oc.HTML, "IOSS しきい値が消えている"


def test_html_documents_the_band_rule():
    for frag in ("iossLimit", "DDU", "国際エアパケット"):
        assert frag in oc.HTML, f"帯ルールの記載が無い: {frag}"
