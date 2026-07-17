# -*- coding: utf-8 -*-
"""drop_classifier: fallback 救済の二重計上を **経路非依存** で防ぐ回帰テスト (2026-07-17)。

背景 (同型2回目):
  2026-07-10 に「promo fallback で救済された品を drop に二重計上しない」修正を入れたが、
  救済検出が文言 'promo fallback' 決め打ちだったため、**reprint fallback**(再録版マッチ)
  経由の救済を拾えず再発した。実害: 処理10 ≠ 成功8+落ち4 (差-2) の誤警報。
  件数照合は「silent drop を検出する仕組み」そのものなので、ここが狼少年化すると
  本物の silent drop を見逃す (状態同期の安全原則③)。

方針: 文言ではなく **reject の直後行に fallback hit が出る構造** で判定する。
  → 新種の fallback が増えても文言追従なしで拾える。本テストは「promo/reprint/未知の新種」を
    同じ構造で守り、3度目の同型再発を止める。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import drop_classifier as dc  # noqa: E402

SET_OK = lambda p: True  # noqa: E731

# 実ログ (run_logs/___20260717_192239.log) の実際の形をそのまま使う
REJECT_SMOKER = ("    ⚠️ iMakCatalog ID hit OP13-030 (Tony Tony Chopper) だが PSA Subject "
                 "'SMOKER SPECIAL ALTERNATE ART' と名前不一致 → reject")
RESCUE_REPRINT = ("    🎯 iMakCatalog hit (reprint fallback): OP10-030_OP13_p2 Smoker "
                  "(PSA set=OP13 の再録版、1件中, SP Alt 優先)")
REJECT_SANJI = ("    ⚠️ iMakCatalog ID hit P-013 (ゴードン) だが PSA Subject 'SANJI' と名前不一致 → reject")
RESCUE_PROMO = ("    🎯 iMakCatalog hit (promo fallback): OP01-013_p1 サンジ "
                "(Subject='SANJI' brand='X' と一致, 11件中 score=280)")


def test_reprint_fallback_rescue_is_not_a_drop():
    """★本命: reprint fallback 救済品を drop に数えない (2026-07-17 再発の直接回帰)。"""
    log = f"{REJECT_SMOKER}\n{RESCUE_REPRINT}\n"
    drops = dc.classify_drops(log, set_exists=SET_OK)
    assert not any(d["class"] == "promo衝突" for d in drops), \
        "reprint fallback で救済済(build成功)の品が drop に二重計上されている"


def test_promo_fallback_rescue_still_works():
    """既存の promo 経路を壊していない (2026-07-10 の修正の回帰)。"""
    log = f"{REJECT_SANJI}\n{RESCUE_PROMO}\n"
    assert not any(d["class"] == "promo衝突" for d in dc.classify_drops(log, set_exists=SET_OK))


def test_unknown_future_fallback_kind_is_rescued():
    """★構造で拾う: 未知の新種 fallback でも文言追従なしで救済扱い (3度目の再発防止)。"""
    log = (f"{REJECT_SANJI}\n"
           "    🎯 iMakCatalog hit (someday-new fallback): XX-001 サンジ (将来の新経路)\n")
    assert not any(d["class"] == "promo衝突" for d in dc.classify_drops(log, set_exists=SET_OK)), \
        "新種 fallback を拾えない = 文言依存が残っている"


def test_reject_without_rescue_is_still_flagged():
    """fail-closed: 救済されない純粋な reject は従来どおり問題提起する (見落とし禁止)。"""
    log = f"{REJECT_SMOKER}\n    📷 カード画像取得成功\n"
    drops = dc.classify_drops(log, set_exists=SET_OK)
    assert any(d["class"] == "promo衝突" and d["item"] == "OP13-030" for d in drops)


def test_non_adjacent_fallback_does_not_rescue_unrelated_reject():
    """fail-closed: 別カードの fallback が離れた reject を誤って救済しない。

    誤救済 = 本物の drop が消える = silent drop(より危険)。取りこぼしは件数不一致で surface される。
    """
    log = (f"{REJECT_SMOKER}\n"
           "    📷 カード画像取得成功\n"
           " → #012 MONKEY D. LUFFY ✓\n"
           f"{RESCUE_PROMO}\n")
    drops = dc.classify_drops(log, set_exists=SET_OK)
    assert any(d["item"] == "OP13-030" for d in drops), \
        "隣接していない fallback が無関係の reject を誤救済した(silent drop 化)"


def test_reconcile_ok_on_real_log_shape():
    """★2026-07-17 実 run の形状で 処理10 = 成功8 + 落ち2 が一致する (誤警報 -2 の解消を実証)。

    実 run: 処理10 / 成功8 / reprint救済2(=成功に含まれる) / DON!!1 / 該当なし1 / 正常2。
    修正前は救済2を落ちにも数えて 8+4=12 ≠ 10 (差-2) の誤警報だった。
    """
    log = ("10件を処理します。（仕入値あり: 10件）\n"
           f"{REJECT_SMOKER}\n{RESCUE_REPRINT}\n"
           f"{REJECT_SANJI}\n{RESCUE_PROMO}\n"
           "  ⏭️ 既出品(同KEYが出品済)の2枚目を除外: 50件\n"
           "  ⏭️ 目視済(NONE/NG, 14日以内)を除外: 9件\n"
           "    ⏭️ Skip: reason=no_card_number_don DON!!カード番号欠落=変種特定不能 "
           "(cert 158452519, subject='DON!! CARD', treatment=無)\n"
           "スキップ(目視未確定): #158452535\n"
           "成功: 8件 / 失敗: 1件\n")
    drops = dc.classify_drops(log, set_exists=SET_OK)
    msg = dc.reconcile_counts(log, drops)
    assert msg.startswith("✅"), f"件数照合が一致しない: {msg}"
    assert "処理10 = 成功8 + 落ち2" in msg


def test_rescued_subjects_pure_function():
    """救済 subject 抽出そのもの (純関数)。"""
    log = f"{REJECT_SMOKER}\n{RESCUE_REPRINT}\n{REJECT_SANJI}\n{RESCUE_PROMO}\n"
    got = dc.rescued_subjects(log)
    assert got == {"SMOKER SPECIAL ALTERNATE ART", "SANJI"}
