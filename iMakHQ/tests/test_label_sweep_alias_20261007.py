"""ラベルの記録の割れを洗い出した時の直し (2026-10-07)。

- カタログが alias_of でまとめた別名は本体に寄せる (同じスラブに2つの ID = 割れに見えていた)
- 刷りの確認が選んだ行が別名なら本体へ (寄せた本体を別名に戻す往復を止める)
- ボックストッパーは通常と別の絵柄
- 刷りの確認は書いた後に毎回かける (作ったまま一度も自動で呼ばれていなかった)
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import psa_label_learned as L  # noqa: E402
import psa_variant_gate as G  # noqa: E402


def test_alias_merged_into_body(tmp_path):
    db = tmp_path / "c.sqlite"
    con = sqlite3.connect(db)
    con.execute("create table products (product_id, alias_of)")
    con.executemany("insert into products values (?,?)", [("A_p", "A_p1"), ("A_p1", None)])
    con.commit()
    bag = {"A_p": {"times": 1, "certs": ["1"]}, "A_p1": {"times": 2, "certs": ["2"]}}
    assert G._alias_body("A_p", con) == "A_p1" and G._alias_body("A_p1", con) == ""
    G._merge_pick(bag, "A_p", "A_p1")
    assert bag == {"A_p1": {"times": 3, "certs": ["1", "2"], "last_at": ""}}


def test_box_topper_is_a_print_word():
    assert "BOX TOPPER" in G._ALT_WORDS


def test_sweep_runs_after_writes_to_the_real_store():
    src = open(L.__file__, encoding="utf-8").read()
    assert src.count("        _sweep_after_write(path)") == 3  # record_nots / record_chosen / record_picks
    assert "if path != PATH:" in src                            # 試験の記録には かけない


def test_reprint_rows_whose_body_is_alt_art():
    """PRB02 の再録 (OP09-020_PRB02 → 本体 OP09-020_p2 の絵) は別絵柄のラベルと合う。
    ST18 の再録 (OP05-060_ST18 → OP05-060_p3 の絵) は PSA が印を書かなくても合う。"""
    op = "one_piece_tcg"
    b = "ONE PIECE JAPANESE PRB02-PREMIUM BOOSTER -ONE PIECE CARD THE BEST- VOL.2"
    assert G.pick(op, b, "COME/WE'LL FIGHT YOU ALTERNATE ART", "OP09-020_PRB02")[0] == "OP09-020_PRB02"
    assert G.pick(op, b, "COME/WE'LL FIGHT YOU ALTERNATE ART", "OP09-020")[0] == ""    # PRB02 に絵が2つ
    assert G.pick(op, "ONE PIECE JAPANESE STARTER DECK ST18-PURPLE MONKEY D. LUFFY", "MONKEY D. LUFFY",
                  "OP05-060_ST18")[0] in ("OP05-060_ST18",)
    assert G.has_alt_mark("CARROT SPECIAL")


def test_alias_with_matching_body_returns_body():
    assert G.pick("one_piece_tcg", "ONE PIECE JAPANESE OP01-ROMANCE DAWN", "DRACULE MIHAWK ALTERNATE ART",
                  "OP01-070_OP-01")[0] == "OP01-070_p1"
