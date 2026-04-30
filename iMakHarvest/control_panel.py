"""control_panel - iMakHarvest 操作パネル (Tkinter ベース).

trabajo の URL 抽出パネルを踏襲した GUI:
  - サービスボタン (メルカリ / Amazon / ヤフオク / ラクマ / メルカリShops)
    Phase 1a ではメルカリのみ active。他は disabled で実装予定 phase を表示。
  - 出力先スプシ選択 (HIGH / LOW / 任意 URL)
    任意 URL は Google Sheets URL から sheet_id + gid を自動パース。
  - オプション (処理中の画面を表示する = headless 無効化)
  - 実行は別スレッド (UI を固めない)、ログ欄にリアルタイム表示

呼び出し:
    python control_panel.py
"""
from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext

from scrapers import mercari_likes
from sheet_writer import HIGH_SHEET_ID, LISTINGS_GID, LOW_SHEET_ID, write_to_sheet


# ============================================================================
# Google Sheets URL parser
# ============================================================================
SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
GID_RE = re.compile(r"[#?&]gid=(\d+)")


def parse_sheet_url(url: str) -> tuple[str, int]:
    """Google Sheets URL から (sheet_id, gid) を抽出.
    gid 指定が無ければ LISTINGS_GID にフォールバック。

    対応形式:
      - https://docs.google.com/spreadsheets/d/<ID>/edit#gid=<GID>
      - https://docs.google.com/spreadsheets/d/<ID>/edit?gid=<GID>
      - https://docs.google.com/spreadsheets/d/<ID>/edit (gid 省略)
      - 生 sheet_id (44 文字程度の英数字_-) もそのまま受け取る
    """
    if not url or not url.strip():
        raise ValueError("URL が空です")
    s = url.strip()

    m = SHEET_ID_RE.search(s)
    if m:
        sheet_id = m.group(1)
    else:
        # 生 ID らしき文字列なら受け入れる
        if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", s):
            sheet_id = s
        else:
            raise ValueError(f"スプシ URL のフォーマットが不正: {url}")

    gm = GID_RE.search(s)
    gid = int(gm.group(1)) if gm else LISTINGS_GID
    return sheet_id, gid


# ============================================================================
# UI
# ============================================================================
SERVICE_DEFS = [
    # (key, label, description, enabled, scope_note)
    ("mercari", "メルカリ",
     "メルカリのお気に入りに登録されている商品を元に情報を抽出します",
     True, ""),
    ("amazon", "Amazon",
     "Amazonの欲しいものリストに登録されている商品を元に情報を抽出します",
     False, "(Phase 1c 実装予定)"),
    ("yahoo", "ヤフオク",
     "ヤフオクのお気に入りに登録されている商品を元に情報を抽出します",
     False, "(Phase 2 実装予定)"),
    ("rakuma", "ラクマ",
     "ラクマのお気に入りに登録されている商品を元に情報を抽出します",
     False, "(Phase 2 実装予定)"),
    ("mercari_shops", "メルカリShops",
     "メルカリShopsのお気に入りに登録されている商品を元に情報を抽出します",
     False, "(Phase 1b 実装予定)"),
]


