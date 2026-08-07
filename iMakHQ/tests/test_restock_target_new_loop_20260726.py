"""「新規再仕入れ可がN件見つかるまで検索」ループの停止判定カウンタ回帰テスト (2026-07-26)。

ユーザー要望「10件検索して2件でなく、10件の補が見つかるまで探して」。SNKRDUNK(全件)先取り →
メルカリを保留分チャンク検索し、_count_new_resourceable_from(pairs, processed) が target に達したら停止。
= 視覚確証HTMLに出る件数(確定/レビュー済を除外)と一致させる純カウンタ。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from psa_resource_gate import _count_new_resourceable_from as count


def test_counts_only_resourceable():
    pairs = [(True, "A"), (False, "B"), (True, "C")]
    assert count(pairs, set()) == 2   # B は不能=数えない


def test_excludes_processed():
    pairs = [(True, "A"), (True, "B"), (True, "C")]
    assert count(pairs, {"B"}) == 2   # B は確定/レビュー済=除外


def test_dedup_same_itemid():
    pairs = [(True, "A"), (True, "A")]
    assert count(pairs, set()) == 1   # 同 itemID の二重は1件


def test_empty_itemid_counted():
    # join 不能(itemID空)の resourceable も確証には出る → 新規として数える
    pairs = [(True, ""), (True, ""), (True, "A")]
    assert count(pairs, set()) == 3


def test_empty_pairs():
    assert count([], {"A"}) == 0


def test_target_reached_semantics():
    # 保留を掘るほど resourceable が増える → target(3)到達で停止できる件数遷移
    base = [(True, "done1"), (True, "done2")]        # 既処理2
    processed = {"done1", "done2"}
    assert count(base, processed) == 0               # 起点=新規0
    after1 = base + [(True, "N1"), (False, "x"), (True, "N2")]
    assert count(after1, processed) == 2             # 1チャンクで新規2
    after2 = after1 + [(True, "N3")]
    assert count(after2, processed) == 3             # 2チャンクで target3到達
