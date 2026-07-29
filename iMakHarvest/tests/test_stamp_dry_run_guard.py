"""dry_run 時 stamp を更新しない = 依頼書 _response.md §2 「最重要判断」の回帰固定.

「本番が回っていない」を dry_run で潰さないため、dry_run では**絶対に**stamp を書かない。
runner main() を mock 越しに走らせて、STAMP_PATH の存在有無で invariant を証明する。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.offline


class _FakeWs:
    """batch_update / get_all_values 対応の最小 worksheet mock."""

    def __init__(self, vals):
        self._vals = vals
        self.batch_calls: list = []

    def get_all_values(self):
        return self._vals

    def batch_update(self, updates, value_input_option=None):
        self.batch_calls.append(updates)


def _fake_source_json(tmp_path: Path) -> Path:
    p = tmp_path / "src.json"
    p.write_text(json.dumps([
        {"model": "GA-2100-1AJF", "url": "https://www.yodobashi.com/product/1/"},
    ]), encoding="utf-8")
    return p


def _patch_merge_runner(monkeypatch, tmp_path, stamp_dir: Path):
    """run_gshock_merge を SSD-only で回すための共通 mock 一式."""
    import run_gshock_merge as M

    # sheet-open 系を fake に差替
    ws = _FakeWs([
        ["url", "b", "title", "d", "e"],  # header
        # 型番一致 (AI=35列) の LOW 既存行、AC-AG は空
        ["https://existing/", "", "some title", "", ""] + [""] * 29 +
        ["GA-2100-1AJF"],
    ])
    monkeypatch.setattr(M, "open_sheet_by_id", lambda _id: "sheet")
    monkeypatch.setattr(M, "get_listings_worksheet", lambda _sh, _gid: ws)

    # STAMP_PATH を tmp_path 配下に差替 (実共有領域を汚さない)
    stamp = stamp_dir / "gshock_merge_stamp.json"
    monkeypatch.setattr(M, "STAMP_PATH", stamp)

    # NEW_CANDIDATES_JSON も tmp 配下に (副作用回避)
    monkeypatch.setattr(M, "NEW_CANDIDATES_JSON",
                        stamp_dir / "yodobashi_new_to_low.json")

    return M, ws, stamp


def test_gshock_merge_dry_run_does_not_write_stamp(monkeypatch, tmp_path):
    """dry_run=True → stamp file 作成されない (silent 死検知を dry で潰さない)."""
    src = _fake_source_json(tmp_path)
    M, ws, stamp = _patch_merge_runner(monkeypatch, tmp_path, tmp_path)

    rc = M.main(["--dry-run", "--source", str(src)])
    assert rc == 0
    assert not stamp.exists(), "dry_run で stamp が書かれた = 最重要 invariant 違反"
    # dry_run 中は batch_update も呼ばれない
    assert ws.batch_calls == []


def test_gshock_merge_real_run_writes_stamp(monkeypatch, tmp_path):
    """dry_run=False → stamp が書かれる (silent 死検知が機能)."""
    src = _fake_source_json(tmp_path)
    M, ws, stamp = _patch_merge_runner(monkeypatch, tmp_path, tmp_path)

    rc = M.main(["--source", str(src)])
    assert rc == 0
    assert stamp.exists(), "本番実行で stamp が書かれなかった = silent 死検知不能"
    data = json.loads(stamp.read_text(encoding="utf-8"))
    assert "ok_at" in data
    assert data["dry_run"] is False
    assert data["yodobashi_models"] == 1
    assert data["matched_models"] == 1


def test_gshock_merge_startup_warns_on_missing_stamp(
        monkeypatch, tmp_path, capsys):
    """起動時に前回スタンプ不在なら stderr に warn (silent 起動検知)."""
    src = _fake_source_json(tmp_path)
    M, ws, stamp = _patch_merge_runner(monkeypatch, tmp_path, tmp_path)
    assert not stamp.exists()

    M.main(["--dry-run", "--source", str(src)])
    err = capsys.readouterr().err
    assert "warning" in err
    assert "gshock_merge" in err


def test_yodobashi_snapshot_startup_warns_on_stale_generated_at(
        monkeypatch, tmp_path, capsys):
    """snapshot main() 冒頭で 前回 generated_at が >10h → warn (片側落ち検知).

    依頼書 §3「片側が落ちたら気づけない状態にしない」の回帰固定。
    """
    import build_yodobashi_snapshot as B
    from datetime import datetime, timedelta, timezone

    stamp = tmp_path / "yodobashi_stock_snapshot.json"
    # 20h 前 = 10h 閾値を超える stale
    prev = datetime.now(timezone(timedelta(hours=9))) - timedelta(hours=20)
    stamp.write_text(json.dumps({
        "generated_at": prev.isoformat(),
        "GA-2100-1AJF": {"in_stock": True, "price_jpy": 12000, "url": "x"},
    }), encoding="utf-8")
    monkeypatch.setattr(B, "SNAPSHOT_PATH", stamp)
    # collect_target_models を空にして早期 return させる (ネットワーク回避)
    monkeypatch.setattr(B, "collect_target_models", lambda: [])

    rc = B.main([])
    assert rc == 0
    err = capsys.readouterr().err
    assert "warning" in err
    assert "yodobashi_snapshot" in err
    assert ">10" in err
