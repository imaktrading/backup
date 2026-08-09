# -*- coding: utf-8 -*-
"""必須spec の退役判定を canonical product_id で行う (2026-08-09 / 残務 №90).

真因 (2026-08-08 実測):
    除外リストは canonical product_id (`MC-746` `S8b-101`) で判定するのに、
    渡していたのは identity 先頭 = CSV の `C:Card Number`
    (= 印刷された「番号/総数」`746/742` `101/184`)。
    One Piece / Gundam は `OP04-119` 形式なので偶然一致していたが、
    **Pokemon は最初から一度も当たらない**。7/29-7/30 に足した
    `mc-` `si-` `cp4-` `cp5-` `s8b-` `m2a-` `sm8b-` `sv4a-` `s6k-` `xy-` `hszm-` は
    **1件も発火していなかった**。
    → 公式に rarity が無い Pokemon が毎日 defect に残り、catalog へ draft を
      毎日投げ続けていた (「同じ件が何度も来る」の現役の発生源)。

固定する挙動:
  1. cert から canonical PID を引けたら、それを判定キーにする
  2. 引けなければ従来どおり印刷番号で判定 (悪化させない)
  3. **set 単位のリストで表現できない「1枚だけ公式に無い」は catalog で判定する**
     (S10b は 93件中85件が rarity を持つので prefix 除外は誤り)
  4. catalog に値が有るのに CSV が空 = generator 脱落 → **defect のまま残す**
  5. 判定不能は全て「必須のまま」に倒す (fail-closed)
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, r"C:\dev\iMak\iMakHQ\tools")
sys.path.insert(0, r"C:\dev\iMak\iMakTCG")
import csv_auditor as A  # noqa: E402
import pdca_store as P  # noqa: E402


def _seed(monkeypatch, mapping):
    monkeypatch.setattr(A, "_VERIFIED_PID_CACHE", mapping, raising=False)


# ---- 1〜2. 判定キー -----------------------------------------------------------


def test_canonical_pid_is_read_from_verified_certs(monkeypatch):
    _seed(monkeypatch, {"159792618": {"choice": "CHOSEN", "product_id": "MC-746"}})
    assert A.canonical_pid_for_item("PSA10-159792618") == "MC-746"


def test_unconfirmed_choice_is_not_used(monkeypatch):
    _seed(monkeypatch, {"1": {"choice": "NONE", "product_id": "MC-746"}})
    assert A.canonical_pid_for_item("PSA10-1") == ""


def test_non_psa_item_id_returns_empty(monkeypatch):
    _seed(monkeypatch, {"1": {"choice": "CHOSEN", "product_id": "MC-746"}})
    assert A.canonical_pid_for_item("m12345678") == ""
    assert A.canonical_pid_for_item("") == ""


def test_printed_number_never_matched_the_exclusion_list(monkeypatch):
    """真因の再現: 印刷番号のままでは `mc-` prefix に当たらない。"""
    _seed(monkeypatch, {})
    assert A._still_required_spec("746/742", "Weavile", "C:Rarity") is True


def test_canonical_pid_makes_the_exclusion_list_fire(monkeypatch):
    _seed(monkeypatch, {"159792618": {"choice": "CHOSEN", "product_id": "MC-746"}})
    assert A._still_required_spec("746/742", "Weavile", "C:Rarity",
                                  "PSA10-159792618") is False


# ---- 3〜4. カード単位の判定 ---------------------------------------------------


def test_card_without_catalog_rarity_is_retired(monkeypatch):
    """S10b-055 (かがやくイーブイ) は公式に rarity 表記が無い → defect ではない。"""
    _seed(monkeypatch, {"156045928": {"choice": "CHOSEN", "product_id": "S10b-055"}})
    monkeypatch.setattr(A, "_catalog_has_spec_value", lambda pid, f: False)
    assert A._still_required_spec("055/071", "Radiant Eevee", "C:Rarity",
                                  "PSA10-156045928") is False


def test_card_with_catalog_rarity_stays_a_defect(monkeypatch):
    """catalog に値が有るのに CSV が空 = generator 脱落。**消さない**。"""
    _seed(monkeypatch, {"1": {"choice": "CHOSEN", "product_id": "S10b-001"}})
    monkeypatch.setattr(A, "_catalog_has_spec_value", lambda pid, f: True)
    assert A._still_required_spec("001/071", "Some Card", "C:Rarity", "PSA10-1") is True


def test_set_prefix_exclusion_is_not_widened_to_s10b():
    """S10b は 93件中85件 (91%) が rarity を持つ。prefix で落とすと85枚を見逃す。"""
    from check_csv import required_specifics_for_card
    assert "C:Rarity" in required_specifics_for_card("S10b-001", "Some Card"), \
        "S10b を set 単位で除外してしまっている"


# ---- 5. fail-closed -----------------------------------------------------------


def test_unmapped_field_is_left_alone():
    assert A._catalog_has_spec_value("MC-746", "C:Character") is True


def test_unknown_product_is_left_alone():
    assert A._catalog_has_spec_value("NO-SUCH-ID-9999", "C:Rarity") is True


def test_non_c_field_is_always_required():
    assert A._still_required_spec("MC-746", "Weavile", "*Title") is True


# ---- pruner が item_id を渡している ------------------------------------------


def test_pruner_passes_item_id_and_tolerates_old_signature():
    """3引数しか受けない実装でも壊れないこと (後方互換)。"""
    import sqlite3
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE improvement_queue (queue_id INTEGER PRIMARY KEY, item_id TEXT,"
                " identity TEXT, target_field TEXT, status TEXT, updated_ts TEXT,"
                " finding_type TEXT, reviewed_ts TEXT)")
    con.execute("INSERT INTO improvement_queue VALUES (1,'PSA10-159792618',"
                "'746/742 | Weavile','C:Rarity','pending','','必須Item Specific','')")
    con.commit()

    seen = {}

    def four_args(num, name, field, item_id):
        seen["item_id"] = item_id
        return False

    P.prune_non_applicable_specs(con, four_args, ts="t")
    assert seen["item_id"] == "PSA10-159792618", "item_id を渡していない"

    con.execute("UPDATE improvement_queue SET status='pending'")
    con.commit()
    P.prune_non_applicable_specs(con, lambda n, m, f: False, ts="t")   # 旧3引数
    st = con.execute("SELECT status FROM improvement_queue").fetchone()[0]
    assert st == "resolved", "旧シグネチャで動かなくなっている"
