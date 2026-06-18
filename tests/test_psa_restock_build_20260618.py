"""Regression: 2026-06-18 — RESTOCK 最後の配線(orchestrator)。

「RESTOCK確定」→ cert/KEY解決 → psa_to_csv(RESTOCK入力モード, 新コア生成・forced変種)→
Add→Revise変換 → Revise CSV。psa_to_csv は env PSA_RESTOCK_INPUT 未設定時は完全に従来通り
(本番不変)であることも固定。
"""
import importlib.util
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools"
import sys
sys.path.insert(0, str(_TOOLS))
_spec = importlib.util.spec_from_file_location("psa_restock_build_t", _TOOLS / "psa_restock_build.py")
b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b)


def test_build_restock_input_resolves_cert_key_cost():
    rows = [{"itemID": "358481165472", "cost": "29400", "supply_url": "https://m/1"},
            {"itemID": "999", "cost": "", "supply_url": ""},          # cert無 → skip
            {"itemID": "358441104504", "cost": "40000", "supply_url": "https://s/2"}]
    i2c = {"358481165472": "142490884", "358441104504": "196679145"}
    i2k = {"358481165472": "OP01-016_P", "358441104504": "M2a-231"}
    inp, sk = b.build_restock_input(rows, i2c, i2k)
    assert inp["certs"] == ["142490884", "196679145"]
    assert inp["forced"] == {"142490884": "OP01-016_P", "196679145": "M2a-231"}
    assert inp["cost"] == {"142490884": 29400.0, "196679145": 40000.0}
    assert inp["supply_url"]["142490884"] == "https://m/1"
    assert len(sk) == 1 and sk[0][0] == "999"          # cert無は fail-closed で skip


def test_build_restock_input_dedups_cert():
    rows = [{"itemID": "a"}, {"itemID": "b"}]
    inp, _ = b.build_restock_input(rows, {"a": "C1", "b": "C1"}, {})  # 同cert
    assert inp["certs"] == ["C1"]                       # 重複cert除去


def test_psatocsv_restock_mode_is_env_gated_and_uses_forced():
    src = (Path(__file__).resolve().parent.parent / "iMakTCG" / "psa_to_csv.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PSA_RESTOCK_INPUT")' in src         # env-gated 入力モード
    assert "load_targets_from_sheet_psa()" in src              # 未設定時は従来の新規抽出
    assert "_restock_forced.get(cert" in src                    # forced変種を新コアに渡す
    # shuffle/batch制限は RESTOCK時 skip(確定分を全部)
    assert "not _restock_input and os.environ" in src
    assert "not _restock_input and len(cert_numbers)" in src


def test_control_panel_has_restock_buttons():
    src = (Path(__file__).resolve().parent.parent / "iMakHQ" / "control_panel.py").read_text(encoding="utf-8")
    i1 = src.index("RESTOCK Revise CSV生成")
    assert '"psa_restock_build.py"' in src[i1:i1 + 400]      # ①生成ボタン
    i2 = src.index("RESTOCK状態同期")
    assert '"psa_restock_writeback.py"' in src[i2:i2 + 400]  # ②書戻しボタン


def test_writeback_has_main_entry():
    src = (_TOOLS / "psa_restock_writeback.py").read_text(encoding="utf-8")
    assert "def main(" in src and '__name__ == "__main__"' in src


def test_parallel_safe_with_new_listing():
    # 新規出品と並走可: 別Chrome profile + 本実行で生成したCSVだけ掴む(2026-06-18)
    gsrc = (Path(__file__).resolve().parent.parent / "iMakTCG" / "psa_to_csv.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PSA_PROFILE_DIR")' in gsrc                  # profile env上書き(競合回避)
    osrc = (_TOOLS / "psa_restock_build.py").read_text(encoding="utf-8")
    assert "PSA_PROFILE_DIR=restock_profile" in osrc                    # RESTOCKは別profile
    assert "before = set(glob.glob" in osrc and "- before" in osrc     # 本実行生成分のみ(誤掴み防止)
    assert "adds[-1]" not in osrc                                       # 「最新」掴みは廃止


def test_orchestrator_wires_psatocsv_then_revise():
    src = (_TOOLS / "psa_restock_build.py").read_text(encoding="utf-8")
    assert "PSA_RESTOCK_INPUT" in src and 'TCG_USE_NEW_GEN="1"' in src
    assert "psa_to_csv.py" in src                                # Add生成を駆動
    assert "convert_file" in src                                 # Add→Revise変換
    assert 'read_tab("RESTOCK確定")' in src or "_read_restock_confirmed" in src
