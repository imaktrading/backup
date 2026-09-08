# -*- coding: utf-8 -*-
"""PSA再仕入れ① のヒントは **押したら人が見る枚数** を出す (2026-09-08 ユーザー指摘).

ヒントが「残り1件」なのに HTML には 2件 出ていた。原因は数えている場所が違ったこと:
  ヒント = 3段目 (仕入元と見比べる) の actionable だけ
  HTML   = 1段目 (①現物 vs ②catalog の変種確認) = KEY未確定の行
①のボタンは「変種確認 → 探す → 仕入元と見比べる」の3段で、1段目が数字に無かった。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import psa_resource_gate as PG          # noqa: E402


def _iid(r):
    return r.get("ebay_url", "")


def test_key_on_row_is_not_counted():
    """行が既に KEY を持っていれば目視に出ない。"""
    rows = [{"ebay_url": "a", "key": "one_piece_tcg:OP01-001"}]
    assert PG.count_variant_todo(rows, {}, {}, {}, set(), item_id=_iid) == 0


def test_itemid_join_resolves_key():
    """商品管理シートの itemID join で KEY が決まる行も出ない。"""
    rows = [{"ebay_url": "a"}]
    assert PG.count_variant_todo(rows, {"a": "pokemon_tcg:S4a-323"}, {}, {}, set(),
                                 item_id=_iid) == 0


def test_verified_cert_resolves_key():
    """出品時の目視確定 (cert→KEY) も資産として効く = 二度 目視させない。"""
    rows = [{"ebay_url": "a"}]
    cert_map = {"a": "cert123"}
    verified = {"cert123": {"choice": "OK", "product_id": "pokemon_tcg:S4a-323"}}
    assert PG.count_variant_todo(rows, {}, cert_map, verified, set(), item_id=_iid) == 0


def test_unresolved_row_is_counted():
    """どれでも決まらない行だけが目視に出る。"""
    rows = [{"ebay_url": "a"}, {"ebay_url": "b"}, {"ebay_url": "c", "key": "k"}]
    assert PG.count_variant_todo(rows, {}, {}, {}, set(), item_id=_iid) == 2


def test_already_confirmed_itemid_is_not_counted():
    """過去に目視で確定した itemID は再目視しない (PSA目視確定済タブ)。"""
    rows = [{"ebay_url": "a"}, {"ebay_url": "b"}]
    assert PG.count_variant_todo(rows, {}, {}, {}, {"a"}, item_id=_iid) == 1


def test_count_workload_exposes_variant_todo():
    """count_workload が variant_todo を返す形になっている (パネルが読む鍵)。"""
    src = open(os.path.join(ROOT, "tools", "psa_resource_gate.py"), encoding="utf-8").read()
    assert 'base["variant_todo"] = count_variant_todo(' in src


def test_panel_hint_uses_visual_count_not_actionable_only():
    """パネルの1行目は 変種確認 + 仕入元照合 の合計を出す (actionable 単独に戻さない)。"""
    src = open(os.path.join(ROOT, "control_panel.py"), encoding="utf-8").read()
    m = re.search(r'_vt = pg\.get\("variant_todo"\).*?pg_txt \+= "\\n\(候補', src, re.S)
    assert m, "psa_gate のヒント組み立てが見つからない"
    body = m.group(0)
    assert 'todo_line("psa_gate", (_vt or 0) + _ac, "目視します")' in body
    assert "変種の確認" in body, "内訳 (何段目が何件か) を出す"
    # 青くする条件も 変種確認だけ残っている場合を含む
    assert '"psa_gate": bool(pg.get("actionable") or pg.get("variant_todo"))' in src


def test_excluded_rows_are_not_counted():
    """RESTOCK対象外 (catalog非対応カテゴリ等) は本体が先に落とすので目視に出ない。

    ★2026-09-08 実測: Weiss Schwarz 2件が対象外に入っており、ここを引かないと
      ヒントが「変種の確認 2件」と出て、押すと「新規/未解決 0件」になっていた。
    """
    rows = [{"ebay_url": "a"}, {"ebay_url": "b"}]
    assert PG.count_variant_todo(rows, {}, {}, {}, set(), item_id=_iid,
                                 excluded={"a", "b"}) == 0
    assert PG.count_variant_todo(rows, {}, {}, {}, set(), item_id=_iid,
                                 excluded={"a"}) == 1


def test_count_workload_matches_body_on_cooldown_revival():
    """レビュー済の cooldown 復活を **本体と同じに** 数える (today を渡す)。

    本体はレビュー済を2か所で読む。視覚確証HTMLに何を出すかを決めるのは
    cooldown を見る側 (:1400) なので、ヒントもそちらに合わせる。
    ★2026-09-08 実測: 台帳8行のうち7件が本体では復活しており、
      ヒント1件に対し HTML は 2件出ていた。
    """
    src = open(os.path.join(ROOT, "tools", "psa_resource_gate.py"), encoding="utf-8").read()
    assert "processed = (_restock_confirmed_iids" in src, "count_workload の processed が見つからない"
    assert "_review_skip_iids(read_tab(REVIEW_SKIP_TAB), today=t)" in src


def test_review_skip_cooldown_revives_old_rows():
    """cooldown: 翌日以降の行は伏せない (= 再表示する)。日付不明は伏せたまま。"""
    rows = [["itemID", "no", "title", "reason", "date"],
            ["old", "", "", "", "2026-09-01"],
            ["new", "", "", "", "2026-09-08"],
            ["nodate", "", "", "", ""]]
    active = PG._review_skip_iids(rows, today="2026-09-08")
    assert "old" not in active, "cooldown 満了は復活する"
    assert "new" in active and "nodate" in active
    assert PG._review_skip_iids(rows) == {"old", "new", "nodate"}
