"""
Claude Code .jsonl 会話履歴を読みやすいテキストに変換

使い方:
    python convert_chat_history.py
        → 全プロジェクトの .jsonl を変換して
          C:\\Users\\imax2\\backups\\.claude_backup\\readable\\ に出力

出力形式:
    プロジェクト別フォルダ / セッション別ファイル
    {project}/{date}_{sessionId8}.txt
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CLAUDE_DIR = Path(r"C:\Users\imax2\.claude\projects")
OUTPUT_DIR = Path(r"C:\Users\imax2\backups\.claude_backup\readable")
JST = timezone(timedelta(hours=9))


def fmt_ts(iso: str) -> str:
    if not iso:
        return "         "
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(JST)
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return iso[:16]


def extract_text(content) -> str:
    """messageのcontentから本文テキストを抽出"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        t = block.get("type")
        if t == "text":
            parts.append(block.get("text", ""))
        elif t == "tool_use":
            name = block.get("name", "?")
            inp = block.get("input", {})
            # ツール呼び出しは1行サマリー
            if name == "Bash":
                cmd = inp.get("command", "")[:120]
                parts.append(f"[Bash] {cmd}")
            elif name == "Read":
                parts.append(f"[Read] {inp.get('file_path', '')}")
            elif name == "Write":
                parts.append(f"[Write] {inp.get('file_path', '')}")
            elif name == "Edit":
                parts.append(f"[Edit] {inp.get('file_path', '')}")
            elif name == "Grep":
                parts.append(f"[Grep] {inp.get('pattern', '')}")
            elif name == "Glob":
                parts.append(f"[Glob] {inp.get('pattern', '')}")
            elif name == "TodoWrite":
                parts.append("[TodoWrite]")
            else:
                parts.append(f"[{name}]")
        elif t == "tool_result":
            # ツール結果は省略 (長くなりすぎる)
            continue
        elif t == "thinking":
            # 思考ブロックも省略
            continue
    return "\n".join(p for p in parts if p)


def convert_session(jsonl_path: Path, out_path: Path) -> tuple[int, int]:
    """1つのjsonlを読みやすいテキストに変換"""
    lines_in = 0
    msgs_out = 0
    sid = jsonl_path.stem
    first_ts = None
    last_ts = None
    chunks = []

    with jsonl_path.open("r", encoding="utf-8") as f:
        for raw in f:
            lines_in += 1
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            mtype = obj.get("type")
            if mtype not in ("user", "assistant"):
                continue
            ts_iso = obj.get("timestamp", "")
            if ts_iso:
                if not first_ts:
                    first_ts = ts_iso
                last_ts = ts_iso
            msg = obj.get("message", {})
            text = extract_text(msg.get("content"))
            if not text.strip():
                continue
            # システムリマインダー除去
            text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL).strip()
            if not text:
                continue
            role = "USER" if mtype == "user" else "CLAUDE"
            chunks.append(f"[{fmt_ts(ts_iso)}] {role}:\n{text}\n")
            msgs_out += 1

    if not chunks:
        return lines_in, 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"==============================================\n"
        f"Session: {sid[:8]}\n"
        f"Period:  {fmt_ts(first_ts)} - {fmt_ts(last_ts)} (JST)\n"
        f"Messages: {msgs_out}\n"
        f"==============================================\n\n"
    )
    out_path.write_text(header + "\n".join(chunks), encoding="utf-8")
    return lines_in, msgs_out


def project_label(project_dir_name: str) -> str:
    """ディレクトリ名から短いラベル生成"""
    if "iMakHQ" in project_dir_name:
        return "iMakHQ"
    if "iMakTCG" in project_dir_name:
        return "iMakTCG"
    if "iMakMercari" in project_dir_name:
        return "iMakMercari"
    if "iMakG-shock" in project_dir_name or "iMakG_shock" in project_dir_name:
        return "iMakG-shock"
    if "ichibankuji" in project_dir_name:
        return "iMak_ichibankuji"
    if "iMakeBayAPI" in project_dir_name:
        return "iMakeBayAPI"
    if "iMakAudit" in project_dir_name:
        return "iMakAudit"
    return project_dir_name[:30]


def main():
    if not CLAUDE_DIR.exists():
        print(f"Source not found: {CLAUDE_DIR}")
        sys.exit(1)

    total_files = 0
    total_msgs = 0
    skipped = 0

    for proj_dir in CLAUDE_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        label = project_label(proj_dir.name)
        for jsonl in proj_dir.glob("*.jsonl"):
            sid8 = jsonl.stem[:8]
            # 出力先ファイル名
            try:
                mtime = datetime.fromtimestamp(jsonl.stat().st_mtime, JST)
                date_str = mtime.strftime("%Y%m%d")
            except Exception:
                date_str = "unknown"
            out = OUTPUT_DIR / label / f"{date_str}_{sid8}.txt"

            # 既存ファイルが新しければスキップ
            if out.exists() and out.stat().st_mtime >= jsonl.stat().st_mtime:
                skipped += 1
                continue

            try:
                _, msgs = convert_session(jsonl, out)
                if msgs > 0:
                    total_files += 1
                    total_msgs += msgs
            except Exception as e:
                print(f"  ERROR {jsonl.name}: {e}")

    print(f"Converted: {total_files} files / {total_msgs} messages")
    print(f"Skipped (up-to-date): {skipped}")
    print(f"Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
