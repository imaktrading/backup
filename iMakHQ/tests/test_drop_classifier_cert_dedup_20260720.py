# -*- coding: utf-8 -*-
"""drop_classifier: 件数照合を **cert 単位** で数える回帰テスト (2026-07-20)。

背景 (同型3回目):
  1回目 2026-07-10 promo fallback 救済の二重計上 → 救済判定で解消
  2回目 2026-07-17 reprint fallback を文言決め打ちで拾えず再発 → 構造(隣接行)判定で解消
  3回目 2026-07-20 **別経路の二重計上**: 同じ1枚が
     「未登録: CP4-075」(card_id 経路) と「目視未確定: #156576106」(cert 経路)
     の二本のログ行で拾われ、seen が別キーのため 2 回数えられた
     (実ログ ___20260720_193045.log で CP4-075 = cert 156576106 と確定)。
     → 誤警報「処理10 ≠ 成功5+落ち6 (差-1)」。

方針: drop の実体は **cert**。card_id しか無い finding (収録漏れ/scope外/promo衝突) は
  その drop の「理由説明」であって別の drop ではないので計上しない。
  cert 情報が無い旧形式ログでは従来どおり件数で数える(後方互換)。
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "tools")))
import drop_classifier as dc  # noqa: E402

SET_OK = lambda p: True      # noqa: E731  セットは catalog 内 = 「収録漏れ」に倒す

# 2026-07-20 実 run の形（処理10 / 成功5 / 目視未確定4 / DON1 / 未登録1(=cert156576106の理由)）
REAL_LOG = (
    "10件を処理します。（仕入値あり: 10件）\n"
    "  ⏭️ 既出品(同KEYが出品済)の2枚目を除外: 51件\n"
    "  ⏭️ 目視済(NONE/NG, 14日以内)を除外: 8件\n"
    "    ⚠️ iMakCatalog (Pokemon) 未登録: CP4-075 → Skip (subject='M LUCARIO EX PREMIUM CHAMPION PACK')\n"
    "スキップ(目視未確定): #140273536\n"
    "スキップ(目視未確定): #156576106\n"
    "    ⏭️ Skip: reason=no_card_number_don DON!!カード番号欠落=変種特定不能 "
    "(cert 158452517, subject='DON!! CARD', treatment=無)\n"
    "スキップ(目視未確定): #147929071\n"
    "スキップ(目視未確定): #128424450\n"
    "成功: 5件 / 失敗: 1件\n"
)


def test_real_run_reconciles_without_double_count():
    """★本命: 2026-07-20 実 run で「処理10 = 成功5 + 落ち5」に一致する(誤警報 -1 の解消)。"""
    drops = dc.classify_drops(REAL_LOG, set_exists=SET_OK)
    msg = dc.reconcile_counts(REAL_LOG, drops)
    assert msg.startswith("✅"), f"件数照合が一致しない: {msg}"
    assert "処理10 = 成功5 + 落ち5" in msg


def test_card_id_only_finding_is_reported_but_not_counted():
    """収録漏れ(card_id のみ)は **報告はする** が drop には数えない(理由説明のため)。"""
    drops = dc.classify_drops(REAL_LOG, set_exists=SET_OK)
    kinds = [d["class"] for d in drops]
    assert "収録漏れ" in kinds, "CP4-075 の収録漏れが報告から消えてはいけない(Catalog 依頼に必要)"
    # cert を持つ finding だけが drop 実体
    certs = {d.get("cert") for d in drops if d.get("class") != "正常" and d.get("cert")}
    assert certs == {"140273536", "156576106", "147929071", "128424450", "158452517"}


def test_findings_carry_cert_or_none():
    """cert 経路には cert が入り、card_id 経路は None。"""
    drops = dc.classify_drops(REAL_LOG, set_exists=SET_OK)
    by = {d["class"]: d for d in drops if d.get("class") != "正常"}
    assert by["収録漏れ"]["cert"] is None
    assert by["該当なし(catalog欠)"]["cert"] is not None
    assert by["DON!!識別可(要catalog)"]["cert"] == "158452517"


def test_same_cert_twice_counted_once():
    """同一 cert が複数行で出ても 1 drop（seen 併用の確認）。"""
    log = ("3件を処理します。\n"
           "スキップ(目視未確定): #111111\n"
           "スキップ(目視未確定): #111111\n"
           "成功: 2件\n")
    drops = dc.classify_drops(log, set_exists=SET_OK)
    assert dc.reconcile_counts(log, drops).startswith("✅")


def test_legacy_log_without_cert_still_counted():
    """後方互換: cert を持つ finding が皆無なら従来どおり件数で数える(取りこぼし防止)。"""
    log = ("2件を処理します。\n"
           "    ⚠️ iMakCatalog (Pokemon) 未登録: SM9a-067 → Skip\n"
           "成功: 1件\n")
    drops = dc.classify_drops(log, set_exists=SET_OK)
    msg = dc.reconcile_counts(log, drops)
    assert msg.startswith("✅"), msg
    assert "成功1 + 落ち1" in msg


def test_real_silent_drop_still_flagged():
    """★fail-closed: 説明の無い本物の取りこぼしは従来どおり警告する(狼少年化の逆振れ防止)。"""
    log = ("10件を処理します。\n"
           "スキップ(目視未確定): #111111\n"
           "成功: 5件\n")            # 10 ≠ 5+1 → 4件が無説明
    drops = dc.classify_drops(log, set_exists=SET_OK)
    msg = dc.reconcile_counts(log, drops)
    assert msg.startswith("⚠️") and "差4件" in msg
