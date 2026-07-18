"""Regression: 2026-06-21 — CSV内 同design重複の間引き。

重複くんは「既出品」としか照合せず同一CSV内の同design複数コピー(別cert)を間引かない →
同じカード(例 Pikachu McDonald's M-P-020)が2枚出る。(Game,Set,番号)同一を1枚に絞る。
"""
import importlib.util
from pathlib import Path
import sys

_P = Path(__file__).resolve().parent.parent / "iMakHQ" / "tools" / "tcg_intra_csv_dedup.py"
sys.path.insert(0, str(_P.parent))
_spec = importlib.util.spec_from_file_location("tcg_intra_csv_dedup_t", _P)
dd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dd)

H = ["*Title", "C:Game", "C:Set", "C:Card Number"]


def _row(title, game, st, num):
    return [title, game, st, num]


def test_drops_same_design_second_copy():
    body = [
        _row("Pikachu A", "Pokemon", "SVP Promo", "020/M-P"),   # keep
        _row("Rayquaza", "Pokemon", "M2a", "127/193"),          # keep
        _row("Pikachu B", "Pokemon", "SVP Promo", "020/M-P"),   # drop (同design 2枚目)
    ]
    drop = dd.dup_row_indices(body, H)
    assert drop == {2}                       # 2枚目Pikachuのみ除外、Rayquazaは残す


def test_three_copies_keep_one():
    body = [_row(f"Pika{i}", "Pokemon", "SVP Promo", "020/M-P") for i in range(3)]
    assert dd.dup_row_indices(body, H) == {1, 2}   # 1枚だけ残す


def test_different_design_kept():
    body = [_row("a", "Pokemon", "SV6", "123/101"),
            _row("b", "One Piece", "OP09", "037")]
    assert dd.dup_row_indices(body, H) == set()    # design 異なる → 両方残す


def test_incomplete_key_not_dropped():
    # 番号が空(同定不能)→ 誤除外しない(fail-closed)
    body = [_row("a", "Pokemon", "SVP Promo", ""),
            _row("b", "Pokemon", "SVP Promo", "")]
    assert dd.dup_row_indices(body, H) == set()


def test_control_panel_wires_intra_dedup_before_write_keys():
    cp = (Path(__file__).resolve().parent.parent / "iMakHQ" / "control_panel.py").read_text(encoding="utf-8")
    assert "tcg_intra_csv_dedup.py" in cp
    # 物理除外(check-csv)の後・intra間引きを挟み、**メインKEY書込(Step 4b)は intra の後**。
    # intra で間引いた分(兄弟未出品)に KEY を書くと orphan 化するため、この順序が安全条件。
    i_excl = cp.index("--check-csv")
    i_intra = cp.index("tcg_intra_csv_dedup.py")
    i_wk_main = cp.index("--write-keys-from-csv", i_intra)   # intra 以降の write-keys = Step 4b
    assert i_excl < i_intra < i_wk_main


def test_control_panel_livedup_writeback_runs_before_intra_dedup():
    """live重複除外(4a)の KEY 書込は intra間引き(4a-2)の**前**(2026-07-18)。

    4a が消すのは出品済(live兄弟あり)= KEY 書いても orphan にならない安全な分。
    一方 intra が消すのは兄弟未出品なので KEY を書いてはいけない。両者を分けるため、
    live重複 writeback は必ず intra の前に置き、4a が消した分だけを対象化する。
    """
    cp = (Path(__file__).resolve().parent.parent / "iMakHQ" / "control_panel.py").read_text(encoding="utf-8")
    assert "_write_keys_for_livedup_removed" in cp
    i_excl = cp.index("--check-csv")
    # 呼出のみ(_pre_rows を渡す実引数)を狙う = def 行を誤ヒットしない
    i_call = cp.index("_write_keys_for_livedup_removed(append_log_func, latest_csv, _pre_rows")
    i_intra = cp.index("tcg_intra_csv_dedup.py")
    assert i_excl < i_call < i_intra
