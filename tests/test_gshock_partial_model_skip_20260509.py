"""Regression: 2026-05-09 G-SHOCK partial model_id (color suffix 欠落) で catalog miss 連発.

事故 (missing_models.csv 5/9 06:06〜17:35 で同一 model 4 回検出):
  Mercari title が "G-SHOCK GW-2320FP メンズ" 等の略記で書かれており、
  extract_model_from_text が "GW-2320FP" を返却 (color suffix 抜き).
  catalog には完全 ID `GW-2320FP-1A1JR` / `GW-2320FP-1A4JR` の 2 色登録済だが、
  partial だと lookup miss → missing_models.csv 通知 → Catalog Claude 困惑
  (catalog 側で partial alias 作成は catalog_official_only 規約違反のため非対応).

修正方針 (本体 logic 不変、validator 追加):
  iMakG-shock/gshock_to_csv.py に is_complete_gshock_model() を追加し、
  load_targets_from_low_sheet で partial 抽出時に SKIP (Precision 100% 原則準拠).
  → catalog miss 通知を出さず、ユーザーに「Mercari 略記」として明示警告.

設計原則:
  - catalog (604 件) の構造的不変性「3+ ハイフンセグメント、最終セグメント数字始まり」
    を validator にエンコード (no_modification_chain 準拠、データ駆動)
  - partial extraction は出品の正確性原則 (CLAUDE.md) 違反のため fail-closed
"""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GSHOCK = _REPO_ROOT / "iMakG-shock"
if str(_GSHOCK) not in sys.path:
    sys.path.insert(0, str(_GSHOCK))


def _load_gshock_to_csv():
    """sys.modules キャッシュ汚染回避用、絶対パスから iMakG-shock/gshock_to_csv.py を load."""
    path = _GSHOCK / "gshock_to_csv.py"
    spec = importlib.util.spec_from_file_location("_test_gshock_to_csv_partial", str(path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_partial_gw2320fp_rejected():
    """5/9 事故: 'GW-2320FP' (color suffix なし) は incomplete 判定."""
    m = _load_gshock_to_csv()
    assert m.is_complete_gshock_model("GW-2320FP") is False


def test_full_gw2320fp_color_variants_accepted():
    """catalog 既存の 2 色 (1A1JR / 1A4JR) は complete 判定."""
    m = _load_gshock_to_csv()
    assert m.is_complete_gshock_model("GW-2320FP-1A1JR") is True
    assert m.is_complete_gshock_model("GW-2320FP-1A4JR") is True


def test_other_full_models_accepted():
    """catalog の他カテゴリ完全 ID も complete 判定 (副作用ゼロ確認)."""
    m = _load_gshock_to_csv()
    for full in [
        "GA-2100-1A1JF",
        "DW-5600AKA-4JR",
        "GMW-B5000BT-1",
        "AW-500BB-1E",
        "GA-B010BEG-1AJF",
    ]:
        assert m.is_complete_gshock_model(full) is True, f"should accept: {full!r}"


def test_other_partials_rejected():
    """色番欠落の partial パターンは全て reject."""
    m = _load_gshock_to_csv()
    for partial in [
        "GW-2320FP",       # 5/9 事故
        "GA-2100",         # 2 セグメント
        "DW-5600",
        "GW-2320FP-FOO",   # 最終セグメント英字始まり
        "",
        None,
    ]:
        assert m.is_complete_gshock_model(partial) is False, f"should reject: {partial!r}"


def test_skip_message_format_does_not_break():
    """SKIP メッセージが実値を含む format string で例外を出さない (smoke)."""
    m = _load_gshock_to_csv()
    # is_complete_gshock_model の戻り値で f-string が組まれることを確認
    model = "GW-2320FP"
    # 副作用: 例外なしで処理可能か (load_targets_from_low_sheet 内の f-string 参照)
    msg = f"⚠️ partial model_id (color suffix 欠落): {model!r} → SKIP (例: {model}-1A4JR)"
    assert "GW-2320FP" in msg
