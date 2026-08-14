# -*- coding: utf-8 -*-
"""相場取得の停止 + 出品品質チェック3本 (2026-08-13)。

背景 (ユーザー指示「出品の質が落ちずに、無駄な部分は削除しよう」):
  - 相場取得は **価格に影響していなかった** (価格は cost-plus / pricing_engine)。
    相場を理由に出品を止めた実績は 81走行645行で0件、最後の NO-GO は 2026-05-11。
    記録先の market_log.csv も 1,848行貯めて未使用 → 3か所とも停止。
  - 代わりに、実際に出てしまった不良を捕まえるチェックを3本足した:
      ① 商品説明がテンプレになっているか (8/12 ダミー説明6件が素通りした)
      ② PSA 画像があるか / 小サイズのままでないか (8/11 に画像0枚の行が入稿された)
      ③ Item Specifics に変換前の生値が残っていないか ('L★'→'L' で潰れた)

固定する挙動:
  1. market_lookup は既定 OFF (yaml に節が無くても OFF = 余計な API を叩かない)
  2. 説明が短い/テンプレ要素欠落 → ERROR (= 出品しない)
  3. PSA 画像0枚 → ERROR / /small/ 混在 → WARN (large が無い cert があるので落とさない)
  4. C:Rarity が1文字 or 記号残り → ERROR、タイトルが1文字で終わる → ERROR
  5. 正常な行は ①②③ のどれにも当たらない (誤検出しない)
"""
from __future__ import annotations

import importlib.util
import os
import sys

_TCG = r"C:\dev\iMak\iMakTCG"
_API = r"C:\dev\iMak\iMakeBayAPI"
for _p in (_TCG, _API):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# TCG の check_csv は固有名でロード (4カテゴリが同名 check_csv.py を持つため)
_MOD = None


