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


# ---------------------------------------------------------------------------
# ★2026-08-09 追加: カテゴリ別 FVF/送料 にも同じ不変条件を適用する
# ---------------------------------------------------------------------------
def _live_categories():
    """live (v8 gsheet) のキャッシュを読む。無ければ None (= このテストは skip)."""
    import json
    p = Path(__file__).resolve().parent.parent / "iMakeBayAPI" / "cache" / "profit_params_cache.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))["data"]["categories"]
    except (ValueError, KeyError):
        return None


def test_yaml_categories_are_never_cheaper_than_live():
    """★yaml の fvf/送料が live より **安い** と、GSheet が落ちた時ほど安く売る.

    fvf・送料はどちらも原価側なので、**高く置くほど最低価格が上がって安全**。
    レート (分母) と向きは逆だが、「fallback は危険側に倒さない」という結論は同じ。

    2026-08-08 実測では 10カテゴリが live より安く、特に一番くじは
    fvf 0.1325 / 送料 ¥2,500 (live は 0.14 / ¥3,000) で **原価を過小評価**していた。
    2026-08-09 に live まで引き上げ済。ここが落ちたら yaml を下げる変更が入った合図。

    live より **高い**分は安全側なので許容する (Montbell/Tシャツ等が該当)。
    """
    import pytest
    live = _live_categories()
    if not live:
        pytest.skip("live キャッシュが無い環境 (creds 無し worktree 等)")

    yaml_cats = config_loader.load()["categories"]
    cheaper = []
    for name, y in yaml_cats.items():
        lv = live.get(name)
        if not lv:
            continue                      # live に無いカテゴリは別問題 (下のテスト)
        if float(y["fvf"]) < float(lv[0]) - 1e-9:
            cheaper.append(f"{name}: fvf {y['fvf']} < live {lv[0]}")
        if int(y["shipping_jpy"]) < int(lv[1]):
            cheaper.append(f"{name}: 送料 {y['shipping_jpy']} < live {lv[1]}")
    assert not cheaper, (
        "yaml fallback が live より安い (= 原価過小評価 = 赤字方向):\n  "
        + "\n  ".join(cheaper))


def test_yaml_only_categories_are_documented():
    """yaml にあって live に無いカテゴリは `get_check_csv_params` が例外になる.

    2026-08-09 実測: スニーカー / ゴルフ が該当し `ValueError: Unknown category`。
    yaml に書いてあるのに使えないので、**v8 スプシに追加するか yaml から消すか**の
    どちらかが要る (残務として起票済)。ここでは「増えていないこと」だけ固定する。
    """
    import pytest
    live = _live_categories()
    if not live:
        pytest.skip("live キャッシュが無い環境")
    yaml_only = sorted(set(config_loader.load()["categories"]) - set(live))
    assert yaml_only == ["ゴルフ", "スニーカー"], (
        f"yaml にあって live に無いカテゴリが変わった: {yaml_only}\n"
        "増えていれば get_check_csv_params が例外になる経路が増えている")
