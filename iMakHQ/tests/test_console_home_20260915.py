# -*- coding: utf-8 -*-
"""出品くん Console (Web 画面) 段階1: ホーム画面 (2026-09-15)。

ユーザー「もっと有料システムみたいな感じで」→ 見本に「こういうのを求めている」→「うん」。
今の出品くん (control_panel.py) は書き換えず、同じ定義・同じ集計を使う。ずれたらここが赤になる。
"""
import os
import re
import sys

HQ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HQ, "console"))

import server as S  # noqa: E402

PANEL = open(os.path.join(HQ, "control_panel.py"), encoding="utf-8").read()
COUNTS = open(os.path.join(HQ, "console", "counts.py"), encoding="utf-8").read()
SERVER = open(os.path.join(HQ, "console", "server.py"), encoding="utf-8").read()


def test_counts_cover_the_same_keys_as_the_panel():
    panel_keys = set(re.findall(r"d\['(\w+)'\]=", PANEL)) | {"hoju"}
    console_keys = set(re.findall(r'^\s+"(\w+)": lambda', COUNTS, re.M))
    assert panel_keys == console_keys, (panel_keys ^ console_keys)


def test_runnable_is_everything_but_the_wizard():
    """2026-09-16 (v0.3.0): 走る前のガードと後処理を共用にしたので、後処理あり・新規生成も押せる。

    残る旧パネル専用は **ウィザード画面が要る物だけ** (一番くじの新規)。
    """
    assert S.runnable({"skip_postprocess": True, "type": "utility"})
    assert S.runnable({"type": "utility"})                                       # 後処理あり → after_run が回す
    assert S.runnable({"type": "new"})                                           # 新規生成 → before_run のガードを通す
    assert S.runnable({"ask_amount": True})                                      # 金額は画面で聞く
    assert S.runnable({"params": [{"name": "--limit"}]})                         # 入力欄も画面で聞く
    assert not S.runnable({"custom_buttons": "ichibankuji"})


def test_console_uses_the_panels_own_before_and_after():
    """二重実装の禁止: Console は control_panel の before_run / after_run を呼ぶだけ。"""
    assert "cp.before_run(script, _to_log)" in SERVER
    assert "cp.after_run(script, rc, _to_log" in SERVER
    panel = PANEL
    assert "def before_run(script, append_log)" in panel
    assert "def after_run(script, returncode, append_log" in panel


def test_inputs_are_passed_the_same_way_as_the_panel():
    """入力欄は --name 値、金額は --amount (旧パネルの run_script と同じ組み立て)。"""
    assert S.build_cmd({"cmd": ["python", "x.py"], "params": [{"name": "--limit"}]},
                       {"--limit": "5"}) == ["python", "x.py", "--limit", "5"]
    assert S.build_cmd({"cmd": ["python", "x.py"], "ask_amount": True},
                       None, "1,200") == ["python", "x.py", "--amount", "1200"]
    assert S.build_cmd({"cmd": ["python", "x.py"], "ask_amount": True}, None, "") == ["python", "x.py"]
    try:
        S.build_cmd({"cmd": ["python", "x.py"], "ask_amount": True}, None, "たくさん")
        raise AssertionError("金額として読めない値は弾く")
    except ValueError:
        pass


def test_summarize_states():
    d = {"hoju": {"search": {"can": 47, "today_can": 0}, "confirm": {"ready": 5, "unjudged": 15},
                  "swap": {"ready": 0, "unjudged": 0}},
         "restock_build": {"actionable": 0, "blocked": 14},
         "ut": {"error": "APIError: 429"}}
    s = S.summarize(d, nightly_ok=True)
    assert s["hoju_search"]["state"] == "night"            # 夜間が動いている日は夜に任せる
    assert s["hoju_confirm"] == {"n": 20, "state": "todo", "note": s["hoju_confirm"]["note"], "hold": 0}
    assert s["hoju_swap"]["state"] == "done"
    assert s["restock_build"]["state"] == "hold" and s["restock_build"]["hold"] == 14
    assert s["ut_confirm"]["state"] == "error"
    assert S.summarize(d, nightly_ok=False)["hoju_search"]["state"] == "todo"   # 夜が転んだ日は青に戻す


def test_night_kinds_match_panel():
    for k in S.NIGHT_KINDS:
        assert re.search(r'"%s": bool\([^\n]*\) and not _auto' % k, PANEL), k


def test_display_label_and_groups():
    assert S.display_label("🩹 PSA 補URL ③ 補充") == "PSA 補URL ③ 補充"
    assert S.group_of("PSA 補URL ③ 補充") == "hoju"
    assert S.group_of("売れた分を補充") == "restock"
    assert S.group_of("棚② 売れない在庫を落とす") == "shelf"


def test_crew_parse():
    txt = "## カタログ — 自分が返す 2件 / 窓口宛 0件\n## 監視くん — 動きなし (最終 5日前)\n## 🔀 ルーティング待ち — 3件\n"
    c = S.parse_crew(txt)
    assert c["route"] == 3 and c["rows"][0]["flag"] == "act" and c["rows"][1]["flag"] == ""


