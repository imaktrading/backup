"""残務の取り合い防止 (claim) の回帰テスト — 2026-08-01。

なぜ要るか (実害の手前で止めた話):
    窓口が 2 → 4 に増えたが、4窓口は同じ worktree / 同じ daily_report を共有していて
    見える範囲が完全に同じ。ユーザーが4窓口に「残務着手して」と同じ指示を出すと
    **全員が同じ1件目に着手する**。commit dd8061f の「着手前に名乗る」は口約束で、
    board も status_now も『着手』を読む処理を持っていなかった (実測)。

    「一回決めたら狂いようがない。それが program」(ユーザー 2026-08-01) に従い、
    **claim を取れた窓口だけが着手できる**形にした。ここが緩むと二重着手が再発する。
"""
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import claim as C  # noqa: E402
import worktree_board as wb  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SESSIONS = ["iMakAdvisor", "iMakHQ", "iMakAlpha", "iMakBravo"]


def _setup(tmp_path, monkeypatch, n_backlog=3, requests=()):
    """claim/backlog の置き場をテスト用に差し替える."""
    monkeypatch.setattr(C, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(C, "BACKLOG", tmp_path / "_backlog")
    monkeypatch.setattr(C, "BACKLOG_DONE", tmp_path / "_backlog" / "_done")
    monkeypatch.setattr(C, "CLAIMS", tmp_path / "_claims")
    monkeypatch.setattr(C, "CLAIM_LOG", tmp_path / "_claims" / "_log.jsonl")
    monkeypatch.setattr(wb, "DATA_ROOT", tmp_path)
    (tmp_path / "_backlog").mkdir(parents=True, exist_ok=True)
    for i in range(n_backlog):
        (tmp_path / "_backlog" / f"item{i}.md").write_text(
            f"# 残件{i}\n\n- 優先度: {i + 1}\n", encoding="utf-8")
    for wt, name in requests:
        d = tmp_path / wt / "requests"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text("# 依頼\n", encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------ 排他
def test_second_window_cannot_take_the_same_item(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert C.take("backlog:item0", "ALPHA")["ok"] is True
    r = C.take("backlog:item0", "BRAVO")
    assert r["ok"] is False and "ALPHA" in r["reason"]


def test_four_windows_claiming_at_once_get_four_different_items(tmp_path, monkeypatch):
    """★本丸。4窓口が**同時**に next を呼んでも同じ件を渡さないこと.

    「存在チェックしてから書く」実装だと、ここで同じ件が複数窓口に渡る。
    O_CREAT|O_EXCL で作れた側だけが勝つ設計であることの証明。
    """
    _setup(tmp_path, monkeypatch, n_backlog=4)
    whos = ["Advisor", "出品専任", "ALPHA", "BRAVO"]
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(C.next_item, whos))
    got = [r["item"]["id"] for r in results if r["ok"]]
    assert len(got) == 4, f"4窓口が取れていない: {got}"
    assert len(set(got)) == 4, f"同じ件が複数窓口に渡った: {got}"


def test_next_returns_nothing_when_all_are_taken(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, n_backlog=1)
    assert C.next_item("ALPHA")["ok"] is True
    r = C.next_item("BRAVO")
    assert r["ok"] is False and r["item"] is None


# ------------------------------------------------------------------ 順番
def test_requests_come_before_backlog(tmp_path, monkeypatch):
    """要返球は他 worktree を止めている。**先に片付ける**のがグローバル規約."""
    _setup(tmp_path, monkeypatch, requests=[("catalog", "2026-08-01_x.md")])
    first = C.next_item("ALPHA")["item"]
    assert first["kind"] == "要返球", f"要返球が先頭でない: {first}"


def test_backlog_is_ordered_by_priority(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, n_backlog=3)
    ids = [it["id"] for it in C.all_items()]
    assert ids == ["backlog:item0", "backlog:item1", "backlog:item2"], ids


# ------------------------------------------------------------------ 待ち
def test_blocked_items_are_never_handed_out(tmp_path, monkeypatch):
    """外部待ちの件を掴ませない (掴んだ窓口が何もできずロックだけ残る)."""
    _setup(tmp_path, monkeypatch, n_backlog=0)
    C.add_backlog("請求書待ち", priority=1, who="Advisor", blocked="待ち (請求書が出るまで)")
    assert C.all_items()[0]["blocked"]
    r = C.next_item("ALPHA")
    assert r["ok"] is False, "待ちの件を渡してはいけない"


# ------------------------------------------------------------------ 所有権
def test_cannot_release_someone_elses_claim(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    C.take("backlog:item0", "ALPHA")
    assert C.release("backlog:item0", "BRAVO")["ok"] is False
    assert C.release("backlog:item0", "ALPHA")["ok"] is True


def test_stale_claim_can_be_taken_over_and_is_logged(tmp_path, monkeypatch):
    """窓口は落ちる/寝る。永久ロックにすると誰も触れない件が生まれる.

    ただし **黙って奪わない** (誰から奪ったかが log に残ること)。
    """
    _setup(tmp_path, monkeypatch)
    C.take("backlog:item0", "ALPHA")
    p = C.claim_path("backlog:item0")
    old = os.stat(p).st_mtime - (C.STALE_HOURS + 1) * 3600
    os.utime(p, (old, old))
    assert C.read_claim("backlog:item0")["stale"] is True
    r = C.take("backlog:item0", "BRAVO")
    assert r["ok"] is True and "ALPHA" in r["reason"]
    events = [json.loads(ln) for ln in
              io.open(C.CLAIM_LOG, encoding="utf-8").read().splitlines() if ln.strip()]
    assert any(e["event"] == "steal" and e["who"] == "BRAVO" for e in events)


# ------------------------------------------------------------------ 完了
def test_done_moves_backlog_and_frees_the_claim(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    C.take("backlog:item0", "ALPHA")
    r = C.done("backlog:item0", "ALPHA", note="やった")
    assert r["ok"] is True
    assert not (tmp_path / "_backlog" / "item0.md").exists()
    body = (tmp_path / "_backlog" / "_done" / "item0.md").read_text(encoding="utf-8")
    assert "完了" in body and "やった" in body
    assert C.read_claim("backlog:item0") is None


def test_done_never_renames_a_request_file(tmp_path, monkeypatch):
    """requests の決着は `_response.md` を書く既存フローが唯一の正.

    ここでリネームすると決着判定が二重定義になり、board と食い違う。
    """
    _setup(tmp_path, monkeypatch, requests=[("catalog", "2026-08-01_x.md")])
    src = tmp_path / "catalog" / "requests" / "2026-08-01_x.md"
    C.take("catalog:2026-08-01_x", "ALPHA")
    r = C.done("catalog:2026-08-01_x", "ALPHA")
    assert r["ok"] is True and src.exists(), "依頼書ファイルを勝手に動かしてはいけない"
    assert r["moved"] is None and r["hint"]


# ------------------------------------------------------------------ 置き場
def test_claim_state_lives_outside_git(tmp_path, monkeypatch):
    """claim/残件は実行時の状態。git 管理下に置くと他セッションの commit に紛れ込む.

    (2026-08-01 `4df3f8a` に4ファイルが乗った事故 / `45d9f23` の lock 除外と同じ理由)
    """
    src = io.open(os.path.join(ROOT, "iMakHQ", "tools", "claim.py"), encoding="utf-8").read()
    assert r"C:\dev\iMak_data" in src, "共有データ領域 (git 外) を使っていない"
    assert "C:/dev/iMak/" not in src.replace("iMakHQ/tools/claim.py", ""), \
        "git worktree 配下に状態を書こうとしている"


# ------------------------------------------------------------------ 周知
def test_every_window_is_told_to_claim_before_starting():
    """★ここが本質。道具があっても窓口が使わなければ dd8061f の口約束と同じ.

    4つの CLAUDE.md **全部**に指示が要る。1つ欠けるとその窓口だけ無断着手する。
    """
    for s in SESSIONS:
        p = os.path.join(ROOT, s, "CLAUDE.md")
        t = io.open(p, encoding="utf-8").read()
        assert "claim.py" in t, f"{s}: claim の指示が無い"
        assert "claim.py next" in t, f"{s}: 着手コマンドが書かれていない"


# ------------------------------------------------------------------ 担当指定
def test_next_never_hands_out_someone_elses_assignment(tmp_path, monkeypatch):
    """★2026-08-02 の実害。宛先が書いてあるのに claim が読んでいなかった.

    8/1 に Advisor が「出品くんにやらせて」と指示されて**出品専任宛**に書いた依頼書を、
    翌朝の `next` が **Advisor 本人に**渡した。頼んだ本人が翌朝それを掴む = 振り分けが無意味。
    """
    _setup(tmp_path, monkeypatch, n_backlog=0)
    C.add_backlog("出品くんの仕事", priority=1, who="Advisor", owner="出品専任")
    C.add_backlog("誰でもいい仕事", priority=2, who="Advisor")
    r = C.next_item("Advisor")
    assert r["ok"] is True
    assert "誰でもいい" in r["item"]["title"], "担当が別の件を渡してはいけない"
    assert any("担当: 出品専任" in why for _it, why in r["skipped"])
    # 本人には渡る
    assert "出品くん" in C.next_item("出品専任")["item"]["title"]


def test_owner_is_read_from_a_request_file_body(tmp_path, monkeypatch):
    """依頼書 (requests/*.md) の `- 担当:` も読むこと (残件ファイルだけでは足りない)."""
    _setup(tmp_path, monkeypatch, n_backlog=0)
    d = tmp_path / "hq" / "requests"
    d.mkdir(parents=True)
    (d / "2026-08-01_x.md").write_text(
        "# 依頼\n\n- 依頼日: 2026-08-01\n- 担当: 出品専任\n", encoding="utf-8")
    it = C.all_items()[0]
    assert it["owner"] == "出品専任"
    assert C.next_item("ALPHA")["ok"] is False, "担当外の窓口に渡してはいけない"


def test_owner_aliases_are_normalized(tmp_path, monkeypatch):
    """表記ゆれ (出品くん / HQ / adv) で振り分けが外れないこと."""
    for raw, want in (("出品くん", "出品専任"), ("HQ", "出品専任"),
                      ("adv", "Advisor"), ("alpha", "ALPHA")):
        assert C._owner_of(f"- 担当: {raw}\n") == want, raw


def test_explicit_take_can_override_the_assignment(tmp_path, monkeypatch):
    """急ぐことはあるので **明示 take は通す** (自動で渡さないだけ)."""
    _setup(tmp_path, monkeypatch, n_backlog=0)
    p = C.add_backlog("出品くんの仕事", priority=1, who="Advisor", owner="出品専任")
    assert C.take(f"backlog:{p.stem}", "ALPHA")["ok"] is True


def test_board_shows_who_holds_what(tmp_path, monkeypatch):
    """現在地に『誰が何を持っているか』が出ること (出ないと窓口が確認しようがない)."""
    src = io.open(os.path.join(ROOT, "iMakHQ", "tools", "worktree_board.py"),
                  encoding="utf-8").read()
    assert "着手中" in src and "import claim" in src
    _setup(tmp_path, monkeypatch)
    C.take("backlog:item0", "ALPHA")
    out = C.render_list()
    assert "着手中" in out and "ALPHA" in out


def test_status_now_shows_the_backlog_board():
    """『現在地』の唯一の答えに残務ボードが含まれること."""
    src = io.open(os.path.join(ROOT, "iMakHQ", "tools", "status_now.py"),
                  encoding="utf-8").read()
    assert "claim.py" in src and "残務ボード" in src
