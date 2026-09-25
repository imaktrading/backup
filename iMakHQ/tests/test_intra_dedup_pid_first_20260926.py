"""CSV内の間引きは生成器が確定した product_id を優先する (2026-09-26)。

クラシックの CLF-001 (フシギダネ) と CLK-001 (カメックス) は (Game, Set, 番号) が同じで、
別カードなのに2枚目が間引かれた (2026-09-23 cert 158998557)。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from tcg_intra_csv_dedup import CSV_CERT, dup_row_indices, load_pid_by_cert  # noqa: E402

H = ["*Title", "C:Game", "C:Set", "C:Card Number", CSV_CERT]
BULBA = ["Bulbasaur", "Pokémon TCG", "Pokemon Card Game Classic", "001/032", "156536236"]
SQUIRT = ["Squirtle", "Pokémon TCG", "Pokemon Card Game Classic", "001/032", "158998557"]


def test_same_print_number_but_different_pid_is_kept():
    pids = {"156536236": "pokemon_tcg:CLF-001", "158998557": "pokemon_tcg:CLK-001"}
    assert dup_row_indices([BULBA, SQUIRT], H, pids) == set()


def test_same_pid_is_still_thinned():
    pids = {"156536236": "pokemon_tcg:CLF-001", "158998557": "pokemon_tcg:CLF-001"}
    assert dup_row_indices([BULBA, SQUIRT], H, pids) == {1}


def test_without_sidecar_falls_back_to_design_key():
    assert dup_row_indices([BULBA, SQUIRT], H) == {1}


def test_sidecar_is_read_next_to_csv(tmp_path):
    csv_path = tmp_path / "tcg_upload_x.csv"
    (tmp_path / "tcg_upload_x.canonical.json").write_text(
        json.dumps({"by_cert": {"1": "pokemon_tcg:A-1"}}), encoding="utf-8")
    assert load_pid_by_cert(str(csv_path)) == {"1": "pokemon_tcg:A-1"}
    assert load_pid_by_cert(str(tmp_path / "none.csv")) == {}
