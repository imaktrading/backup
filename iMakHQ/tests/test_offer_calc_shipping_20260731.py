# -*- coding: utf-8 -*-
"""offer_calc — 受信オファーの自動読込 + 「何で送るか」表示の不変条件.

背景 (2026-07-31 実オファーで発覚):
    ebay.de の listing (出品 €220.62) に **€120 のオファー**が来た。
    出品価格は「>€150 帯」なので配送設定は日本郵便だが、**成約額は €150 未満**になる。
    日本郵便はドイツ向け €150未満を引き受けないため、実際は SpeedPAK Economy で送る必要がある。
    = **発送手段は出品価格ではなく成約額で決まる**。ここを人の記憶に頼ると誤発送になる。

    併せて、オファーは期限が短い (実例: 受信〜翌日 23:11)。国・出品価格・仕入値を
    人が探して手入力する時間がそのまま判断の遅れになるため、API とシートから自動取得する。

守りたい不変条件:
  1. 仕向地マッピングが ROUTES の実キーに解決する (タイポで無言に壊れない)
  2. 発送手段の判定が HTML に入っている (消えたら誤発送に直結)
  3. €150 / £135 の境界と IOSS 番号が明記されている
  4. 仕入値は「商品管理シート N列」から取る (補URL からの推測にしない)
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import offer_calc as oc  # noqa: E402


def test_currency_to_dest_resolves_to_real_routes():
    """通貨→仕向地 が ROUTES の実キーに解決すること."""
    for cur, dest in oc.CUR2DEST.items():
        assert dest in oc.ROUTES, f"{cur} → {dest} は ROUTES に無い"


def test_usd_falls_back_to_valid_routes():
    """USD は バイヤー国で US / 非US に分岐する。両方とも実キーであること."""
    assert "US" in oc.ROUTES
    assert "その他 (US出品・米国外へ発送)" in oc.ROUTES


def test_category_map_targets_exist_in_html_defaults():
    """カテゴリ変換先が空でないこと (シート依存なので存在チェックのみ)."""
    for k, v in oc.CAT2CALC.items():
        assert v and isinstance(v, str), f"{k} の変換先が不正"
    assert oc.CAT2CALC["TCG"] == "TCG(PSA10)"


def test_html_has_shipping_panel():
    """「何で送るか」パネルが HTML に存在すること."""
    assert "shipInfo" in oc.HTML
    assert "何で送るか" in oc.HTML
    assert "成約額で決まる" in oc.HTML


def test_html_states_the_thresholds():
    """€150 / £135 / A$1000 の境界が定数として入っていること."""
    assert "IOSS_EUR = 150" in oc.HTML
    assert "UK_GBP   = 135" in oc.HTML
    assert "AU_GST   = 1000" in oc.HTML


def test_html_warns_on_band_crossing():
    """出品価格と成約額で帯が変わる場合の警告があること (本件の核心)."""
    assert "帯またぎ" in oc.HTML
    assert "SpeedPAK Economy で発送すること" in oc.HTML


def test_html_carries_operational_warnings():
    """発送時に忘れると実害が出る注意が消えていないこと."""
    assert "IM2760000742" in oc.HTML, "EU の IOSS 番号が消えている (VAT 二重払い)"
    assert "単独で発送" in oc.HTML, "UK VAT 徴収済の単独発送注意が消えている"
    assert "1kgあたり $1,000" in oc.HTML, "Economy の申告額制限が消えている"


def test_cost_comes_from_sheet_column_n():
    """仕入値は商品管理シート N列 (index 13) から取る = 補URL から推測しない."""
    assert oc.COL_COST_N == 13
    assert "N列" in (oc.fetch_offers.__doc__ or "")
    assert "補URL から推測しない" in (oc.fetch_offers.__doc__ or "")


def test_offers_are_optional_and_failsafe():
    """オファー取得に失敗しても手入力版として使えること (握り潰して続行)."""
    src = Path(oc.__file__).read_text(encoding="utf-8")
    body = src[src.index("def main"):]
    assert "--no-offers" in body, "自動取得を止める手段が無い"
    assert re.search(r"except Exception.*?\n.*?手入力版", body, re.S), \
        "取得失敗時に手入力版へフォールバックしていない"


def test_html_prefills_from_selected_offer():
    """オファーを選ぶと 国 / 出品価格 / 仕入値 が入ること."""
    for frag in ("id=\"offersel\"", "id=\"list\"", "o.cost", "o.list", "o.dest"):
        assert frag in oc.HTML, f"prefill 要素が無い: {frag}"
