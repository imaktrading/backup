"""全 runner が **途中で保存する** ことを守る (2026-09-13).

user「なんでまめな保存をしないの？学習機能ないの？」。
2026-08-20 に楽天ガチャへ入れた守りを他へ広げず、 新しく作った UT 収集で 140件が消えた。
1本直すだけでは次に作る runner でまた漏れるので、 **全 runner を走査して落とす**。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from incremental_writer import PendingWriter

pytestmark = pytest.mark.offline

ROOT = Path(__file__).resolve().parents[1]

# 途中保存の目印 (どれかがあれば良い)
INCREMENTAL_MARKERS = ("PendingWriter", "_flush(", "len(pending) >=")

# スプシへ書く runner の目印
WRITE_MARKERS = ("append_", "write_to_sheet(")

# ★例外: 収集ループが scraper 側の関数の中にあり、 runner からは1回で受け取る作り。
#   ここを変えるには scraper の挙動に手を入れる必要がある (mercari いいね収集は
#   「既存挙動保持必須」の凍結対象)。 件数も少ない (いいね/ほしい物リスト)。
#   **理由を書かずに足さないこと**。
ALLOWLIST = {
    "run_harvest_amazon.py": "ほしい物リスト収集。ループは scrapers 側、件数が少ない",
    "run_harvest_mercari_shops.py": "メルショいいね収集。ループは scrapers 側 (凍結対象)",
    # 以下3本は 2026-09-13 の洗い出しで見つかった分。 データは失わない形になっているか、
    # 触ると別の仕組みを壊すので、 理由付きで残す (未対応として日報に記録済)
    "run_harvest_restock_psa10.py": "カード1枚ごとに JSON を保存し --resume-from-json で再開できる (失わない)",
    "run_harvest_yodobashi.py": "cron の G-SHOCK 延命。完走スタンプと Amazon 差分が最後の書込に依存 (要設計)",
    "run_harvest_amazon_search.py": "詳細ループが _fetch_details の中。CAPTCHA に敏感で手動実行 (要設計)",
}


def _runners():
    for p in sorted(ROOT.glob("run_harvest_*.py")):
        yield p, p.read_text(encoding="utf-8")


def test_every_runner_that_writes_saves_incrementally():
    bad = []
    for path, src in _runners():
        if path.name in ALLOWLIST:
            continue
        if not any(m in src for m in WRITE_MARKERS):
            continue                      # スプシに書かない runner (JSON だけ等)
        if not any(m in src for m in INCREMENTAL_MARKERS):
            bad.append(path.name)
    assert not bad, ("最後にまとめて書くだけの runner がある (落ちたら全部消える): "
                     + ", ".join(bad))


def test_allowlist_entries_have_a_reason_and_still_exist():
    for name, reason in ALLOWLIST.items():
        assert reason.strip(), f"{name} に理由が無い"
        assert (ROOT / name).exists(), f"{name} は無くなった。ALLOWLIST から消すこと"


# --------------------------------------------------------------------------
# 部品の動き
# --------------------------------------------------------------------------
def test_writes_every_n_items(tmp_path):
    calls = []
    w = PendingWriter(write_fn=lambda rows: calls.append(len(rows)), every=5,
                      dump_path=tmp_path / "x.json", log=lambda m: None)
    for i in range(12):
        w.add({"i": i})
    assert calls == [5, 5]          # 5件ごとに書いている
    w.close()
    assert calls == [5, 5, 2]       # 最後の残りも書く
    assert w.written == 12


def test_failed_write_is_carried_over_not_dropped(tmp_path):
    state = {"fail": True, "rows": []}

    def write(rows):
        if state["fail"]:
            raise RuntimeError("network")
        state["rows"].extend(rows)

    w = PendingWriter(write_fn=write, every=2, dump_path=tmp_path / "x.json", log=lambda m: None)
    w.add(1); w.add(2)              # 書込失敗 → 持ち越し
    assert w.pending == [1, 2]
    state["fail"] = False
    w.add(3)                        # 次の機会にまとめて書く
    assert state["rows"] == [1, 2, 3] and w.pending == []


def test_unwritten_rows_are_saved_to_a_file_on_close(tmp_path):
    def write(rows):
        raise RuntimeError("down")

    w = PendingWriter(write_fn=write, every=10, dump_path=tmp_path / "run.json",
                      log=lambda m: None)
    w.add({"url": "u1"})
    left = w.close()
    assert left is not None and left.exists()
    assert json.loads(left.read_text(encoding="utf-8"))["unwritten"] == [{"url": "u1"}]


def test_json_is_written_after_every_item(tmp_path):
    p = tmp_path / "run.json"
    w = PendingWriter(write_fn=lambda rows: None, every=100, dump_path=p, log=lambda m: None)
    w.add({"url": "u1"})
    assert json.loads(p.read_text(encoding="utf-8"))["kept"] == [{"url": "u1"}]


def test_dry_run_does_not_write_but_keeps_json(tmp_path):
    calls = []
    p = tmp_path / "run.json"
    w = PendingWriter(write_fn=lambda rows: calls.append(rows), every=1, dump_path=p,
                      log=lambda m: None, enabled=False)
    w.add({"url": "u1"})
    w.close()
    assert calls == [] and p.exists()
