"""棚②のボタンの件数は「今日すでに落とした分」を引くこと (2026-09-18)。

実害: 3件 落とした直後もボタンは 3件 のままで「押しても件数が減りませんでした
(3件 → 3件)」が出た。押しても main() は『今日はもう落とす分がありません』で
何もしないので、数字だけが残っていた。
"""
import sys

sys.path.insert(0, r"C:/dev/iMak/iMakHQ/tools")
import shelf_evict as SE


def test_今日の分を落とし切ったら0件(monkeypatch):
    monkeypatch.setattr(SE, "listed_today_amount", lambda *a, **k: 2773.0)
    monkeypatch.setattr(SE, "evicted_today_amount", lambda *a, **k: 3468.0)
    monkeypatch.setattr(SE, "_load", lambda *a, **k: ([], lambda r: 0, lambda r: ""))
    got = SE.count_workload()
    assert got["target"] == 0
    assert got["picked"] == 0


def test_まだ落としていなければ目標が立つ(monkeypatch):
    monkeypatch.setattr(SE, "listed_today_amount", lambda *a, **k: 2773.0)
    monkeypatch.setattr(SE, "evicted_today_amount", lambda *a, **k: 0.0)
    monkeypatch.setattr(SE, "_load", lambda *a, **k: ([], lambda r: 0, lambda r: ""))
    assert SE.count_workload()["target"] > 0
