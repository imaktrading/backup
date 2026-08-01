# -*- coding: utf-8 -*-
"""窓口の自走を ON / OFF する (ダブルクリック用の中身)。

なぜ Python にやらせるか (2026-08-02 の失敗):
    最初は `.bat` に日本語の説明を直書きしていたが、cmd.exe は **CP932 + CRLF** でしか
    正しく読めない。UTF-8 で保存すると化けて行が壊れ、CRLF を LF にしても行が壊れる。
    実際にユーザーの画面で `'します' は、内部コマンドまたは外部コマンドとして認識されていません`
    が大量に出た。同型の事故は 7/30 にもあった (`run_hoju_search.bat` が一度も走っていなかった)。

    → **`.bat` は ASCII だけ**にして、日本語の表示・確認・分岐は Python が持つ。
      Python なら encoding を自分で決められるので、この事故は構造的に起きない。

使い方 (通常はダブルクリック経由):
    python desk_autorun_setup.py --on   [--minutes 5]
    python desk_autorun_setup.py --off
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TASK = "iMakHQ_DeskAutorun_ALPHA"
REGISTER_PS1 = os.path.join(HERE, "desk_autorun_register.ps1")
AUTORUN = os.path.join(HERE, "desk_autorun.py")
LOGDIR = os.path.join(os.path.dirname(HERE), "review_logs")


def _out(s: str = "") -> None:
    print(s, flush=True)


def _ps(args: list[str]) -> int:
    return subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"] + args)


def turn_on(minutes: int) -> int:
    _out()
    _out("=" * 62)
    _out("  窓口 ALPHA の自走を ON にします")
    _out("=" * 62)
    _out()
    _out(f"  {minutes}分ごとに、残務を「1件だけ」自動で片付けます。")
    _out("   ・残務が無い時は agent を立てずに終わるので、空振りのコストはゼロ")
    _out("   ・走行中は新しく起動しません (同時に走るのは常に1本)")
    _out("   ・他の窓口が持っている件、担当が別の件には手を出しません")
    _out("   ・eBay書込 / CSV入稿 / スプシ一括書換 / 出品くん本体 は禁止済み")
    _out()
    _out("-" * 62)
    _out("  まず「今なら何を取るか」だけ見ます (まだ何もしません)")
    _out("-" * 62)
    _out()
    subprocess.call([sys.executable, AUTORUN, "--who", "ALPHA", "--dry-run"])
    _out()
    _out("-" * 62)
    try:
        ans = input("  これで ON にしますか? (y = する / それ以外 = やめる): ").strip().lower()
    except EOFError:
        ans = ""
    if ans != "y":
        _out()
        _out("  やめました。何も変更していません。")
        return 0
    _out()
    rc = _ps(["-File", REGISTER_PS1, "-Minutes", str(minutes)])
    _out()
    if rc == 0:
        _out(f"  [OK] ON にしました。{minutes}分以内に最初の1件を取りにいきます。")
        _out(f"       動いたかは {LOGDIR}\\desk_*.log で見られます。")
        _out("       止めたくなったら 自走OFF_ALPHA.bat をダブルクリック。")
    else:
        _out("  [NG] 登録に失敗しました。この画面の文字をそのまま Claude に貼ってください。")
    return rc


def turn_off() -> int:
    _out()
    _out("=" * 62)
    _out("  窓口 ALPHA の自走を OFF にします")
    _out("=" * 62)
    _out()
    rc = _ps(["-Command",
              f"try {{ Unregister-ScheduledTask -TaskName '{TASK}' -Confirm:$false "
              f"-ErrorAction Stop; exit 0 }} catch {{ exit 2 }}"])
    _out()
    if rc == 0:
        _out("  止めました。")
        _out("  走行中の1件は最後までやり切ってから止まります (途中で壊さないため)。")
    elif rc == 2:
        _out("  もともと ON になっていませんでした。")
    else:
        _out("  [NG] 解除に失敗しました。この画面の文字をそのまま Claude に貼ってください。")
    return 0 if rc in (0, 2) else rc


def main(argv=None) -> int:
    # cmd.exe の画面は CP932。化けさせない (ここを決められるのが Python にした理由)。
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="cp932", errors="replace")
        except Exception:                                      # noqa: BLE001
            pass
    ap = argparse.ArgumentParser(description="窓口 ALPHA の自走を ON/OFF する")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--on", action="store_true")
    g.add_argument("--off", action="store_true")
    ap.add_argument("--minutes", type=int, default=5)
    a = ap.parse_args(argv)
    return turn_on(a.minutes) if a.on else turn_off()


if __name__ == "__main__":
    raise SystemExit(main())
