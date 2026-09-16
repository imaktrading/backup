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


def test_console_watches_for_counts_that_do_not_move():
    """押しても件数が減らないボタンを、新画面でも毎回見張る (2026-09-16)。

    ユーザー「こういうの、頻発している。他のボタンも含めてちゃんとやってよ。
    これを見て作業しているんだから！」
    旧パネルにしか見張り (_check_badge_moved) が無く、新画面で作業している間は
    ずれても記録すら残らなかった (badge_drift.jsonl は6件しか無かった)。
    """
    assert "before = count_of(script.get(\"badge\"))" in SERVER
    assert "cp.badge_did_not_move(before, after)" in SERVER
    assert "cp._record_badge_drift(badge, label, before, after)" in SERVER
    assert "if rc in (0, None) and not stopped:" in SERVER      # 失敗・停止は突き合わせない


def test_sold_restock_count_uses_the_same_orders_as_the_button():
    """件数と実行が別の物を見ていた (2026-09-16 ユーザー「件数が変わってないけど」)。

    ボタンは注文API、件数はデスクの古い CSV を見ていたので、補充しても件数が動かなかった。
    """
    src = open(os.path.join(HQ, "tools", "sold_restock.py"), encoding="utf-8").read()
    body = src.split("def count_workload()")[1].split("\ndef ")[0]
    assert "orders_from_api()" in body                          # まず注文API
    assert body.index("orders_from_api()") < body.index("_find_desk_report()")   # CSV は控え


def test_running_job_is_not_killed_when_the_server_restarts():
    """サーバを入れ替えても、走っている作業を道連れにしない (2026-09-16 実害)。

    18:11 にサーバを再起動して、走っていた 🤖自動 (PSA) を落とした
    (ログは「📷2 ✓」で切れ、生成に進まなかった)。
    子は別のプロセスグループで起こす + 入れ替え用スクリプトは走行中に止める。
    """
    assert "CREATE_NEW_PROCESS_GROUP" in SERVER
    assert "CREATE_BREAKAWAY_FROM_JOB" in SERVER
    ps1 = open(os.path.join(HQ, "console", "restart.ps1"), encoding="utf-8-sig").read()
    assert "running -and -not $Force" in ps1        # 走行中は入れ替えない


def test_console_port_does_not_collide_with_the_viewers():
    """Console のポートが 目視画面のポートとぶつからない (2026-09-16 実害)。

    8765 は PSA 目視 (post_psa_review.SERVER_PORT)、8766 は一番くじ。Console を 8765 に置いたため、
    PSA の 🤖自動 が目視画面を開いた時に **Console が出てしまい、目視ができなかった**
    (Windows は後から同じポートに割り込めるので、エラーも出ずに入れ替わる)。
    """
    import re as _re
    m = _re.search(r'PORT = int\(os\.environ\.get\("CONSOLE_PORT", "(\d+)"\)\)', SERVER)
    assert m, "Console のポートが読めない"
    port = int(m.group(1))
    used = set()
    for name in ("tools/post_psa_review.py", "tools/ichibankuji_restock.py"):
        src = open(os.path.join(HQ, name), encoding="utf-8").read()
        used |= {int(x) for x in _re.findall(r"(?:SERVER_PORT|port)\s*=\s*(\d{4})", src)}
    assert port not in used, "Console のポート %d が 目視画面と衝突している (%s)" % (port, sorted(used))


def test_console_can_stop_a_run_left_by_the_previous_server():
    """前のサーバが残した走行も止められる (2026-09-16 実害)。

    ユーザー「再走するから、止めるボタン押したけど、止まらんけど」。
    18:20 に走り出した PSA は前の Console の子で、入れ替えた後の Console は知らないため、
    「止める」を押しても何も起きなかった (画面にも走行中と出ていなかった)。
    起動時に 出品くんの道具のプロセスを探して拾い、pid で止められるようにする。
    """
    assert "def find_orphan_run():" in SERVER
    assert "def adopt_orphan_run():" in SERVER
    assert "threading.Thread(target=adopt_orphan_run, daemon=True).start()" in SERVER
    assert '"orphan_pid"' in SERVER
    assert '["taskkill", "/PID", str(pid), "/T", "/F"]' in SERVER
    assert "psa_to_csv.py" in SERVER                     # 主な道具は手掛かりに入れておく


def test_restock_count_is_only_what_the_button_can_do():
    """件数は「押して動かせる分」だけ (2026-09-16 見張りが捕まえた実害)。

    「売れた分を補充」が 要対応2件と出ていたが、押すと「対象 0」。中身は
    **売れて終了した UK ミラー2件** で、走行は「US 以外 → 触らない」と必ず飛ばす。
    判定できない分は件数から外し、note に出す。
    """
    s = S.summarize({"restock": {"actionable": 0, "unknown": 2, "done": 11, "blocked": 0}})
    assert s["sold_restock"]["n"] == 0 and s["sold_restock"]["state"] == "done"
    assert "判定できない 2件" in s["sold_restock"]["note"]
    s2 = S.summarize({"restock": {"actionable": 3, "unknown": 2, "done": 11, "blocked": 0}})
    assert s2["sold_restock"]["n"] == 3 and s2["sold_restock"]["state"] == "todo"
    assert 'bool(sr.get("actionable")) and not _auto' in PANEL      # 旧パネルも同じ数え方


def test_search_buttons_are_not_checked_for_not_moving():
    """「探す」系は押すと候補が増えるのが正常なので突き合わせない (2026-09-16)。

    実測: PSA 再仕入れ①探す が 3件 → 38件 になり、見張りが「減らなかった」と誤記録した。
    """
    assert "SEARCH_KINDS" in SERVER
    assert "badge not in SEARCH_KINDS and cp.badge_did_not_move" in SERVER
    for k in ("hoju_search", "ut_search", "psa_gate", "kuji_search"):
        assert k in SERVER.split("SEARCH_KINDS = {")[1].split("}")[0], k


def test_a_job_without_a_step_does_not_hide_the_others():
    """段の無い作業が「①」扱いになって ②③ を隠していた (2026-09-16)。

    ユーザー「棚②は今日やることに追加しないの？」で発覚。JS の indexOf("") は **0** を返すので、
    段が空の作業まで rank 1 になり、同じまとまりの 棚② (rank 2) が順番待ちに落ちていた。
    """
    app = open(os.path.join(HQ, "console", "static", "app.js"), encoding="utf-8").read()
    body = app.split("function rankOf(j) {")[1].split("function firstStepOnly")[0]
    assert 'var s = j.step || "";' in body
    assert "if (!s) return 9;" in body                      # 段が無ければ順番待ちにしない
    assert body.index("if (!s) return 9;") < body.index('indexOf(s)')   # indexOf より先に弾く
