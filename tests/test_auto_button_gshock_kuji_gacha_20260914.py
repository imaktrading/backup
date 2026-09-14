# -*- coding: utf-8 -*-
"""🤖自動 を G-SHOCK / 一番くじ / ガチャ にも付ける (2026-09-14・残務 №63、№14 統合)。

回答書 2026-09-14_auto_button_gshock_kuji_gacha_response.md の実装確認。
締めのチェーン (監査→入稿→書戻し→広告→メール) は商材に依存しない共通コード
(auto_csv_prefix_of / _run_auto_full_tail) なので、ここでは **SCRIPTS のボタン定義**
と **各生成器の件数枠 (PSA の20枠と別)** だけを見る。分岐を足していないこと
(値だけ持たせていること) を確認する。
"""
import importlib.util
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "iMakHQ", ROOT / "iMakHQ" / "tools", ROOT / "iMakeBayAPI"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import control_panel as CP  # noqa: E402


def _auto_entries():
    return [e for e in CP.SCRIPTS if e.get("auto_full")]


def _entries(category, type_):
    return [e for e in CP.SCRIPTS if e.get("category") == category and e.get("type") == type_]


# ── G-SHOCK ──────────────────────────────────────────────────────────


def test_gshock_has_an_auto_button():
    e = _entries("G-SHOCK", "auto")
    assert len(e) == 1
    entry = e[0]
    assert entry["auto_full"] is True
    assert entry["auto_csv_prefix"] == "gshock_upload_"
    assert entry["auto_upload_write"] is True
    assert entry["auto_upload_schedule"] is True
    assert entry["verified"] is False, "初回は未検証のまま (実戦で確かめてから True にする)"
    assert entry["env"]["GSHOCK_BATCH_LIMIT"] == "20", "件数は PSA の20枠と別に持つ"
    assert CP.auto_csv_prefix_of(entry) == "gshock_upload_"


def test_gshock_generator_reads_batch_limit_env():
    """main() が GSHOCK_BATCH_LIMIT を読んで select_run_targets に渡す配線。"""
    src = io.open(ROOT / "iMakG-shock" / "gshock_to_csv.py", encoding="utf-8").read()
    i = src.index("def main():")
    body = src[i:]
    assert "GSHOCK_BATCH_LIMIT" in body
    a = body.index("GSHOCK_BATCH_LIMIT")
    b = body.index("select_run_targets(targets", a)
    assert "max_per_run=_max_per_run" in body[a:b + 120]


def test_gshock_select_run_targets_honors_custom_cap():
    """select_run_targets 自体は既存の純関数。env で渡した上限がそのまま効くことを確認。"""
    _GSHOCK = os.path.normpath(str(ROOT / "iMakG-shock" / "gshock_to_csv.py"))
    spec = importlib.util.spec_from_file_location("gshock_to_csv_batchcap", _GSHOCK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    targets = [("url%d" % n, "model%d" % n, "") for n in range(30)]
    picked = mod.select_run_targets(targets, no_shuffle=True, max_per_run=20)
    assert len(picked) == 20
    picked_default = mod.select_run_targets(targets, no_shuffle=True)
    assert len(picked_default) == mod.MAX_PER_RUN == 10, "env 未設定時は既存の既定値のまま (無変更)"


# ── 一番くじ ─────────────────────────────────────────────────────────


def test_ichibankuji_has_an_auto_button():
    e = _entries("一番くじ", "auto")
    assert len(e) == 1
    entry = e[0]
    assert entry["auto_full"] is True
    assert entry["auto_csv_prefix"] == "ichibankuji_upload_"
    assert entry["auto_upload_write"] is True
    assert entry["auto_upload_schedule"] is True
    assert entry["verified"] is False
    assert entry["env"]["ICHIBANKUJI_BATCH_LIMIT"] == "20"
    assert CP.auto_csv_prefix_of(entry) == "ichibankuji_upload_"


def test_ichibankuji_new_button_unchanged():
    """既存の「新規」ボタン (custom_buttons=ichibankuji) は触らない。"""
    e = _entries("一番くじ", "new")
    assert len(e) == 1
    assert e[0].get("custom_buttons") == "ichibankuji"


def test_ichibankuji_generator_reads_batch_limit_env():
    src = io.open(ROOT / "iMak_ichibankuji" / "ichibankuji_to_csv.py", encoding="utf-8").read()
    i = src.index("def _process_sheet_to_ebay_csv():")
    body = src[i:]
    assert "ICHIBANKUJI_BATCH_LIMIT" in body
    assert "targets = targets[:_batch]" in body


# ── ガチャ (パネルにボタンが1つも無かった) ──────────────────────────


def test_gacha_new_and_auto_buttons_wired():
    new_e = _entries("ガチャ", "new")
    auto_e = _entries("ガチャ", "auto")
    assert len(new_e) == 1, "ガチャの新規ボタンが無い"
    assert len(auto_e) == 1, "ガチャの 🤖自動 が無い"
    auto = auto_e[0]
    assert auto["auto_full"] is True
    assert auto["auto_csv_prefix"] == "gacha_upload_"
    assert auto["auto_upload_write"] is True
    assert auto["auto_upload_schedule"] is True
    assert auto["verified"] is False
    # 既存の --limit をそのまま使う (env を新設しない)
    assert "--limit" in auto["cmd"] and "20" in auto["cmd"]
    assert CP.auto_csv_prefix_of(auto) == "gacha_upload_"


# ── 共通: auto ボタンは新規出品用 dedupe (KEY excluder) を skip しない ──


def test_all_three_new_auto_buttons_run_postprocess_dedupe():
    for cat in ("G-SHOCK", "一番くじ", "ガチャ"):
        e = _entries(cat, "auto")[0]
        assert CP._runs_new_listing_dedupe(e) is True


def test_all_three_never_publish_immediately():
    """予約出品 (auto_upload_schedule) を必ず伴う。中身を確かめる前に即公開しない。"""
    for cat in ("G-SHOCK", "一番くじ", "ガチャ"):
        e = _entries(cat, "auto")[0]
        if e.get("auto_upload_write", True):
            assert e.get("auto_upload_schedule") is True


def test_no_category_branch_introduced_in_shared_tail():
    """共通の締め (_run_auto_full_tail) に商材の if 分岐を足していないこと。"""
    src = io.open(ROOT / "iMakHQ" / "control_panel.py", encoding="utf-8").read()
    i = src.index("def _run_auto_full_tail(")
    j = src.index("\ndef ", i + 10)
    body = src[i:j]
    for bad in ("G-SHOCK", "一番くじ", "ガチャ", "gshock_upload_", "ichibankuji_upload_",
                "gacha_upload_"):
        assert bad not in body, f"共通コードに商材固有の分岐/値 ({bad!r}) が混入している"