def test_unread_shelf_is_not_shown_as_zero():
    """統合シートが 429 で空 → 公式在庫の件数だけ残る形を「読めなかった」と判定する (9/15 実測)。"""
    broken = [{"cat": "Tシャツ", "usd": 0.0, "count": 133}, {"cat": "TCG", "usd": 0.0, "count": 0}]
    ok = [{"cat": "Tシャツ", "usd": 64069.0, "count": 133}]
    assert S.shelf_looks_unread(broken)
    assert not S.shelf_looks_unread(ok)
    assert not S.shelf_looks_unread([])
    assert '_CACHED_SHEET_COUNTS["data"] = None' in SERVER      # パネルの1分キャッシュに空の結果を残さない


def test_counts_retry_quota_errors_once():
    """9/15 実測: UT / 売れた分の補充 / くじ再仕入れ が 429 で「数えられない」になった。待って数え直す。"""
    sys.path.insert(0, os.path.join(HQ, "console"))
    import counts as C
    assert C.hits_quota({"error": "APIError: [429]: Quota exceeded"})
    assert C.hits_quota({"search": {"can": 29}, "supply": {"can": None, "error": "APIError: [429]"}})
    assert not C.hits_quota({"error": ""})
    assert not C.hits_quota({"error": "KeyError: x"})
    assert "time.sleep(65)" in COUNTS


def test_launcher_vbs_is_ascii_only():
    """9/15 実害: 1行目の日本語コメントを VBScript が ANSI で読み、次の行を飲み込んで起動しなかった。"""
    raw = open(os.path.join(HQ, "console", "start_console.vbs"), "rb").read()
    assert all(b < 0x80 for b in raw)


def test_server_is_local_only_and_posts_need_the_header():
    assert 'HOST = "127.0.0.1"' in SERVER
    assert 'self.headers.get("X-Console") != "1"' in SERVER


def test_panel_itself_is_untouched_by_the_console():
    """Console は control_panel を import するだけ。control_panel 側から console を参照しない。"""
    assert "console" not in re.findall(r"^import (\w+)|^from (\w+)", PANEL)


def test_every_button_has_a_place_on_the_screen():
    """9/16 段階2: 商材 × 段階の格子・一覧に **全ての badge** を置く。

    見本 https://claude.ai/artifact/17znRRHtq61RzUeroRxU41 の形に組み直した時、
    どこにも出していないボタンが黙って消えないようにする (出していない物は画面の
    「ここに置き場が無いボタン」に出るが、既知のものはここで気付けるようにする)。
    """
    app = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
    placed = set(re.findall(r'"(\w+)"', app))
    sys.path.insert(0, HQ)
    import control_panel as cp
    for s_ in cp.SCRIPTS:
        b = s_.get("badge")
        if b and b != "hoju_status":                     # 件数感は見るだけのボタン
            assert b in placed, b


def test_screen_has_no_crew_or_permanent_log_panel():
    """ユーザー「担当・実行ログの欄は要らない」(2026-09-15)。ログは実行中・直後だけ下から出す。"""
    html = open(os.path.join(HQ, "console", "static", "index.html"), encoding="utf-8").read()
    assert "担当" not in html
    assert 'id="drawer" hidden' in html                  # 既定は出さない


def test_version_and_migration_status():
    """ユーザー「ver管理も」(2026-09-16)。版は 0.x = 旧パネル併用、1.0 = 全ボタンが新画面で押せる。"""
    sys.path.insert(0, os.path.join(HQ, "console"))
    import version as V
    sys.path.insert(0, HQ)
    import control_panel as cp
    assert re.match(r"^\d+\.\d+\.\d+$", V.VERSION)
    ready = [s_ for s_ in cp.SCRIPTS if S.runnable(s_)]
    blocked = [s_ for s_ in cp.SCRIPTS if not S.runnable(s_)]
    assert all(not V.why_not_runnable(s_) for s_ in ready)       # 押せる物に「理由」は出さない
    assert all(V.why_not_runnable(s_) for s_ in blocked)         # 押せない物は必ず理由が出る
    # 1.0 を名乗れるのは全部押せる時だけ
    assert V.VERSION.startswith("0.") or not blocked
    log = open(os.path.join(HQ, "console", "CHANGELOG.md"), encoding="utf-8").read()
    assert V.VERSION in log                                      # 版を上げたら CHANGELOG に1行足す


def test_after_run_closes_the_run_even_without_a_csv():
    """共通化した後処理を実際に呼ぶ (2026-09-16)。skip_postprocess のボタンは CSV を触らず締める。"""
    sys.path.insert(0, HQ)
    import control_panel as cp
    out = []
    r = cp.after_run({"label": "テスト", "skip_postprocess": True, "type": "utility", "cmd": []},
                     0, out.append)
    text = "".join(str(x) for x in out)
    assert "後処理をスキップ" in text
    assert "🎉 全 process 完了" in text
    assert r["latest_csv"] is None


