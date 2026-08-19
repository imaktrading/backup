# -*- coding: utf-8 -*-
"""目視 skip 台帳が catalog 修正に追随する (2026-08-09).

なぜ:
    目視で NONE を付けた**当時の**判断が台帳に焼き付き、catalog が直っても
    誰も見直していなかった。cooldown(14日) が切れるたび同じ cert が浮上し、
    また NONE 扱いで沈む。**実測: 台帳49件のうち29件は、その時点で既に
    出品と同じ resolver が canonical product_id を返せた**
    (PERONA cert153420191 = 3ヶ月で20回以上 catalog に蒸し返された件を含む)。

固定する挙動:
  1. cooldown 中でも、今 catalog で引けるなら **スキップしない**
  2. 引けないものは従来どおりスキップ (目視の再出題を無駄に増やさない)
  3. cooldown を過ぎたものは従来どおり再浮上
  4. 判定不能 (catalog 不能 / cache 無し / 例外) は **何も外さない** = fail-closed
  5. 判定は psa_preflight に SSOT。ここで再実装しない
"""
from __future__ import annotations

import datetime
import os
import sys

sys.path.insert(0, r"C:\dev\iMak\iMakTCG")
import tcg_batch_select as B  # noqa: E402

NOW = datetime.datetime(2026, 8, 9, 12, 0, 0)


def _ledger(*certs, days_ago=1):
    at = (NOW - datetime.timedelta(days=days_ago)).isoformat()
    return {c: {"at": at, "choice": "NONE"} for c in certs}


# ---- 1. 引けるようになったら止めない ----------------------------------------


def test_resolvable_cert_is_not_skipped_even_inside_cooldown():
    # ★2026-08-19: cooldown を 14日 → 1日 にしたので、cooldown 内であることを
    #   日数で表さず **明示** する (この test が見ているのは自己修復であって長さではない)。
    skips = _ledger("111", "222", days_ago=0)
    got = B.active_review_skips(skips, NOW, resolvable={"111"}, out_of_scope=set(),
                                cooldown_days=B.REVIEW_SKIP_COOLDOWN_DAYS)
    assert got == {"222"}, "catalog で引けるのに止めている"


def test_all_resolvable_means_nothing_is_skipped():
    skips = _ledger("111", "222", days_ago=3)
    assert B.active_review_skips(skips, NOW, resolvable={"111", "222"},
                                 out_of_scope=set()) == set()


# ---- 2. 引けないものは従来どおり ---------------------------------------------


def test_unresolvable_stays_skipped():
    skips = _ledger("333", days_ago=0)          # cooldown 内 (長さに依存させない)
    assert B.active_review_skips(skips, NOW, resolvable=set(), out_of_scope=set()) == {"333"}


# ---- 3. cooldown 経過は従来どおり再浮上 --------------------------------------


def test_expired_cooldown_resurfaces_regardless():
    skips = _ledger("444", days_ago=99)
    assert B.active_review_skips(skips, NOW, resolvable=set(), out_of_scope=set()) == set()


# ---- 4. 判定不能は何も外さない (fail-closed) ---------------------------------


def test_resolvable_now_returns_empty_when_classify_unavailable():
    """catalog を読めない時に「引ける」に倒さない。"""
    def boom(cert):
        raise RuntimeError("catalog import 不能")
    assert B.resolvable_now(["111", "222"], classify_fn=boom) == set()


def test_missing_resolver_is_reported_not_silent(monkeypatch, capsys):
    """判定器が読めない時は **黙って no-op しない**。

    ここが静かに死ぬと「自己修復を入れた」つもりのまま14日ループが復活し、
    しかも誰も気づかない。実際 2026-08-09 に、テストの実行順によって
    psa_preflight の import が通らない状況が起きた。
    """
    monkeypatch.setattr(B, "load_resolver", lambda: None)
    assert B.resolvable_now(["111"]) == set()
    assert "1件も解除しません" in capsys.readouterr().out


def test_resolvable_now_ignores_non_resolved_status():
    st = {"111": "RESOLVED", "222": "GAP", "333": "REVIEW", "444": None}
    assert B.resolvable_now(list(st), classify_fn=st.get) == {"111"}


def test_empty_input_is_safe():
    assert B.resolvable_now([]) == set()
    assert B.resolvable_now(None) == set()


