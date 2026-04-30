"""control_panel - iMakInventory GUI 操作パネル (Phase 6b).

Tkinter ベースの操作パネル:
- スプシ ID 入力 (HIGH/LOW セット or 単一スプシ、ラジオで切替)
- 履歴 combobox (.gui_state.json に保存、最新 5 件)
- オプション: test_mode / skip_upload / limit
- 巡回開始 → run_cycle.py を subprocess.Popen
- 進捗: stdout pipe を threading で tail
- 停止 → subprocess に SIGTERM (Windows: terminate)
- ログ tail: decision_log/cycle_*.jsonl の最新を表示
- cron 状態確認 / TEST タスク登録 / 本番タスク登録 (確認 dialog 付)

依存: 標準 Tkinter (Python 同梱)、subprocess、threading、json
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# Google Sheets URL から ID 抽出
GSHEETS_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")


def extract_sheet_id(value: str) -> str:
    """URL or ID 文字列から spreadsheet ID を抽出.
    既に ID なら trim して返す (英数字 + _- のみの 30 文字以上)。
    """
    if not value:
        return ""
    s = value.strip()
    m = GSHEETS_URL_RE.search(s)
    if m:
        return m.group(1)
    # URL ではなさそう → そのまま ID として返す (空白除去のみ)
    return s

SCRIPT_DIR = Path(__file__).resolve().parent
GUI_STATE_FILE = SCRIPT_DIR / ".gui_state.json"
DECISION_LOG_DIR = SCRIPT_DIR / "decision_log"
TOOLS_DIR = SCRIPT_DIR / "tools"
HISTORY_MAX = 5


# ============================================================================
# State persistence
# ============================================================================
def _load_state() -> dict:
    if not GUI_STATE_FILE.exists():
        return {"high_history": [], "low_history": [], "single_history": []}
    try:
        return json.loads(GUI_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"high_history": [], "low_history": [], "single_history": []}


def _save_state(state: dict):
    try:
        GUI_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _push_history(history: list, value: str) -> list:
    """value を先頭に追加 (重複は削除して再追加)、HISTORY_MAX 件保持."""
    if not value:
        return history
    new = [value] + [h for h in history if h != value]
    return new[:HISTORY_MAX]


# ============================================================================
# GUI
# ============================================================================
class ControlPanel:
    SUMMARY_POLL_MS = 30_000  # 30 秒おきに状態を refresh
    PROGRESS_POLL_MS = 2_000  # 巡回中のみ 2 秒間隔で速い refresh
    ERRORS_WARN_THRESHOLD = 5  # この件数を超えたら赤色警告

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("iMakInventory 操作パネル (Phase 9b)")
        root.geometry("900x780")
        self.state = _load_state()
        self.proc: subprocess.Popen | None = None
        self.reader_thread: threading.Thread | None = None
        self._build_ui()
        self._refresh_log_tail()
        # サマリバーの自動更新ループを開始
        self._summary_poll()

    def _build_ui(self):
        # === Live summary bar (Phase 9b) ===
        summary_frame = ttk.LabelFrame(self.root, text="状態サマリ")
        summary_frame.pack(fill="x", padx=8, pady=4)
        self.summary_status_label = tk.Label(
            summary_frame, text="(更新待ち...)", anchor="w", justify="left",
            font=("Yu Gothic UI", 10, "bold"),
        )
        self.summary_status_label.pack(fill="x", padx=4, pady=2)
        self.summary_progress_label = tk.Label(
            summary_frame, text="", anchor="w", justify="left",
        )
        self.summary_progress_label.pack(fill="x", padx=4, pady=2)
        self.summary_cron_label = tk.Label(
            summary_frame, text="cron: (未確認)", anchor="w", justify="left",
        )
        self.summary_cron_label.pack(fill="x", padx=4, pady=2)
        self.summary_errors_label = tk.Label(
            summary_frame, text="", anchor="w", justify="left",
        )
        self.summary_errors_label.pack(fill="x", padx=4, pady=2)

        # === Mode selector ===
        mode_frame = ttk.LabelFrame(self.root, text="スプシモード")
        mode_frame.pack(fill="x", padx=8, pady=4)
        self.mode_var = tk.StringVar(value="dual")
        ttk.Radiobutton(mode_frame, text="HIGH/LOW セット",
                        variable=self.mode_var, value="dual",
                        command=self._on_mode_change).pack(side="left", padx=8, pady=4)
        ttk.Radiobutton(mode_frame, text="単一スプシ",
                        variable=self.mode_var, value="single",
                        command=self._on_mode_change).pack(side="left", padx=8, pady=4)

        # === Dual mode (HIGH/LOW) ===
        self.dual_frame = ttk.LabelFrame(self.root, text="HIGH/LOW セット")
        self.dual_frame.pack(fill="x", padx=8, pady=4)

        ttk.Label(self.dual_frame, text="HIGH URL/ID:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.high_id_var = tk.StringVar()
        self.high_combo = ttk.Combobox(self.dual_frame, textvariable=self.high_id_var, width=70,
                                       values=self.state.get("high_history", []))
        self.high_combo.grid(row=0, column=1, sticky="we", padx=4, pady=2)

        ttk.Label(self.dual_frame, text="LOW  URL/ID:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.low_id_var = tk.StringVar()
        self.low_combo = ttk.Combobox(self.dual_frame, textvariable=self.low_id_var, width=70,
                                      values=self.state.get("low_history", []))
        self.low_combo.grid(row=1, column=1, sticky="we", padx=4, pady=2)

        ttk.Label(self.dual_frame,
                  text="(Google Sheets URL をそのまま貼付け OK、または ID 直接)",
                  font=("", 8), foreground="gray").grid(
            row=2, column=0, columnspan=2, sticky="w", padx=4)
        self.dual_frame.columnconfigure(1, weight=1)

        # === Single mode ===
        self.single_frame = ttk.LabelFrame(self.root, text="単一スプシ")
        self.single_frame.pack(fill="x", padx=8, pady=4)

        ttk.Label(self.single_frame, text="URL/ID:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.single_id_var = tk.StringVar()
        self.single_combo = ttk.Combobox(self.single_frame, textvariable=self.single_id_var, width=70,
                                         values=self.state.get("single_history", []))
        self.single_combo.grid(row=0, column=1, sticky="we", padx=4, pady=2)

        ttk.Label(self.single_frame, text="Label: ").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.single_label_var = tk.StringVar(value="SHEET")
        ttk.Entry(self.single_frame, textvariable=self.single_label_var, width=20).grid(
            row=1, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(self.single_frame,
                  text="(Google Sheets URL をそのまま貼付け OK、または ID 直接)",
                  font=("", 8), foreground="gray").grid(
            row=2, column=0, columnspan=2, sticky="w", padx=4)
        self.single_frame.columnconfigure(1, weight=1)

        # === Options ===
        opt_frame = ttk.LabelFrame(self.root, text="オプション")
        opt_frame.pack(fill="x", padx=8, pady=4)

        self.test_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_frame, text="--test-mode (完了通知 + ログ [TEST])",
                        variable=self.test_mode_var).pack(side="left", padx=8)
        self.monitor_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="--monitor-only (在庫チェックのみ、eBay UP なし)",
                        variable=self.monitor_only_var).pack(side="left", padx=8)
        self.skip_upload_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_frame, text="--skip-upload (CSV 生成までで止める)",
                        variable=self.skip_upload_var).pack(side="left", padx=8)
        ttk.Label(opt_frame, text="--limit:").pack(side="left", padx=8)
        self.limit_var = tk.StringVar(value="3")
        ttk.Entry(opt_frame, textvariable=self.limit_var, width=8).pack(side="left")

        # === Run controls ===
        run_frame = ttk.Frame(self.root)
        run_frame.pack(fill="x", padx=8, pady=4)
        self.start_btn = ttk.Button(run_frame, text="▶ 巡回開始", command=self._start_cycle)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ttk.Button(run_frame, text="■ 停止", command=self._stop_cycle, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        self.status_label = ttk.Label(run_frame, text="待機中")
        self.status_label.pack(side="left", padx=8)

        # === Log output ===
        log_frame = ttk.LabelFrame(self.root, text="出力 (subprocess stdout)")
        log_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.log_text = scrolledtext.ScrolledText(log_frame, height=15, wrap="none")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

        # === Cycle log tail ===
        tail_frame = ttk.LabelFrame(self.root, text="decision_log/cycle_*.jsonl 最新")
        tail_frame.pack(fill="x", padx=8, pady=4)
        self.tail_label = ttk.Label(tail_frame, text="(なし)", anchor="w", justify="left")
        self.tail_label.pack(fill="x", padx=4, pady=4)

        # === Task scheduler controls ===
        task_frame = ttk.LabelFrame(self.root, text="Windows タスクスケジューラ")
        task_frame.pack(fill="x", padx=8, pady=4)
        ttk.Button(task_frame, text="状態確認",
                   command=self._task_status).pack(side="left", padx=4, pady=4)
        ttk.Button(task_frame, text="TEST タスク登録 (5 分おき)",
                   command=lambda: self._task_register("test")).pack(side="left", padx=4, pady=4)
        ttk.Button(task_frame, text="TEST タスク削除",
                   command=lambda: self._task_unregister("test")).pack(side="left", padx=4, pady=4)
        ttk.Button(task_frame, text="本番タスク登録 (4h おき)",
                   command=lambda: self._task_register("cycle")).pack(side="left", padx=4, pady=4)
        ttk.Button(task_frame, text="本番タスク削除",
                   command=lambda: self._task_unregister("cycle")).pack(side="left", padx=4, pady=4)

        # === Restore (Phase 8c): backup シートから D 列を巻戻す ===
        restore_frame = ttk.LabelFrame(self.root, text="スプシ復元 (D 列バックアップから巻戻し)")
        restore_frame.pack(fill="x", padx=8, pady=4)
        ttk.Label(restore_frame, text="復元対象 URL/ID:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.restore_id_var = tk.StringVar()
        self.restore_id_entry = ttk.Entry(restore_frame, textvariable=self.restore_id_var, width=70)
        self.restore_id_entry.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        ttk.Button(restore_frame, text="backup 一覧読込",
                   command=self._restore_load_backups).grid(row=0, column=2, padx=4, pady=2)
        ttk.Label(restore_frame, text="backup シート:").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.restore_tab_var = tk.StringVar()
        self.restore_tab_combo = ttk.Combobox(
            restore_frame, textvariable=self.restore_tab_var, width=68, state="readonly"
        )
        self.restore_tab_combo.grid(row=1, column=1, sticky="w", padx=4, pady=2)
        ttk.Button(restore_frame, text="プレビュー (差分のみ)",
                   command=self._restore_preview).grid(row=2, column=1, sticky="w", padx=4, pady=4)
        ttk.Button(restore_frame, text="🔄 復元実行",
                   command=self._restore_apply).grid(row=2, column=2, sticky="w", padx=4, pady=4)

        self._on_mode_change()

    def _on_mode_change(self):
        mode = self.mode_var.get()
        if mode == "dual":
            for child in self.dual_frame.winfo_children():
                child.configure(state="normal")
            for child in self.single_frame.winfo_children():
                if isinstance(child, (ttk.Entry, ttk.Combobox)):
                    child.configure(state="disabled")
        else:
            for child in self.dual_frame.winfo_children():
                if isinstance(child, (ttk.Entry, ttk.Combobox)):
                    child.configure(state="disabled")
            for child in self.single_frame.winfo_children():
                child.configure(state="normal")

    # =====================================================================
    # Cycle execution
    # =====================================================================
    def _build_cmd(self) -> list[str] | None:
        cmd = [sys.executable, "-u", "run_cycle.py"]
        if self.test_mode_var.get():
            cmd.append("--test-mode")
        if self.monitor_only_var.get():
            cmd.append("--monitor-only")
        if self.skip_upload_var.get():
            cmd.append("--skip-upload")
        limit = self.limit_var.get().strip()
        if limit:
            try:
                int(limit)
                cmd.extend(["--limit", limit])
            except ValueError:
                messagebox.showerror("エラー", f"--limit は整数: {limit!r}")
                return None

        if self.mode_var.get() == "dual":
            high_raw = self.high_id_var.get().strip()
            low_raw = self.low_id_var.get().strip()
            high = extract_sheet_id(high_raw)
            low = extract_sheet_id(low_raw)
            if not high and not low:
                messagebox.showerror("エラー", "HIGH/LOW いずれかの URL or ID を入力してください")
                return None
            if high:
                cmd.extend(["--high-sheet-id", high])
                # 履歴は ID で保存 (URL でも構わないが ID の方が短い)
                self.state["high_history"] = _push_history(
                    self.state.get("high_history", []), high)
            if low:
                cmd.extend(["--low-sheet-id", low])
                self.state["low_history"] = _push_history(
                    self.state.get("low_history", []), low)
        else:
            raw = self.single_id_var.get().strip()
            sid = extract_sheet_id(raw)
            if not sid:
                messagebox.showerror("エラー", "単一スプシ URL or ID を入力してください")
                return None
            cmd.extend(["--sheet-id", sid])
            label = self.single_label_var.get().strip() or "SHEET"
            cmd.extend(["--sheet-label", label])
            self.state["single_history"] = _push_history(
                self.state.get("single_history", []), sid)

        _save_state(self.state)
        # Refresh combobox values
        self.high_combo["values"] = self.state.get("high_history", [])
        self.low_combo["values"] = self.state.get("low_history", [])
        self.single_combo["values"] = self.state.get("single_history", [])
        return cmd

    def _start_cycle(self):
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo("情報", "既に実行中です")
            return
        cmd = self._build_cmd()
        if cmd is None:
            return
        self._append_log(f"=== 起動: {' '.join(cmd)} ===\n")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=str(SCRIPT_DIR),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                bufsize=1, env=env,
            )
        except Exception as e:
            messagebox.showerror("起動失敗", f"{type(e).__name__}: {e}")
            return
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_label.configure(text="実行中...")
        self.reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self.reader_thread.start()

    def _read_stdout(self):
        if not self.proc or not self.proc.stdout:
            return
        try:
            for line in self.proc.stdout:
                self.root.after(0, self._append_log, line)
        except Exception as e:
            self.root.after(0, self._append_log, f"\n[reader err] {e}\n")
        finally:
            rc = self.proc.wait() if self.proc else None
            self.root.after(0, self._on_proc_exit, rc)

    def _on_proc_exit(self, rc):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_label.configure(text=f"完了 (exit={rc})")
        self._append_log(f"=== 終了 exit={rc} ===\n")
        self._refresh_log_tail()

    def _stop_cycle(self):
        if not self.proc:
            return
        if self.proc.poll() is not None:
            self._append_log("[stop] 既に終了済み\n")
            return
        try:
            self.proc.terminate()
            self._append_log("[stop] terminate() 送信\n")
            # 短時間で kill
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self._append_log("[stop] kill() forced\n")
        except Exception as e:
            self._append_log(f"[stop err] {e}\n")

    def _append_log(self, text: str):
        self.log_text.insert("end", text)
        self.log_text.see("end")

    # =====================================================================
    # Cycle log tail
    # =====================================================================
    def _refresh_log_tail(self):
        if not DECISION_LOG_DIR.exists():
            self.tail_label.configure(text="(decision_log dir なし)")
            return
        cycles = sorted(DECISION_LOG_DIR.glob("cycle_*.jsonl"),
                        key=lambda p: p.stat().st_mtime, reverse=True)[:5]
        if not cycles:
            self.tail_label.configure(text="(cycle log なし)")
            return
        lines = []
        for p in cycles:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                m = data.get("phases", {}).get("monitor", {})
                summary = (
                    f"{p.name}: {data.get('status', '?')} "
                    f"sold={m.get('newly_sold', '?')} "
                    f"in_stock={m.get('newly_in_stock', '?')} "
                    f"err={m.get('errors', '?')}"
                )
                lines.append(summary)
            except Exception:
                lines.append(f"{p.name}: (parse err)")
        self.tail_label.configure(text="\n".join(lines))

    # =====================================================================
    # Task scheduler
    # =====================================================================
    def _run_powershell(self, script: str, action: str = "Status") -> str:
        ps = TOOLS_DIR / script
        if not ps.exists():
            return f"❌ {ps} not found"
        try:
            r = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps),
                 "-Action", action],
                cwd=str(SCRIPT_DIR), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30,
            )
            return r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            return "❌ powershell timeout"
        except Exception as e:
            return f"❌ {type(e).__name__}: {e}"

    def _task_status(self):
        out = ""
        for s in ("register_test_task.ps1", "register_cycle_task.ps1"):
            out += f"--- {s} -Action Status ---\n{self._run_powershell(s, 'Status')}\n"
        self._show_dialog("タスク状態", out)

    def _task_register(self, kind: str):
        if kind == "cycle":
            if not messagebox.askyesno(
                "本番タスク登録",
                "本番タスク (4h サイクル) を登録します。\n"
                "TEST タスクで動作確認 OK でしたか?\n\n登録を続行しますか?"
            ):
                return
        script = "register_test_task.ps1" if kind == "test" else "register_cycle_task.ps1"
        out = self._run_powershell(script, "Register")
        self._show_dialog(f"{kind} タスク登録結果", out)

    def _task_unregister(self, kind: str):
        if not messagebox.askyesno(
            f"{kind} タスク削除",
            f"{kind} タスクを削除します。よろしいですか?"
        ):
            return
        script = "register_test_task.ps1" if kind == "test" else "register_cycle_task.ps1"
        out = self._run_powershell(script, "Unregister")
        self._show_dialog(f"{kind} タスク削除結果", out)

    def _show_dialog(self, title: str, text: str):
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.geometry("700x400")
        body = scrolledtext.ScrolledText(dlg, wrap="word")
        body.insert("end", text)
        body.configure(state="disabled")
        body.pack(fill="both", expand=True, padx=8, pady=8)
        ttk.Button(dlg, text="閉じる", command=dlg.destroy).pack(pady=4)

    # =====================================================================
    # Live summary bar (Phase 9b)
    # =====================================================================
    def _summary_poll(self):
        """30 秒おきに状態を更新。巡回中は 2 秒間隔で速く更新する."""
        try:
            self._summary_refresh()
        except Exception as e:
            try:
                self.summary_status_label.configure(
                    text=f"⚠️ summary refresh 例外: {type(e).__name__}: {e}",
                    fg="orange",
                )
            except Exception:
                pass
        # 巡回中なら速く再 schedule
        try:
            from progress import read_latest_progress  # noqa: PLC0415
            in_progress = read_latest_progress() is not None
        except Exception:
            in_progress = False
        delay = self.PROGRESS_POLL_MS if in_progress else self.SUMMARY_POLL_MS
        self.root.after(delay, self._summary_poll)

    def _summary_refresh(self):
        """progress + cycle log + cron task 情報を 1 度取得 → サマリ表示更新."""
        from progress import read_latest_progress  # noqa: PLC0415

        progress = read_latest_progress()
        in_progress = progress is not None
        # 状態行
        if in_progress:
            phase = progress.get("phase", "?")
            sl = progress.get("sheet_label") or ""
            sl_str = f" [{sl}]" if sl else ""
            self.summary_status_label.configure(
                text=f"🟢 巡回中: {phase}{sl_str} (cycle_ts={progress.get('cycle_ts','?')})",
                fg="dark green",
            )
            # 進捗行
            processed = progress.get("processed", 0)
            total = progress.get("total", 0)
            if total > 0:
                pct = processed * 100 // max(total, 1)
                bar_len = 30
                filled = bar_len * processed // max(total, 1)
                bar = "█" * filled + "░" * (bar_len - filled)
                self.summary_progress_label.configure(
                    text=f"  {bar} {processed}/{total} ({pct}%)",
                    fg="black",
                )
            else:
                self.summary_progress_label.configure(
                    text=f"  phase={phase} (進捗カウント未取得)", fg="gray",
                )
            # errors
            errors = int(progress.get("errors", 0) or 0)
            self._render_errors(errors, prefix="ライブ errors=")
        else:
            # 待機中 → 直近 cycle log を読込
            self.summary_progress_label.configure(text="", fg="black")
            latest = self._read_latest_cycle_log()
            if latest is None:
                self.summary_status_label.configure(
                    text="⚪ 待機中 (cycle log なし)", fg="black",
                )
                self.summary_errors_label.configure(text="", fg="black")
            else:
                ts_end = latest.get("ts_end") or latest.get("ts_start") or "?"
                status = latest.get("status", "?")
                monitor = latest.get("phases", {}).get("monitor", {}) or {}
                processed = monitor.get("processed", "?")
                newly_sold = monitor.get("newly_sold", "?")
                errors = int(monitor.get("errors", 0) or 0)
                self.summary_status_label.configure(
                    text=f"⚪ 待機中 / 最終 {ts_end[-8:]} status={status}",
                    fg="black",
                )
                self.summary_progress_label.configure(
                    text=f"  最終 monitor: processed={processed} sold={newly_sold} errors={errors}",
                    fg="black",
                )
                self._render_errors(errors, prefix="errors=")

        # cron 情報
        self._render_cron_info()

    def _render_errors(self, errors: int, prefix: str = "errors="):
        if errors > self.ERRORS_WARN_THRESHOLD:
            self.summary_errors_label.configure(
                text=f"  ⚠️ {prefix}{errors} (>{self.ERRORS_WARN_THRESHOLD}): 異常多発、cycle log 参照",
                fg="red",
            )
        elif errors > 0:
            self.summary_errors_label.configure(
                text=f"  {prefix}{errors}", fg="dark orange",
            )
        else:
            self.summary_errors_label.configure(text="", fg="black")

    def _render_cron_info(self):
        """schtasks /Query で iMakInventory_Cycle の Last/Next を取得."""
        try:
            r = subprocess.run(
                ["schtasks", "/Query", "/TN", "iMakInventory_Cycle", "/FO", "LIST", "/V"],
                capture_output=True, text=True, encoding="cp932", errors="replace",
                timeout=8,
            )
            if r.returncode != 0:
                self.summary_cron_label.configure(
                    text="cron: (iMakInventory_Cycle 未登録)", fg="gray",
                )
                return
            out = r.stdout or ""
            last_line = next((ln for ln in out.splitlines() if "前回の実行" in ln or "Last Run" in ln), "")
            next_line = next((ln for ln in out.splitlines() if "次回の実行" in ln or "Next Run" in ln), "")
            last = last_line.split(":", 1)[1].strip() if ":" in last_line else "?"
            nxt = next_line.split(":", 1)[1].strip() if ":" in next_line else "?"
            self.summary_cron_label.configure(
                text=f"cron: Last={last}  Next={nxt}", fg="black",
            )
        except subprocess.TimeoutExpired:
            self.summary_cron_label.configure(text="cron: (取得タイムアウト)", fg="gray")
        except FileNotFoundError:
            self.summary_cron_label.configure(text="cron: (schtasks 不在)", fg="gray")
        except Exception as e:
            self.summary_cron_label.configure(text=f"cron: 例外 {type(e).__name__}", fg="gray")

    def _read_latest_cycle_log(self) -> dict | None:
        try:
            files = sorted(
                DECISION_LOG_DIR.glob("cycle_*.jsonl"),
                key=lambda p: p.name, reverse=True,
            )
            if not files:
                return None
            return json.loads(files[0].read_text(encoding="utf-8"))
        except Exception:
            return None

    # =====================================================================
    # Restore (Phase 8c)
    # =====================================================================
    def _restore_get_sheet_id(self) -> str | None:
        raw = self.restore_id_var.get().strip()
        sid = extract_sheet_id(raw)
        if not sid:
            messagebox.showerror("エラー", "復元対象 URL or ID を入力してください")
            return None
        return sid

    def _restore_load_backups(self):
        sid = self._restore_get_sheet_id()
        if not sid:
            return
        try:
            from sheet_updater import open_sheet_by_id  # noqa: PLC0415
            from backup import list_backup_tabs  # noqa: PLC0415
            sh = open_sheet_by_id(sid)
            tabs = list_backup_tabs(sh)
            if not tabs:
                messagebox.showinfo("情報", "backup_* シートが見つかりません")
                self.restore_tab_combo["values"] = []
                self.restore_tab_var.set("")
                return
            values = [t["title"] for t in tabs]
            self.restore_tab_combo["values"] = values
            self.restore_tab_var.set(values[0])
            self._append_log(f"=== backup 一覧 ({len(tabs)} 件): 最新={values[0]} ===\n")
        except Exception as e:
            messagebox.showerror("失敗", f"{type(e).__name__}: {e}")

    def _restore_preview(self):
        sid = self._restore_get_sheet_id()
        if not sid:
            return
        tab = self.restore_tab_var.get().strip()
        if not tab:
            messagebox.showerror("エラー", "backup シートを選択してください")
            return
        try:
            from sheet_updater import open_sheet_by_id  # noqa: PLC0415
            from backup import restore_from_backup  # noqa: PLC0415
            sh = open_sheet_by_id(sid)
            r = restore_from_backup(sh, tab, dry_run=True)
            self._show_restore_result(r, applied=False)
        except Exception as e:
            messagebox.showerror("失敗", f"{type(e).__name__}: {e}")

    def _restore_apply(self):
        sid = self._restore_get_sheet_id()
        if not sid:
            return
        tab = self.restore_tab_var.get().strip()
        if not tab:
            messagebox.showerror("エラー", "backup シートを選択してください")
            return
        # 二重確認: 復元はスプシ書込発生
        if not messagebox.askyesno(
            "復元実行 確認",
            f"backup シート [{tab}] から D 列を巻戻します。\n"
            f"この操作はスプシ書込が発生します。続行しますか?"
        ):
            return
        try:
            from sheet_updater import open_sheet_by_id  # noqa: PLC0415
            from backup import restore_from_backup  # noqa: PLC0415
            sh = open_sheet_by_id(sid)
            r = restore_from_backup(sh, tab, dry_run=False)
            self._show_restore_result(r, applied=True)
        except Exception as e:
            messagebox.showerror("失敗", f"{type(e).__name__}: {e}")

    def _show_restore_result(self, r: dict, applied: bool):
        if r.get("error"):
            messagebox.showerror("失敗", r["error"])
            return
        n = r.get("to_restore", 0)
        preview = r.get("diff_preview", [])
        lines = []
        lines.append(("✅ 復元完了" if applied else "📋 プレビュー (未適用)"))
        lines.append(f"  backup_tab: {r.get('backup_tab')}")
        lines.append(f"  to_restore: {n} 件")
        lines.append("")
        if preview:
            lines.append("差分プレビュー (先頭 50 件):")
            lines.append("  row  | before → after")
            lines.append("  -----+---------------")
            for p in preview:
                b = repr(p.get("before") or "")
                a = repr(p.get("after") or "")
                lines.append(f"  {p['row']:>4} | {b} → {a}")
        else:
            lines.append("(差分 0 件 ─ 復元不要)")
        self._show_dialog(("復元結果" if applied else "プレビュー結果"), "\n".join(lines))


def main():
    root = tk.Tk()
    app = ControlPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
