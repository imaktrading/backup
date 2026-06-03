"""control_panel.py - リバイスくん 操作パネル (シンプル版).

1 画面に集約 + 詳細オプション折り畳み + cron Menubutton。

起動:
  python control_panel.py            # コンソール付
  pythonw control_panel.py           # コンソールなし
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from queue import Empty, Queue

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

# ============================================================================
# 定数
# ============================================================================
PROJECT = Path(__file__).resolve().parent
RUN_REVISE_PY = PROJECT / "run_revise.py"
DECISION_LOG_DIR = PROJECT / "decision_log"
CSV_OUTPUT_DIR = PROJECT / "csv_output"
GUI_STATE_FILE = PROJECT / ".gui_state.json"
REGISTER_TASK_PS1 = PROJECT / "tools" / "register_task.ps1"

EBAY_FILEEXCHANGE_URL = "https://www.ebay.com/sh/reports/uploads"

# 後方互換 (回帰 test 用): URL/ID extractor は残置
GSHEET_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
GSHEET_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{40,}$")


def extract_sheet_id(value: str) -> str | None:
    """ユーザー入力 (URL or 直 ID) から spreadsheet ID を抽出 (test 用残置)."""
    if not value:
        return None
    s = value.strip()
    m = GSHEET_URL_RE.search(s)
    if m:
        return m.group(1)
    if GSHEET_ID_RE.match(s):
        return s
    return None


# 対象スプシ (= price_revise.SHEETS と同期。3 固定なので checkbox 化)
SHEET_DEFS = [
    ("HIGH", "HIGH (高価格帯)"),
    ("LOW",  "LOW (低価格帯)"),
    ("公式", "公式 (UNIQLO/GU drop-shipping)"),
]
DEFAULT_SHEET_KEYS = ["HIGH", "LOW", "公式"]


# ============================================================================
# ログ parse (subprocess stdout サマリ抽出, 回帰テスト維持のため残す)
# ============================================================================
def parse_summary_line(line: str, summary: dict) -> bool:
    """1 行から進捗情報を抽出し summary を更新. 更新があれば True."""
    line = line.strip()
    updated = False
    if "全行数:" in line:
        try:
            summary["total_rows"] = int(line.split("全行数:")[1].split()[0])
            updated = True
        except (ValueError, IndexError):
            pass
    elif "F 初期化対象" in line and ":" in line:
        try:
            summary["init_targets"] = int(line.rsplit(":", 1)[1].strip().split()[0])
            updated = True
        except (ValueError, IndexError):
            pass
    elif "revise 候補" in line and ":" in line:
        try:
            summary["revise_candidates"] = int(line.rsplit(":", 1)[1].strip().split()[0])
            updated = True
        except (ValueError, IndexError):
            pass
    elif "revise 可能:" in line:
        try:
            head = line.split("revise 可能:")[1]
            summary["revisable"] = int(head.split("/")[0].strip().split()[0])
            updated = True
        except (ValueError, IndexError):
            pass
    elif "上限" in line and "超過" in line:
        summary["cap_exceeded"] = True
        updated = True
    return updated


# ============================================================================
# 状態保存
# ============================================================================
def load_state() -> dict:
    if not GUI_STATE_FILE.exists():
        return {"sheet_keys": list(DEFAULT_SHEET_KEYS)}
    try:
        with GUI_STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"sheet_keys": list(DEFAULT_SHEET_KEYS)}


def save_state(state: dict):
    try:
        with GUI_STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ============================================================================
# control panel 本体 (1 画面集約版)
# ============================================================================
class ControlPanel:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("リバイスくん")

        self.state = load_state()
        self.proc: subprocess.Popen | None = None
        self.log_queue: Queue[str] = Queue()
        self.options_visible = False

        # 前回の window geometry を復元 (= ない時は default)
        last_geom = self.state.get("geometry")
        self.root.geometry(last_geom if last_geom else "900x340")
        # 終了時に geometry 保存
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------
    def _build_ui(self):
        # 大ボタン用 style
        style = ttk.Style()
        style.configure("Big.TButton", font=("", 14, "bold"), padding=(30, 18))

        # === Top: 対象スプシ checkbox ===
        top = ttk.LabelFrame(self.root, text="対象スプシ")
        top.pack(fill="x", padx=12, pady=(12, 8))

        saved = set(self.state.get("sheet_keys") or DEFAULT_SHEET_KEYS)
        self.sheet_vars: dict[str, tk.BooleanVar] = {}
        for key, label in SHEET_DEFS:
            v = tk.BooleanVar(value=(key in saved))
            cb = ttk.Checkbutton(top, text=label, variable=v,
                                  command=self._on_sheet_toggle)
            cb.pack(side="left", padx=8, pady=4)
            self.sheet_vars[key] = v

        # === 大ボタン 1 つ (= 2026-05-22 統合: 新 logic では mode 区別なし) ===
        big_buttons = ttk.Frame(self.root)
        big_buttons.pack(pady=12)

        self.btn_start = ttk.Button(big_buttons, text="revise 実行", style="Big.TButton",
                                    command=self.on_start)
        self.btn_start.pack(side="left", padx=8)

        # === 状態 + 停止 (小) ===
        sub = ttk.Frame(self.root)
        sub.pack(pady=(0, 8))
        self.var_status = tk.StringVar(value="待機中")
        ttk.Label(sub, textvariable=self.var_status, foreground="blue",
                  font=("", 11)).pack(side="left", padx=(0, 12))
        self.btn_stop = ttk.Button(sub, text="停止", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left")

        # 内部用 (UI 簡素化 2026-05-22: dry-run default ON、review xlsx default ON)
        self.var_dry_run = tk.BooleanVar(value=True)
        self.var_review_xlsx = tk.BooleanVar(value=True)

        # === レビュー xlsx オプション ===
        review_row = ttk.Frame(self.root)
        review_row.pack(fill="x", padx=12, pady=(0, 4))
        ttk.Checkbutton(
            review_row,
            text="レビュー xlsx 生成 (= 旧/新 比較、HQ snapshot + Trading API、~30秒)",
            variable=self.var_review_xlsx,
        ).pack(side="left")

        # === Bottom: CSV / cron ===
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=12, pady=(8, 6))

        ttk.Button(bottom, text="最新 CSV を開く",
                   command=self.on_open_csv_dir).pack(side="left", padx=2)
        ttk.Button(bottom, text="eBay FileExchange",
                   command=self.on_open_ebay).pack(side="left", padx=2)

        self.cron_menu = tk.Menu(self.root, tearoff=0)
        self.cron_menu.add_command(label="状態確認",
                                   command=lambda: self._run_register_task("Status"))
        self.cron_menu.add_command(label="登録", command=self.on_cron_register)
        self.cron_menu.add_command(label="削除", command=self.on_cron_unregister)

        btn_cron = ttk.Menubutton(bottom, text="cron ▼")
        btn_cron["menu"] = self.cron_menu
        btn_cron.pack(side="left", padx=2)

        ttk.Button(bottom, text="ログクリア",
                   command=self.clear_log).pack(side="right", padx=2)
        ttk.Button(bottom, text="ログ表示",
                   command=self.toggle_log).pack(side="right", padx=2)

        # === 実行ログ (折り畳み、初期非表示) ===
        self.log_frame = ttk.LabelFrame(self.root, text="実行ログ")
        self.txt_out = scrolledtext.ScrolledText(self.log_frame, wrap="word",
                                                 font=("Consolas", 9), height=8)
        self.txt_out.pack(fill="both", expand=True, padx=4, pady=4)
        self.log_visible = False

    # ------------------------------------------------------------------
    # ログ折り畳み
    # ------------------------------------------------------------------
    def toggle_log(self):
        if self.log_visible:
            self.log_frame.pack_forget()
        else:
            self.log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.log_visible = not self.log_visible

    def clear_log(self):
        self.txt_out.delete("1.0", "end")

    # ------------------------------------------------------------------
    # 巡回開始 / 停止
    # ------------------------------------------------------------------
    def _get_checked_sheet_keys(self) -> list[str]:
        return [k for k, v in self.sheet_vars.items() if v.get()]

    def _on_sheet_toggle(self):
        self.state["sheet_keys"] = self._get_checked_sheet_keys()
        save_state(self.state)

    def on_start(self):
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("実行中", "既に巡回が走っています。")
            return

        checked = self._get_checked_sheet_keys()
        if not checked:
            messagebox.showerror("選択エラー", "対象スプシを 1 つ以上 check してください。")
            return

        self._on_sheet_toggle()
        self.txt_out.delete("1.0", "end")

        # 新 logic (2026-05-22 統合): mode 区別なし、default 50 件上限。
        # 50 件超過 → run_price_revise が WARN log + cap_exceeded で通知、xlsx で確認可能。
        cmd = [sys.executable, "-X", "utf8", str(RUN_REVISE_PY),
               "--sheets", ",".join(checked)]
        if self.var_dry_run.get():
            cmd.append("--dry-run")
        if self.var_review_xlsx.get():
            cmd.append("--review-xlsx")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        self._append_out(f"[GUI] 起動 (sheets={','.join(checked)})\n")
        self._append_out(f"[GUI] {' '.join(cmd)}\n\n")

        try:
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            messagebox.showerror("起動失敗", str(e))
            return

        self.var_status.set("実行中")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")

        threading.Thread(target=self._reader_thread, daemon=True).start()
        self.root.after(100, self._drain_queue)

    def on_stop(self):
        if not self.proc or self.proc.poll() is not None:
            return
        if not messagebox.askyesno("停止確認", "巡回を強制停止しますか?"):
            return
        try:
            self.proc.terminate()
        except Exception as e:
            messagebox.showerror("停止失敗", str(e))

    def _reader_thread(self):
        assert self.proc and self.proc.stdout
        for line in self.proc.stdout:
            self.log_queue.put(line)
        self.log_queue.put("__EOF__")

    def _drain_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__EOF__":
                    self._on_proc_exit()
                    return
                self._append_out(line)
        except Empty:
            pass
        if self.proc and self.proc.poll() is None:
            self.root.after(100, self._drain_queue)
        else:
            self.root.after(200, self._drain_queue)

    def _on_proc_exit(self):
        rc = self.proc.poll() if self.proc else -1
        self._append_out(f"\n[GUI] 終了 (exit={rc})\n")
        self.var_status.set(f"完了 (exit={rc})")
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.proc = None

    # ------------------------------------------------------------------
    # cron
    # ------------------------------------------------------------------
    def _run_register_task(self, action: str):
        if not REGISTER_TASK_PS1.exists():
            messagebox.showerror("ファイルなし", f"{REGISTER_TASK_PS1} が見つかりません。")
            return
        cmd = [
            "powershell.exe", "-ExecutionPolicy", "Bypass", "-NonInteractive",
            "-File", str(REGISTER_TASK_PS1),
            "-Action", action,
        ]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=30)
            output = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
            messagebox.showinfo(f"cron {action}", output or "(出力なし)")
        except Exception as e:
            messagebox.showerror("cron 実行失敗", str(e))

    def on_cron_register(self):
        if messagebox.askyesno("cron 登録",
                                "iMakRevise_PriceCycle を毎日 00:30/04:30/08:30/12:30/16:30/20:30 に登録します。\n\n登録しますか?"):
            self._run_register_task("Register")

    def on_cron_unregister(self):
        if messagebox.askyesno("cron 削除", "iMakRevise_PriceCycle を削除します。よろしいですか?"):
            self._run_register_task("Unregister")

    # ------------------------------------------------------------------
    # CSV / eBay
    # ------------------------------------------------------------------
    def on_open_csv_dir(self):
        CSV_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(CSV_OUTPUT_DIR))
        except Exception as e:
            messagebox.showerror("起動失敗", str(e))

    def on_open_ebay(self):
        webbrowser.open(EBAY_FILEEXCHANGE_URL)

    # ------------------------------------------------------------------
    # 出力
    # ------------------------------------------------------------------
    def _append_out(self, text: str):
        self.txt_out.insert("end", text)
        self.txt_out.see("end")

    # ------------------------------------------------------------------
    # 終了時: window 状態保存
    # ------------------------------------------------------------------
    def _on_close(self):
        try:
            self.state["geometry"] = self.root.geometry()  # 例: "900x340+100+50"
            save_state(self.state)
        except Exception:
            pass
        self.root.destroy()


# 2026-05-22: SettingsWindow + 設定ボタン 撤去 (= 設定は config/revise_params.json 直編集)


# ============================================================================
# entry point
# ============================================================================
def main():
    root = tk.Tk()
    ControlPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