def test_skip_ledger_empty_is_safe():
    assert B.active_review_skips({}, NOW, out_of_scope=set()) == set()
    assert B.active_review_skips(None, NOW, out_of_scope=set()) == set()


# ---- 6. 恒久 対象外 は cooldown/自己修復と無関係に常に止める ------------------
#
# ★自己修復だけ入れると「永久に引けないカードが14日ごとに永久に浮上する」穴ができる。
#   SDBH (スーパードラゴンボールヒーローズ) は catalog が「意図的な非対応」と回答済
#   (Fusion World 専用 scraper / DB 0件 / filter_map にも無し)。引ける日は来ない。


def test_out_of_scope_is_skipped_even_after_cooldown_expires():
    skips = _ledger("777", days_ago=999)          # cooldown はとっくに切れている
    got = B.active_review_skips(skips, NOW, resolvable=set(), out_of_scope={"777"})
    assert got == {"777"}, "恒久対象外が cooldown 経過で浮上している"


def test_out_of_scope_is_skipped_even_if_ledger_has_no_entry():
    """台帳に載っていなくても、恒久対象外なら止める。"""
    got = B.active_review_skips({}, NOW, resolvable=set(), out_of_scope={"777"})
    assert got == {"777"}


def test_out_of_scope_wins_over_self_heal():
    """resolver がたまたま何か引いても、参入しないゲームは出さない。"""
    skips = _ledger("777", days_ago=1)
    got = B.active_review_skips(skips, NOW, resolvable={"777"}, out_of_scope={"777"})
    assert got == {"777"}, "自己修復が恒久対象外を解除してしまっている"


def test_out_of_scope_file_ignores_note_keys(tmp_path):
    """`_note` のような注記キーを cert として扱わない。"""
    p = tmp_path / "oos.json"
    p.write_text('{"_note": "説明", "111": {"reason": "SDBH"}}', encoding="utf-8")
    assert B.load_out_of_scope(str(p)) == {"111"}


def test_out_of_scope_missing_file_is_empty():
    """読めなければ空 = 誰も止めない側。勝手に出品を止めない。"""
    assert B.load_out_of_scope(r"C:\nope\missing.json") == set()


def test_real_out_of_scope_file_holds_sdbh_and_not_the_shenron_cert():
    """実ファイルの中身を固定する。

    cert158452540 (SHENRON ALTERNATE ART #FB07-097) は **入れてはいけない**。
    catalog draft は SDBH として denylist 入りを提案してきたが、実測で
    `FB07-097 = 神龍 / ブースターパック 神龍への願い[FB07]` が **10件実在**した。
    Fusion World の正規カードなので、引き方 (②) を直す対象。
    """
    got = B.load_out_of_scope()
    assert "158452540" not in got, "実在する Fusion World カードを恒久対象外にしている"
    for sdbh in ("135885792", "91207615", "158452557", "158452575"):
        assert sdbh in got, f"SDBH cert {sdbh} が恒久対象外に入っていない"


# ---- 5. 判定を2箇所に実装していない ------------------------------------------


def test_resolution_logic_is_not_reimplemented():
    src = open(B.__file__, encoding="utf-8").read()
    assert "psa_preflight" in src, "判定は psa_preflight に SSOT のはず"
    for reimpl in ("lookup_one_piece", "lookup_pokemon", "SELECT 1 FROM products"):
        assert reimpl not in src, f"resolver を再実装している: {reimpl}"


# ---- 実データでの回帰 (cache がある環境でのみ) --------------------------------


def test_perona_is_resolvable_on_real_catalog():
    """cert153420191 (PERONA) = 3ヶ月で20回以上 catalog に蒸し返された件。

    catalog はとっくに直っていて、止めていたのはこちら側だった。
    実機に cert cache が無い環境では skip。
    """
    import pytest
    cache = r"C:\dev\iMak\iMakeBayAPI\cache\psa_certs\153420191.json"
    if not os.path.exists(cache):
        pytest.skip("cert cache が無い環境")
    clf = B.load_resolver()
    if clf is None:
        # 他テストが catalog 側モジュールを先に掴むと import が通らないことがある。
        # その時は **判定不能** であって「引けない」ではない (fail-closed の設計どおり)。
        pytest.skip("この実行順では判定器を読めない (fail-closed で何も外さない)")
    assert B.resolvable_now(["153420191"], classify_fn=clf) == {"153420191"}
