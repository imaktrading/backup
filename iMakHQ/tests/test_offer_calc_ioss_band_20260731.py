# -*- coding: utf-8 -*-
"""offer_calc — €150 (IOSS) をまたぐと DDP/DDU が切り替わること.

背景 (2026-07-31 実オファーが発端):
    ebay.de の出品 €220.62 に €120 のオファー。**発送手段も税の扱いも成約額で決まる**:
      ≤€150 … IOSS/DDP。eBay が VAT を徴収し、**関税は当方負担**。SpeedPAK Economy
      >€150 … DDU。**買い手が着払いで関税を払う**ので当方コストに入れない。国際エアパケット

★2026-07-31 夕: **送料の定義が確定**し、本テストの期待値を更新した (ユーザー確定・V9 実装済)。

    送料 = (その手段の実費 − 国際エアパケット実費) + 当方負担の関税

  - 旧: 送料収入は**ポリシー値なので帯によらず一定** (€14.86/€17.49 固定)
  - 新: 送料収入 = **DDPコスト − 想定送料 と同額**。**>€150 は €0** (送料無料)

  → 帯をまたいだ時の利益改善は **旧より小さくなる**。DDPコストが消える一方で
    **送料収入も同時に消える**ため。実測 (下記 test に固定):
      DDPコスト差 = 3219 − 2000 = ¥1,219 (= €6.625 @184)
      これが消えて +1,219、送料収入 ¥1,219 の手取り (手数料 ~33% 差引 ≈ ¥821) が消えて −821
      → 差引 **+約398円**。旧テストの「1,500円以上」は旧定義の値なので不成立が正しい。

  ★出品価格と成約価格で見る帯が違う (またぎ問題):
    - **コスト側 (S)** は **成約額** の帯 … 実際にどう送るかで決まる
    - **送料収入 (R)** は **出品価格** の帯 … ポリシーは出品時に決まり後から変えられない
    >€150 で出した listing に €150 未満のオファーが来ると、Economy で送るのに送料収入 0
    = DDP コストが全額持ち出し。これが「またぎ」。

守りたい性質:
  1. しきい値は 成約額 (コスト側) / 出品価格 (送料収入側)
  2. >€150 は関税を上乗せしない
  3. 送料収入は **帯で変わる** (旧: 変わらない ← 定義変更で反転)
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
    """€150 をまたぐと利益が改善する (DDP コストが消える)。

    ただし送料収入も同時に消えるので、改善幅は DDP コスト全額ではない。
    実測 +397.7円 (= 1219 − 821)。旧定義の「1,500円以上」は成立しない。
    """
    lo, hi = de(150), de(151)
    gain = hi - lo
    assert gain > 0, f"帯が切り替わっていない: {lo:.0f} → {hi:.0f}"
    assert 300 < gain < 500, f"改善幅が想定外 (期待 ≈398円): {gain:.0f}"


def test_de_ddu_drops_duty():
    """>€150 は関税を当方コストに乗せない (買い手が着払い)。

    全部 DDP 扱いにした場合と比べて DDU 側が有利であること。
    実測 +251.7円 (DDPコスト 1219 が消え、送料収入の手取り ≈967 が消える差引)。
    """
    price = 200.0
    profit = de(price)
    ddp = oc.calc_py(dict(P, iossEur=1e9), "DE計算", "TCG(PSA10)", "DE", price,
                     cost=20000, promo_on=False, eu_country="DE")
    gain = profit - ddp
    assert gain > 0, f"DDU が不利になっている: {gain:.0f}"
    assert 150 < gain < 350, f"DDU の得が想定外 (期待 ≈252円): {gain:.0f}"


def test_shipping_revenue_follows_the_band():
    """★定義変更点: 送料収入は帯で変わる (旧は「ポリシー値で一定」だった)。

    >€150 は送料無料なので、送料収入も VAT の基数も price のみになる。
    コード側の実装 (R の三項演算) を固定して、元の「固定額」実装に戻ったら落とす。
    """
    assert "listedPrice" in oc.HTML, "出品価格で送料帯を見る関数が消えている"
    assert "deShip" not in oc.HTML.split("function calc(")[1].split("const O =")[0], \
        "送料収入が固定額 (deShip/atShip) に戻っている"


def test_vat_follows_destination():
    """AT は 20% (実注文 2026-07-12 €49.82 → €9.96 = 20% で確認)."""
    d, a = de(100, "DE"), de(100, "AT")
    assert d != a, "仕向地で VAT 率が変わっていない"


def test_nonus_band_uses_usd_threshold():
    """非US ルートは €150 を USD 換算したしきい値で切り替わる (実測 +487.8円)."""
    lim = 150 * 184.0 / 160.0        # = $172.5
    lo, hi = nonus(lim - 1), nonus(lim + 1)
    gain = hi - lo
    assert gain > 0, f"USD 換算しきい値で切り替わっていない: {lo:.0f} → {hi:.0f}"
    assert 350 < gain < 650, f"改善幅が想定外 (期待 ≈488円): {gain:.0f}"


def test_html_documents_the_band_rule():
    for frag in ("iossLimit", "DDU", "国際エアパケット"):
        assert frag in oc.HTML, f"帯ルールの記載が無い: {frag}"