class HarvestPanel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("iMakHarvest - URL 抽出")
        self.geometry("820x720")
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._running = False
        self._build_ui()
        self.after(150, self._flush_log_queue)

    # ----------------------------------------------------------------
    # build
    # ----------------------------------------------------------------
    def _build_ui(self) -> None:
        # ヘッダー
        header = tk.Label(self, text="抽出", font=("Meiryo UI", 14, "bold"), anchor="w")
        header.pack(fill="x", padx=12, pady=(10, 4))

        # サービス選択
        svc = tk.LabelFrame(self, text="サービスを選択してね", padx=10, pady=8,
                            font=("Meiryo UI", 10))
        svc.pack(fill="x", padx=12, pady=4)
        self._service_buttons: dict[str, tk.Button] = {}
        for key, label, desc, enabled, note in SERVICE_DEFS:
            self._service_buttons[key] = self._make_service_row(svc, key, label, desc, enabled, note)

        # 出力先スプシ
        out = tk.LabelFrame(self, text="出力先スプシ", padx=10, pady=8, font=("Meiryo UI", 10))
        out.pack(fill="x", padx=12, pady=4)

        self.sheet_var = tk.StringVar(value="high")
        rb_high = tk.Radiobutton(out, text="HIGH", variable=self.sheet_var, value="high",
                                  command=self._on_sheet_change, font=("Meiryo UI", 10))
        rb_high.grid(row=0, column=0, sticky="w", padx=(0, 8))
        rb_low = tk.Radiobutton(out, text="LOW", variable=self.sheet_var, value="low",
                                 command=self._on_sheet_change, font=("Meiryo UI", 10))
        rb_low.grid(row=0, column=1, sticky="w", padx=(0, 8))
        rb_custom = tk.Radiobutton(out, text="任意 URL:", variable=self.sheet_var, value="custom",
                                    command=self._on_sheet_change, font=("Meiryo UI", 10))
        rb_custom.grid(row=0, column=2, sticky="w", padx=(0, 4))

        self.custom_url_var = tk.StringVar()
        self.custom_entry = tk.Entry(out, textvariable=self.custom_url_var, width=70,
                                      font=("Consolas", 9))
        self.custom_entry.grid(row=0, column=3, sticky="we", padx=4)
        self.custom_entry.configure(state="disabled")
        out.grid_columnconfigure(3, weight=1)

        hint = tk.Label(out,
                        text="※ Google Sheets の URL をそのまま貼り付け可 (gid 部分も自動認識)",
                        fg="#666", font=("Meiryo UI", 8))
        hint.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        # オプション
        opt = tk.LabelFrame(self, text="オプション", padx=10, pady=8, font=("Meiryo UI", 10))
        opt.pack(fill="x", padx=12, pady=4)
        # 既定 ON: Mercari は headless Chrome を bot 検出で弾く (2026-04-30 確認)
        # → 画面表示モードでないと /mypage/likes が「未対応ブラウザ」フォールバックされる
        self.show_browser_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opt,
                       text="処理中の画面を表示する (Mercari は非表示モード非対応のため、推奨 ON)",
                       variable=self.show_browser_var,
                       font=("Meiryo UI", 10)).pack(anchor="w")
        # 詳細取得: 各商品ページを訪問して タイトル/価格/状態/説明/画像 を取得
        self.fetch_detail_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opt,
                       text="商品詳細も取得する (タイトル/価格/状態/画像/説明) — 1 件あたり ~5 秒",
                       variable=self.fetch_detail_var,
                       font=("Meiryo UI", 10)).pack(anchor="w")
        # SOLD 除外
        self.exclude_sold_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opt,
                       text="SOLD 商品は除外 (売切は出品しても仕入れ不可)",
                       variable=self.exclude_sold_var,
                       font=("Meiryo UI", 10)).pack(anchor="w")

        # ステータス
        status_frame = tk.Frame(self)
        status_frame.pack(fill="x", padx=12, pady=(8, 4))
        self.status_var = tk.StringVar(value="ステータス: 待機中")
        tk.Label(status_frame, textvariable=self.status_var, anchor="w",
                 font=("Meiryo UI", 10, "bold")).pack(side="left", fill="x", expand=True)

        # ログ
        log_frame = tk.LabelFrame(self, text="ログ", padx=4, pady=4, font=("Meiryo UI", 10))
        log_frame.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.log_text = scrolledtext.ScrolledText(log_frame, height=16,
                                                    font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

    def _make_service_row(self, parent: tk.Widget, key: str, label: str, desc: str,
                          enabled: bool, scope_note: str) -> tk.Button:
        row = tk.Frame(parent)
        row.pack(fill="x", pady=3)
        btn = tk.Button(row, text=label, width=16, height=2,
                        state=("normal" if enabled else "disabled"),
                        command=(lambda k=key: self._on_service(k)) if enabled else None,
                        font=("Meiryo UI", 10))
        btn.pack(side="left", padx=4)
        desc_text = desc + (f"  {scope_note}" if scope_note else "")
        fg = "#000" if enabled else "#888"
        tk.Label(row, text=desc_text, anchor="w", justify="left", wraplength=580,
                 fg=fg, font=("Meiryo UI", 9)).pack(side="left", padx=8)
        return btn

    # ----------------------------------------------------------------
    # callbacks
    # ----------------------------------------------------------------
    def _on_sheet_change(self) -> None:
        if self.sheet_var.get() == "custom":
            self.custom_entry.configure(state="normal")
        else:
            self.custom_entry.configure(state="disabled")

    def _resolve_sheet(self) -> tuple[str, int, str]:
        """選択されたスプシを (sheet_id, gid, label) に解決."""
        choice = self.sheet_var.get()
        if choice == "high":
            return HIGH_SHEET_ID, LISTINGS_GID, "HIGH"
        if choice == "low":
            return LOW_SHEET_ID, LISTINGS_GID, "LOW"
        if choice == "custom":
            sid, gid = parse_sheet_url(self.custom_url_var.get())
            return sid, gid, f"任意 (gid={gid})"
        raise ValueError(f"unknown sheet choice: {choice}")

    def _on_service(self, key: str) -> None:
        if self._running:
            messagebox.showwarning("実行中", "現在別の収集が実行中です。完了をお待ちください。")
            return
        if key != "mercari":
            messagebox.showinfo("未実装", f"{key} は Phase 1a 範囲外です。")
            return
        try:
            sheet_id, gid, label = self._resolve_sheet()
        except ValueError as e:
            messagebox.showerror("スプシ URL エラー", str(e))
            return
        if not messagebox.askyesno(
            "確認",
            f"メルカリのいいね一覧から URL を収集し、\n出力先スプシ「{label}」に追記します。\n\n実行しますか？",
        ):
            return
        threading.Thread(
            target=self._run_mercari_thread,
            args=(sheet_id, gid, label),
            daemon=True,
        ).start()

    # ----------------------------------------------------------------
    # background work
    # ----------------------------------------------------------------
    def _run_mercari_thread(self, sheet_id: str, gid: int, label: str) -> None:
        self._running = True
        self._set_buttons_state(disabled=True)
        headless = not self.show_browser_var.get()
        fetch_detail = self.fetch_detail_var.get()
        exclude_sold = self.exclude_sold_var.get()

        self._set_status("メルカリ収集中...")
        self._log("=== メルカリ いいね収集 開始 ===")
        self._log(f"  出力先     : {label} (sheet_id={sheet_id[:14]}.., gid={gid})")
        self._log(f"  headless   : {headless}")
        self._log(f"  詳細取得   : {fetch_detail}")
        self._log(f"  SOLD除外   : {exclude_sold}")
        try:
            if fetch_detail:
                def progress(cur, total, msg):
                    self._set_status(f"商品詳細取得中... [{cur}/{total}]")
                    self._log(f"  [{cur}/{total}] {msg}")

                items = mercari_likes.collect_likes_with_details(
                    headless=headless,
                    exclude_sold=exclude_sold,
                    progress_callback=progress,
                )
            else:
                items = mercari_likes.collect_liked_urls(headless=headless)
            self._log(f"  収集完了   : {len(items)} 件")
            self._set_status(f"スプシ書込中... ({len(items)} 件)")
            result = write_to_sheet(items, spreadsheet_id=sheet_id, gid=gid)
            self._log(f"  書込結果   : appended={result['appended']}, "
                      f"skipped_existing={result['skipped_existing']}, "
                      f"input={result['input']}")
            self._set_status(
                f"完了: 新規 {result['appended']} 件 / 既出 skip {result['skipped_existing']} 件"
            )
            self._log("=== 完了 ===")
            messagebox.showinfo("完了",
                                f"収集 {len(items)} 件 → 新規追加 {result['appended']} 件 "
                                f"(既出 skip {result['skipped_existing']} 件)")
        except Exception as e:
            self._log(f"!!! エラー: {e}")
            self._set_status(f"失敗: {type(e).__name__}")
            messagebox.showerror("エラー", str(e))
        finally:
            self._running = False
            self._set_buttons_state(disabled=False)

    def _set_buttons_state(self, disabled: bool) -> None:
        # active なボタン (= mercari) のみ disable/enable 切替
        for key, btn in self._service_buttons.items():
            spec_enabled = next(s[3] for s in SERVICE_DEFS if s[0] == key)
            if not spec_enabled:
                continue
            btn.configure(state=("disabled" if disabled else "normal"))

    # ----------------------------------------------------------------
    # log / status helpers
    # ----------------------------------------------------------------
    def _log(self, msg: str) -> None:
        self._log_queue.put(f"[{datetime.now():%H:%M:%S}] {msg}")

    def _flush_log_queue(self) -> None:
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self.log_text.configure(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._flush_log_queue)

    def _set_status(self, msg: str) -> None:
        self.status_var.set(f"ステータス: {msg}")


def main() -> None:
    HarvestPanel().mainloop()


if __name__ == "__main__":
    main()