def _cc():
    global _MOD
    if _MOD is None:
        spec = importlib.util.spec_from_file_location(
            "tcg_check_csv_quality_test", os.path.join(_TCG, "check_csv.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _MOD = m
    return _MOD


_GOOD_DESC = ("<html><body><p>x</p><ul><li>PSA 10</li></ul>"
              "<p>Specifications</p><ul><li>Card Name: X</li></ul>" + "y" * 2100 +
              "</body></html>")
_CDN = "https://d1htnxwo4o0jhw.cloudfront.net/cert/1/{}/a.jpg"


# ---------------------------------------------------------------------------
# 1. 相場取得は既定 OFF
# ---------------------------------------------------------------------------
def test_market_lookup_is_off_by_default():
    import config_loader
    assert config_loader.is_market_lookup_enabled() is False
    assert config_loader.is_ai_review_enabled() is False


def test_market_lookup_off_when_yaml_missing_section(monkeypatch):
    import config_loader
    monkeypatch.setattr(config_loader, "load", lambda: {"version": "x"})
    assert config_loader.is_market_lookup_enabled() is False


def test_check_csv_and_generator_read_the_same_switch():
    """3か所が同じスイッチを見ている (バラバラに再実装していない)。"""
    for path in (os.path.join(_TCG, "check_csv.py"),
                 os.path.join(_TCG, "psa_to_csv.py"),
                 r"C:\dev\iMak\iMakHQ\tools\csv_auditor.py"):
        with open(path, encoding="utf-8") as f:
            assert "is_market_lookup_enabled" in f.read(), f"{path} がスイッチを見ていない"


# ---------------------------------------------------------------------------
# 2. 商品説明
# ---------------------------------------------------------------------------
def test_dummy_description_is_error():
    """8/12 に実際に出た 72字のダミー文。"""
    d = "PSA graded card shipped from Japan. Grade and cert number are as listed."
    msgs = [m for lv, m in _cc().description_issues(d) if lv == "ERROR"]
    assert msgs, "ダミー説明が ERROR になっていない"
    assert any("字しかない" in m for m in msgs)


def test_empty_description_is_error():
    assert [lv for lv, _ in _cc().description_issues("")] == ["ERROR"]


def test_unbalanced_html_is_error():
    d = _GOOD_DESC.replace("</ul>", "", 1)
    assert any("数が合わない" in m for lv, m in _cc().description_issues(d))


def test_good_description_passes():
    assert _cc().description_issues(_GOOD_DESC) == []


# ---------------------------------------------------------------------------
# 3. 画像
# ---------------------------------------------------------------------------
def test_no_psa_image_is_error():
    msgs = _cc().image_issues("https://example.com/999.png")
    assert ("ERROR", "PSA 画像が1枚も無い") in msgs


def test_small_image_is_warn_not_error():
    msgs = _cc().image_issues(_CDN.format("small") + "|" + _CDN.format("large"))
    assert [lv for lv, _ in msgs] == ["WARN"], "small は WARN 止まり (large 不在の cert がある)"


def test_large_images_pass():
    assert _cc().image_issues(_CDN.format("large")) == []


# ---------------------------------------------------------------------------
# 4. Item Specifics の生値
# ---------------------------------------------------------------------------
def _row(rarity="Rare", card_type="Character", features="Alternative Art"):
    C = _cc()
    headers = ["*Title", "C:Rarity", "C:Card Type", "C:Features"]
    C.HEADER_MAP = {h: i for i, h in enumerate(headers)}
    return ["PSA 10 One Piece #OP01-001 Nami", rarity, card_type, features]


def test_raw_symbol_left_in_rarity_is_error():
    msgs = [m for lv, m in _cc().specifics_sanity_issues(_row(rarity="L★"), "PSA 10 X Card")
            if lv == "ERROR"]
    assert any("変換前の記号" in m for m in msgs)


def test_single_letter_rarity_is_error():
    """★が落ちて 'L' に潰れた状態 (8/12 に実際に出た形)。"""
    msgs = [m for lv, m in _cc().specifics_sanity_issues(_row(rarity="L"), "PSA 10 X Card")
            if lv == "ERROR"]
    assert any("1文字だけ" in m for m in msgs)


def test_title_ending_with_single_letter_is_error():
    t = "PSA 10 Dragon Ball Japanese Awakened Pulse #FB01-071 Son Gohan : Childhood L"
    msgs = [m for lv, m in _cc().specifics_sanity_issues(_row(rarity="Secret Rare"), t)
            if lv == "ERROR"]
    assert any("1文字" in m and "終わって" in m for m in msgs)


def test_normal_row_is_clean():
    t = "PSA 10 One Piece Japanese 500 Years in the Future #OP07-047 Trafalgar Law Rare"
    assert _cc().specifics_sanity_issues(_row(), t) == []


# ---------------------------------------------------------------------------
# 5. 相場停止中に「競合なし($100で先行出品)」と嘘を出さない (2026-08-13 実走で発覚)
# ---------------------------------------------------------------------------
def test_gate_summary_not_printed_when_market_off():
    """相場を止めている = 判定していない。未判定を『競合なし』と書くと
    実際の価格 (cost-plus $529.98 等) と食い違う嘘のログになる。"""
    src = open(os.path.join(_TCG, "check_csv.py"), encoding="utf-8").read()
    assert "enumerate(all_gates if _market_lookup else [])" in src, "停止中も判定行を出している"
    assert "相場取得は停止中 = GATE判定なし" in src


# ---------------------------------------------------------------------------
# 6. 画面に出す量 (2026-08-13「無駄なログを消す」)
# ---------------------------------------------------------------------------
def test_ai_review_header_only_when_there_is_a_review():
    """中身が無いのに枠線+タイトルで3行使わない。"""
    src = open(os.path.join(_TCG, "check_csv.py"), encoding="utf-8").read()
    i = src.index("# === Claude AI 総合レビュー ===")
    block = src[i:i + 600]
    assert block.index("review = claude_review") < block.index("AI総合レビュー\"")


def test_dup_guard_list_is_opt_in():
    """毎回同じ顔ぶれの26組を既定で出さない (63行 → 1行)。"""
    src = open(r"C:\dev\iMak\iMakHQ\tools\dup_guard.py", encoding="utf-8").read()
    assert 'DUP_GUARD_VERBOSE' in src
    i = src.index("④ RESTOCK復活")
    assert 'if _os.environ.get("DUP_GUARD_VERBOSE"):' in src[i:i + 700]


def test_scrape_progress_is_one_line_per_card():
    """1件ごとに改行して2〜3行使っていたのを1行にまとめる。"""
    src = open(os.path.join(_TCG, "psa_to_csv.py"), encoding="utf-8").read()
    assert 'print(" 📷2", end="", flush=True)' in src
    assert 'print(f"    📷 PSA 画像 表+裏 取得 (2 枚)")' not in src


# ---------------------------------------------------------------------------
# 7. 補URL ボタンの残件ラベル (2026-08-14)
# ---------------------------------------------------------------------------
def test_hoju_badge_explains_zero():
    """★「目視できる0件」の時に理由を出す。件数だけだと押して空振りする
    (status の安い母数 37件 と、足切り後の実数 0件 が食い違うため)。"""
    src = open(r"C:\dev\iMak\iMakHQ\control_panel.py", encoding="utf-8").read()
    i = src.index("目視できる %s件")
    block = src[i:i + 1400]
    assert "押しても0件" in block
    for k in ("絵柄違い", "候補NG済", "候補なし", "未検索"):
        assert k in block, f"{k} の内訳が出ない"