def test_after_run_says_failed_when_the_script_failed():
    sys.path.insert(0, HQ)
    import control_panel as cp
    out = []
    cp.after_run({"label": "テスト", "skip_postprocess": True, "type": "utility", "cmd": []}, 1, out.append)
    text = "".join(str(x) for x in out)
    assert "❌ 失敗しました (returncode=1)" in text
    assert "🎉" not in text


def test_post_run_log_goes_to_the_screen_only():
    """後処理のログを run log に書き足さない (2026-09-16 実測で気づいた差)。

    後処理は run log を「今回の stdout」として読み直す。そこに後処理自身の文
    (問題提起の引用など) が入ると NO-GO 行を二重に拾う。旧パネルは画面にしか出していない。
    """
    body = SERVER.split("def _to_log(text):")[1].split("def _run_log_text")[0]
    assert "fh.write" not in body


def test_stop_button_uses_the_panels_kill():
    """止めるボタン (2026-09-16 ユーザー「確かに停止ボタンがないね」)。

    止め方は旧パネルと同じ (_kill_process_tree = 子プロセスごと)。走っていない時は 409。
    """
    assert "_kill_process_tree(p, _log)" in SERVER
    assert '"/api/stop"' in SERVER
    html = open(os.path.join(HQ, "console", "static", "index.html"), encoding="utf-8").read()
    assert 'id="drawer-stop"' in html
    app = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
    assert '$("drawer-stop").hidden = !running.running;' in app   # 走っている時だけ出す


def test_sold_restock_button_actually_sends():
    """「売れた分を補充」は押したら実際に戻す (2026-09-16 ユーザー「押したんだけど・・・」)。

    それまでは --write が無く **下見だけ**で、見ている注文も古い OrdersReport の CSV だった。
    夜間バッチと同じ呼び方 (--orders-api --write --max=10) に揃える。
    """
    sys.path.insert(0, HQ)
    import control_panel as cp
    e = next(s for s in cp.SCRIPTS if s.get("badge") == "sold_restock")
    assert e["cmd"] == ["python", "sold_restock.py", "--orders-api", "--write", "--max=10"]
    bat = open(os.path.join(HQ, "tools", "run_hoju_search.bat"), encoding="utf-8", errors="replace").read()
    assert "--orders-api --write --max=10" in bat          # 夜間と同じ形


def test_log_has_a_copy_button():
    """ログをコピー (2026-09-16 ユーザー要望。貼って相談する時に使う)。"""
    html = open(os.path.join(HQ, "console", "static", "index.html"), encoding="utf-8").read()
    assert 'id="drawer-copy"' in html
    app = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
    assert "navigator.clipboard" in app and "execCommand" in app   # 控えの手も用意する


def test_screen_retries_when_the_server_is_restarting():
    """最初の読み込みが失敗しても、そのまま止まらない (2026-09-16 実害)。

    ユーザー「出品君が件数読み込み中で、固まってる気がする」。
    サーバ側は正常 (件数は取れていた) で、画面の最初の読み込みが1回きりだったため、
    サーバ入れ替え中に失敗したページがそのまま「読み込み中」で固まっていた。
    """
    app = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
    assert "function bootstrap()" in app
    assert "setTimeout(bootstrap, 3000)" in app                       # 失敗したらやり直す
    assert "if (!buttons.length || !jobList.length) { bootstrap(); return; }" in app


def test_app_js_has_no_raw_newline_inside_a_string():
    """画面の JS が構文エラーで丸ごと止まらないようにする (2026-09-16 実害)。

    「ログをコピー」を足した時に、文字列の中に **生の改行** が入って SyntaxError になり、
    画面が「件数 読込中」のまま固まった。行の途中で引用符が閉じていない行を弾く。
    """
    path = os.path.join(HQ, "console", "static", "app.js")
    for i, line in enumerate(open(path, encoding="utf-8").read().split("\n"), 1):
        code = re.sub(r"\.", "", line)                    # \" などのエスケープは外す
        code = re.sub(r"//.*$", "", code)
        assert code.count('"') % 2 == 0, "%s:%d 二重引用符が閉じていない" % (path, i)
        assert code.count("'") % 2 == 0, "%s:%d 引用符が閉じていない" % (path, i)


def test_log_can_be_opened_anytime():
    """ログはいつでも開ける (2026-09-16 ユーザー「ログ画面消えてない？」)。

    実行中と直後しか出していなかったので、終わった後に見返せなかった。
    """
    html = open(os.path.join(HQ, "console", "static", "index.html"), encoding="utf-8").read()
    assert 'id="btn-log"' in html
    app = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
    i = app.index('$("btn-log").addEventListener')
    body = app[i:i + 700]
    assert '$("drawer").hidden = false' in body
    assert "直近のログ" in body                      # 走っていない時の見出し
