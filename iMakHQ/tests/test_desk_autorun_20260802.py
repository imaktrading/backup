"""窓口の自走 (desk_autorun) の安全弁テスト — 2026-08-02。

なぜ要るか:
    担当 worktree は dispatch_watch で自動化済みだが、**窓口の仕事は人が窓を開けるまで動かない**。
    8/2 時点でレビュー待ち3件・残件4件が滞留し、窓口が律速になっていた。
    ユーザー承認 (「B を1窓口だけ」) を受けて ALPHA だけ自走させる。

    自走は暴走したときの被害が大きいので、**縛りが外れていないこと**を機械で守る:
      - 1回の起動で **1件だけ**
      - 担当が別の窓口の件は取らない
      - 出品専任が同じ worktree を編集中なら起動しない
      - 二重起動しない
      - 走り終わったら claim を必ず解放する (握ったまま落ちると誰も触れなくなる)
      - push/checkout/switch/reset は CLI 側で拒否
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import claim as C  # noqa: E402
import desk_autorun as A  # noqa: E402
import dispatch_worktree as dw  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _setup(tmp_path, monkeypatch, busy=False):
    # ★テストが**本物の headless claude を起動しない**ための二重の封じ (2026-08-02 実際にやらかした)。
    #   ① worktree_board の DATA_ROOT も差し替える。ここを忘れると実 requests を拾い、
    #      「取れる残務がある」状態になって run() が本気で agent を起動する
    #   ② claude.exe を「見つからない」状態にしておく。起動が要るテストだけ個別に patch する
    import worktree_board as wb
    monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(dw, "_resolve_claude_exe", lambda: "")
    monkeypatch.setattr(C, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(C, "BACKLOG", tmp_path / "_backlog")
    monkeypatch.setattr(C, "BACKLOG_DONE", tmp_path / "_backlog" / "_done")
    monkeypatch.setattr(C, "CLAIMS", tmp_path / "_claims")
    monkeypatch.setattr(C, "CLAIM_LOG", tmp_path / "_claims" / "_log.jsonl")
    monkeypatch.setattr(dw, "REVIEW_DIR", tmp_path / "review")
    monkeypatch.setattr(dw, "hq_busy", lambda: busy)
    monkeypatch.setattr(A, "DESK_DIR", {"ALPHA": tmp_path})
    (tmp_path / "_backlog").mkdir(parents=True, exist_ok=True)
    (tmp_path / "review").mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ 起動しない条件
def test_does_not_start_while_the_listing_session_is_editing(tmp_path, monkeypatch):
    """出品専任が同じ worktree を編集中は起動しない (index 衝突 = 出品が止まる)."""
    _setup(tmp_path, monkeypatch, busy=True)
    C.add_backlog("何か", priority=1, who="ALPHA")
    assert A.run("ALPHA")["status"] == "skip-busy"


def test_does_not_start_twice(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert A.acquire("ALPHA") is True
    assert A.run("ALPHA")["status"] == "skip-locked"
    A.release("ALPHA")


def test_does_nothing_when_there_is_no_work(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert A.run("ALPHA")["status"] == "skip-empty"


def test_never_takes_another_desks_assignment(tmp_path, monkeypatch):
    """★出品専任宛の依頼を ALPHA が勝手に着手しない."""
    _setup(tmp_path, monkeypatch)
    C.add_backlog("出品くんの仕事", priority=1, who="Advisor", owner="出品専任")
    r = A.run("ALPHA", dry_run=True)
    assert r["status"] == "skip-empty"
    assert any("担当: 出品専任" in why for _id, why in r["skipped"])


# ------------------------------------------------------------------ 1件だけ
def test_takes_exactly_one_item(tmp_path, monkeypatch):
    """1回の起動で1件。暴走時の被害と usage を人が読める大きさに保つ."""
    _setup(tmp_path, monkeypatch)
    for i in range(3):
        C.add_backlog(f"仕事{i}", priority=i + 1, who="ALPHA")
    r = A.run("ALPHA", dry_run=True)
    assert r["status"] == "dry-run"
    assert "仕事0" in r["title"], "優先度順に1件だけ取る"
    # dry-run は claim を残さない (次の起動が同じ件を取れる)
    assert C.read_claim(r["id"]) is None


# ------------------------------------------------------------------ 後始末
def test_claim_is_released_even_if_the_agent_forgot(tmp_path, monkeypatch):
    """★握ったまま落ちると、その件は stale になるまで誰も触れない."""
    _setup(tmp_path, monkeypatch)
    p = C.add_backlog("仕事", priority=1, who="ALPHA")
    monkeypatch.setattr(A.dw, "_resolve_claude_exe", lambda: __file__)

    class _Res:
        returncode = 0
        stdout = "SUMMARY: release / 触れなかった"
        stderr = ""
    monkeypatch.setattr(A.subprocess, "run", lambda *a, **k: _Res())
    r = A.run("ALPHA")
    assert r["status"] == "ok"
    assert r["unfinished"] is True, "done を打っていないので未完扱いにする"
    assert C.read_claim(f"backlog:{p.stem}") is None, "claim を残してはいけない"


def test_finished_item_is_not_reclaimed(tmp_path, monkeypatch):
    """担当が done を打っていれば未完扱いにしない."""
    _setup(tmp_path, monkeypatch)
    p = C.add_backlog("仕事", priority=1, who="ALPHA")
    monkeypatch.setattr(A.dw, "_resolve_claude_exe", lambda: __file__)

    class _Res:
        returncode = 0
        stdout = "SUMMARY: done / 片付けた"
        stderr = ""

    def _fake_run(*a, **k):
        C.done(f"backlog:{p.stem}", "ALPHA")      # 担当が done を打った状況
        return _Res()
    monkeypatch.setattr(A.subprocess, "run", _fake_run)
    assert A.run("ALPHA")["unfinished"] is False


# ------------------------------------------------------------------ 縛りが外れていないこと
def test_destructive_git_is_denied_at_the_cli():
    """prompt の言い回しは抑止力にならない (2026-07-29 実証済) ので CLI 側で落とす."""
    for t in ("push", "checkout", "switch", "reset"):
        assert any(t in d for d in A.DENY_TOOLS), f"git {t} が拒否されていない"


def test_prompt_carries_the_hard_rules():
    """自走なので**指示は prompt にしか無い**。抜けると人の確認なしで踏む."""
    item = {"id": "backlog:x", "kind": "残件", "title": "t", "path": "", "body": "b"}
    p = A.build_prompt("ALPHA", item)
    for must in ("1丁目1番地", "禁止", "eBay への書込", "git add -A", "daily_report",
                 "claim.py done", "claim.py release", "psa_to_csv", "SUMMARY:"):
        assert must in p, f"prompt に『{must}』が無い"
    assert "「①②とも正しい → 直すものは無い」は禁止" in p, \
        "2026-08-02 の規約改訂が自走 prompt に反映されていない"


def test_only_alpha_is_enabled_for_now():
    """ユーザー承認は『まず1窓口 (ALPHA)』。勝手に窓口を増やさない."""
    src = io.open(os.path.join(ROOT, "iMakHQ", "tools", "desk_autorun.py"),
                  encoding="utf-8").read()
    assert 'default=os.environ.get("IMAK_DESK", "ALPHA")' in src
