"""fallback レートが「安全側」に留まることを守る回帰テスト (2026-07-31).

背景:
  `compute_min_price_usd = (cost_jpy + shipping_jpy) / (exchange_rate * net_ratio)`
  = exchange_rate は **分母**。低いほど最低価格が高く出る = 安全側 (fail-closed)。

  つまり fallback レートを「現在値に追随させて上げる」と最低価格が下がり、
  **危険側 (fail-OPEN)** に倒れる。GSheet が落ちている時ほど慎重であるべきなので、
  fallback は live を上回らせない。

  2026-07-31 実測: cost=10,000 / TCG(PSA10) で
    rate=159.245 (fallback) → $121.05
    rate=160.6035 (live)    → $120.03

  ここでは「yaml と config_loader のハードコード既定が食い違わないこと」を固定する。
  この 2 つが割れると、yaml を読めない環境だけ別のレートで値付けすることになる。
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "iMakeBayAPI"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import config_loader  # noqa: E402
import profit_params  # noqa: E402

def test_yaml_and_hardcoded_fallback_agree():
    """yaml の profit_fallback と config_loader のハードコード既定が一致すること."""
    yaml_fb = config_loader.get_profit_fallback()
    assert yaml_fb, "global.yaml の profit_fallback が読めていない"

    # yaml が読めなかった時に config_loader が使うハードコード既定
    hardcoded = config_loader._hardcoded_fallback()["profit_fallback"]

    for key in ("exchange_rate_usd", "ad_rate", "payo_fee", "intl_fee", "target_profit"):
        assert yaml_fb[key] == hardcoded[key], (
            f"{key} が yaml({yaml_fb[key]}) と config_loader 既定({hardcoded[key]}) で割れている。"
            " yaml を読めない環境だけ別の値で値付けすることになる"
        )


def test_lower_rate_yields_higher_min_price():
    """レートが低いほど最低価格が高く出る = 安全側、という前提が崩れていないこと.

    この関係が逆転したら、上の「fallback は live を上回らせない」という運用ルールごと
    見直しが要る。
    """
    cost, ship = 10000, 2000
    net = 1 - 0.1325 - profit_params.INTL_FEE - 0.10 - 0.025 - 0.10

    low = (cost + ship) / (159.245 * net)
    high = (cost + ship) / (170.0 * net)

    assert low > high, "レートが低い方が最低価格が高い、という前提が壊れている"


def test_fallback_rate_is_sane():
    """fallback レートが現実的な範囲にあること (0 除算・桁間違いの検出)."""
    rate = config_loader.get_profit_fallback()["exchange_rate_usd"]
    assert 100 < rate < 250, f"USD/JPY の fallback が非現実的: {rate}"
