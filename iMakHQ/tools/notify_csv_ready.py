# -*- coding: utf-8 -*-
"""CSV入稿準備OK を知らせる「CSV UP シグナル」(2026-06-26 ユーザー要望)。

NG対応(Act)の優先順位: ①CSV手直し → ②**このUPシグナル** → ③カタログ依頼/プログラム修正。
CSV を UP するのを最優先にしたいので、手直しが済んだ瞬間に目立つ通知を出し、
カタログ依頼等の後続処理を待たずに入稿に動けるようにする。

通知方式は monthly_snapshot_alert.show_modal_alert を再利用(Tkinter MessageBox +
PowerShell fallback の実績パターン)。headless Claude から BG 起動される想定:
    python notify_csv_ready.py <count> <csv_path>
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def build_message(count, csv_path, degraded=""):
    """通知本文 (純関数, test可)。

    ★2026-08-02: `degraded` が付いた走行は **緑にしない**。
    AI 補強 (タイトル最適化 / 絵柄照合 / AI総合レビュー) が落ちたまま
    「🟢 入稿準備OK」を出していたため、タイトルが短いまま入稿された実害があった。
    """
    name = os.path.basename(csv_path) if csv_path else "(CSV)"
    if degraded:
        return (f"⚠️ CSV入稿準備OK(ただしAI補強が落ちています): {count}件\n\n{name}\n\n"
                f"落ちたもの: {degraded}\n\n"
                "→ 内容の監査は済んでいます。急がないなら復旧後に再走を推奨。"
                "このまま UP する場合はタイトルが短い可能性があります")
    return f"🟢 CSV入稿準備OK: {count}件\n\n{name}\n\n→ eBay に UP してください(カタログ依頼/プログラム修正は後続で自動処理中)"


def notify(count, csv_path, degraded=""):
    """UP シグナルを出す。戻り: bool(成功)。"""
    from monthly_snapshot_alert import show_modal_alert
    title = "CSV UP シグナル" + ("(⚠️AI補強なし)" if degraded else "")
    return show_modal_alert(title, build_message(count, csv_path, degraded))


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    count = argv[0] if len(argv) > 0 else "?"
    csv_path = argv[1] if len(argv) > 1 else ""
    degraded = argv[2] if len(argv) > 2 else ""      # 例 "APIクレジット不足: 9件"
    ok = notify(count, csv_path, degraded)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
