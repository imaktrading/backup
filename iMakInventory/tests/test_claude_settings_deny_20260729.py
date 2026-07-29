"""`.claude/settings.json` の deny list 回帰テスト.

依頼書 (HQ→Inventory):
- `C:/dev/iMak_data/inventory/requests/2026-07-29_permission_deny_for_irreversible_ops.md`
- 承認回答: `..._response.md` ([IMPLEMENT-GO])

Claude Code の worktree ローカル権限設定に、戻せない破壊コマンドを deny で
封じている。この設定が抜けると:

- `git push --force` / `git reset --hard` / `rm -rf` を Claude が勝手に叩ける
- `_clear_sku_sheet.py` (1 回限定初期化) を誤走らせて SKU シート全消し

の事故が起きる。deny 定義の欠落を回帰検知する。

**Cron 本業 (`run_cycle.py` / `revise_qty_csv_generator.py` 等) は絶対 deny 対象外**。
入っていたら 8h 毎の巡回が止まって在庫切れ品が残り Defect Rate → 永久 BAN。
`_forbidden_deny_patterns` で「入ってはいけないもの」も同時に守る。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.offline

# tests/ → iMakInventory/ → worktree root
_WORKTREE_ROOT = Path(__file__).resolve().parents[2]
_SETTINGS_PATH = _WORKTREE_ROOT / ".claude" / "settings.json"

_REQUIRED_DENY_PATTERNS = {
    "Bash(git push --force*)",
    "Bash(git push -f*)",
    "Bash(git reset --hard*)",
    "Bash(rm -rf *)",
    "Bash(rm -fr *)",
    "Bash(*_clear_sku_sheet.py*)",
}

_FORBIDDEN_DENY_SUBSTRINGS = (
    "run_cycle.py",
    "run_daily.py",
    "reverse_audit.py",
    "trading_api_client.py",
    "trading_api_uploader.py",
    "revise_csv_generator.py",
    "revise_qty_csv_generator.py",
    "audit_and_heal.py",
    "auto_qty_zero.py",
    "ebay_qty_sync.py",
    "sell_feed_uploader.py",
    "release_holdouts.py",
    "supervised_backup_drain.py",
    "drain_stale_holdouts.py",
)


def _load_settings() -> dict:
    assert _SETTINGS_PATH.exists(), (
        f"{_SETTINGS_PATH} が存在しない。deny 設定が抜けると壊せる操作が野放しになる。"
        " 依頼書 2026-07-29_permission_deny_for_irreversible_ops.md 参照。"
    )
    return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))


def test_settings_file_is_valid_json():
    data = _load_settings()
    assert isinstance(data, dict)
    assert "permissions" in data


def test_default_mode_is_bypass_permissions():
    """グローバルは bypassPermissions 継承。ここが acceptEdits/prompt に変わると
    cron 手動再走時に確認ダイアログで止まる (HQ が 2026-07-29 まで踏んでいた地雷)."""
    data = _load_settings()
    assert data["permissions"].get("defaultMode") == "bypassPermissions"


def test_all_required_deny_patterns_present():
    data = _load_settings()
    deny = data["permissions"].get("deny", [])
    assert isinstance(deny, list)
    missing = _REQUIRED_DENY_PATTERNS - set(deny)
    assert not missing, (
        f"deny から必須 pattern が欠落: {sorted(missing)}."
        " 戻せない操作の歯止めが外れている。"
    )


def test_no_cron_business_scripts_in_deny():
    """cron 本業スクリプトが deny に入っていないことを守る.

    間違って `Bash(*run_cycle.py*)` 等を deny に入れると 1日13回の巡回が停止し
    在庫切れ品が残る → 買われる → キャンセル → Defect Rate → 永久 BAN.
    """
    data = _load_settings()
    deny = data["permissions"].get("deny", [])
    for pattern in deny:
        assert isinstance(pattern, str)
        for forbidden in _FORBIDDEN_DENY_SUBSTRINGS:
            assert forbidden not in pattern, (
                f"cron 本業スクリプト {forbidden!r} が deny pattern {pattern!r} に含まれている."
                " 8h 毎の巡回停止で在庫切れ取下げが死ぬ。"
            )


def test_deny_list_has_only_expected_entries():
    """未知の deny 追加は無害だが、意図せず増えていないかを見る回帰."""
    data = _load_settings()
    deny = set(data["permissions"].get("deny", []))
    unexpected = deny - _REQUIRED_DENY_PATTERNS
    assert not unexpected, (
        f"deny に予期しない pattern が増えている: {sorted(unexpected)}."
        " 追加意図を確認して、この test の _REQUIRED_DENY_PATTERNS を更新するか、"
        " cron 本業を巻き込んでいないか見直すこと。"
    )
