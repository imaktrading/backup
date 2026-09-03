"""Regression: 2026-06-18 — RESTOCK 最後の配線(orchestrator)。

「RESTOCK確定」→ cert/KEY解決 → psa_restock_csv(=psa_to_csv の fork, RESTOCK入力モード)→
Add→Revise変換 → Revise CSV。2026-06-21: ユーザー指示「新規は触るな」で psa_to_csv.py を
pristine に戻し、RESTOCK 差分は fork(psa_restock_csv.py)へ隔離。新規が pristine であることも固定。
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


def test_restock_fork_is_env_gated_and_uses_forced():
    # RESTOCK差分は fork(psa_restock_csv.py)に隔離。新規 psa_to_csv.py は触らない(2026-06-21)。
    fork = (Path(__file__).resolve().parent.parent / "iMakTCG" / "psa_restock_csv.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PSA_RESTOCK_INPUT")' in fork        # env-gated 入力モード
    assert "load_targets_from_sheet_psa()" in fork             # 未設定時は従来の新規抽出
    assert "_restock_forced.get(cert" in fork                   # forced変種を新コアに渡す
    # shuffle/batch制限は RESTOCK時 skip(確定分を全部)
    assert "not _restock_input and os.environ" in fork
    assert "not _restock_input and len(cert_numbers)" in fork


def test_new_listing_psatocsv_is_pristine_no_restock():
    """新規 psa_to_csv.py に RESTOCK差分が混入しないこと(ユーザー指示「新規は触るな」回帰ガード)。
    RESTOCK が新規生成器を再び編集したらここで落ちる。差分は psa_restock_csv.py(fork)へ。"""
    src = (Path(__file__).resolve().parent.parent / "iMakTCG" / "psa_to_csv.py").read_text(encoding="utf-8")
    assert "PSA_RESTOCK_INPUT" not in src
    assert "_restock_input" not in src
    assert "_restock_forced" not in src
    assert 'os.environ.get("PSA_PROFILE_DIR")' not in src       # 別profile差分も新規には入れない


def test_control_panel_has_restock_buttons():
    src = (Path(__file__).resolve().parent.parent / "iMakHQ" / "control_panel.py").read_text(encoding="utf-8")
    # ★2026-09-03: ラベルを商材+工程に統一 (旧「RESTOCK Revise CSV生成」)
    i1 = src.index('"label": "🛒 PSA 再仕入れ ② CSV"')
    assert '"psa_restock_build.py"' in src[i1:i1 + 400]      # ①生成ボタン
    i2 = src.index('"label": "🛒 PSA 再仕入れ ③ 確認"')
    assert '"psa_restock_writeback.py"' in src[i2:i2 + 400]  # ②書戻しボタン


def test_writeback_has_main_entry():
    src = (_TOOLS / "psa_restock_writeback.py").read_text(encoding="utf-8")
    assert "def main(" in src and '__name__ == "__main__"' in src


def test_parallel_safe_with_new_listing():
    # 新規出品と並走可: 別Chrome profile + 本実行で生成したCSVだけ掴む(2026-06-18)
    gsrc = (Path(__file__).resolve().parent.parent / "iMakTCG" / "psa_restock_csv.py").read_text(encoding="utf-8")
    assert 'os.environ.get("PSA_PROFILE_DIR")' in gsrc                  # profile env上書き(競合回避・fork側)
    osrc = (_TOOLS / "psa_restock_build.py").read_text(encoding="utf-8")
    assert "PSA_PROFILE_DIR=restock_profile" in osrc                    # RESTOCKは別profile
    assert "before = set(glob.glob" in osrc and "- before" in osrc     # 本実行生成分のみ(誤掴み防止)
    assert "adds[-1]" not in osrc                                       # 「最新」掴みは廃止


def test_orchestrator_generates_add_csv_revise_delegated():
    """psa_restock_build は Add CSV 生成までを駆動。Add→Revise 変換は 2026-06-20 から
    control_panel の post-chain(除外/dedup後)に移動(順序保証=赤字/重複/旧タイトル非混入)。"""
    src = (_TOOLS / "psa_restock_build.py").read_text(encoding="utf-8")
    assert "PSA_RESTOCK_INPUT" in src and 'TCG_USE_NEW_GEN="1"' in src
    assert "psa_restock_csv.py" in src                           # Add生成を駆動(新規でなくfork)
    assert 'read_tab("RESTOCK確定")' in src or "_read_restock_confirmed" in src
    # convert_file は psa_restock_build では呼ばない(dedup前変換=混入バグの根治)
    assert "convert_file" not in src


def test_control_panel_does_revise_after_dedup():
    """control_panel が post-chain(dedup)後に Add→Revise 変換する(restock_revise=True ボタン)。"""
    cp = (Path(__file__).resolve().parent.parent / "iMakHQ" / "control_panel.py").read_text(encoding="utf-8")
    assert "restock_revise" in cp                                # ♻ボタンのフラグ
    assert "_run_restock_revise_for_latest_csv" in cp            # post-chain の変換ステップ
    assert "convert_file" in cp                                  # 変換は control_panel 側
