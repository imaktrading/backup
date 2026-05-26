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

import os
import queue
import re
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext

from scrapers import (
    amazon_wishlist,
    mercari_likes,
    mercari_seller,
    mercari_shops_likes,
    snkrdunk_favorites,
    snkrdunk_official,
    workman_official,
)
from sheet_writer_mercari_seller import append_seller_items
from sheet_writer import HIGH_SHEET_ID, LISTINGS_GID, LOW_SHEET_ID, write_to_sheet
from sheet_writer_amazon import write_to_sheet as write_to_sheet_amazon
from sheet_writer_snkrdunk_aux import (
    get_listings_worksheet as get_snkrdunk_listings_ws,
    insert_aux_urls_for_row,
    open_sheet_by_id as open_snkrdunk_sheet,
)
from sheet_writer_workman_official import (
    OFFICIAL_SHEET_ID as WORKMAN_OFFICIAL_SHEET_ID,
    write_to_official_sheet as write_to_workman_official_sheet,
)

# Amazon ウィッシュリスト URL 保存先 (Mercari の chrome_profile と同じ親ディレクトリ)
AMAZON_URL_FILE = r"C:\Users\imax2\local_data\iMakHarvest\amazon_wishlist_url.txt"


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
# Amazon URL persistence
# ============================================================================
def _load_amazon_url() -> str:
    """前回保存した Amazon ウィッシュリスト URL を読込. 無ければ ""."""
    try:
        if os.path.exists(AMAZON_URL_FILE):
            with open(AMAZON_URL_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


def _save_amazon_url(url: str) -> None:
    """Amazon ウィッシュリスト URL を保存 (次回起動時の自動復元用)."""
    try:
        os.makedirs(os.path.dirname(AMAZON_URL_FILE), exist_ok=True)
        with open(AMAZON_URL_FILE, "w", encoding="utf-8") as f:
            f.write(url.strip())
    except Exception:
        pass


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
     True, ""),
    ("yahoo", "ヤフオク",
     "ヤフオクのお気に入りに登録されている商品を元に情報を抽出します",
     False, "(Phase 2 実装予定)"),
    ("rakuma", "ラクマ",
     "ラクマのお気に入りに登録されている商品を元に情報を抽出します",
     False, "(Phase 2 実装予定)"),
    ("mercari_shops", "メルカリShops",
     "メルカリShopsのお気に入りに登録されている商品を元に情報を抽出します",
     True, ""),
    ("workman", "ワークマン",
     "ワークマン公式商品 URL から商品情報を抽出 (改行区切りで複数 URL 可)",
     True, ""),
    ("snkrdunk", "SNKRDUNK 補仕入",
     "既存 OP listing (= ワンピース TCG OP\\d{2}-\\d{3}) に PSA10 補仕入 URL を投入 "
     "(AC-AG 列、出力先 = HIGH スプシ固定)",
     True, ""),
    ("snkrdunk_fav", "SNKRDUNK 抽出",
     "SNKRDUNK のお気に入り商品 (= login 必須) から URL を収集してスプシ A 列に append",
     True, ""),
    ("mercari_seller", "メルカリセラー",
     "メルカリ user profile URL (= /user/profile/<id>) から出品中商品を収集 "
     "→ 中間スプシ seller_<id> タブに append (= 同 card_id は AC-AG 補配置)",
     True, ""),
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
        # 下部 (= ログ + ステータス) を先に side="bottom" で確保、
        # 残り中央領域を Canvas + Scrollbar で scrollable にする。

        # === ログ (= 最下、ScrolledText 内蔵 scroll、固定) ===
        log_frame = tk.LabelFrame(self, text="ログ", padx=4, pady=4, font=("Meiryo UI", 10))
        log_frame.pack(side="bottom", fill="both", expand=False, padx=12, pady=(4, 12))
        self.log_text = scrolledtext.ScrolledText(log_frame, height=10,
                                                    font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")

        # === ステータス (= ログの直上、固定) ===
        status_frame = tk.Frame(self)
        status_frame.pack(side="bottom", fill="x", padx=12, pady=(0, 4))
        self.status_var = tk.StringVar(value="ステータス: 待機中")
        tk.Label(status_frame, textvariable=self.status_var, anchor="w",
                 font=("Meiryo UI", 10, "bold")).pack(side="left", fill="x", expand=True)

        # === 上部 scrollable container ===
        scroll_container = tk.Frame(self)
        scroll_container.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(scroll_container, highlightthickness=0, borderwidth=0)
        vbar = tk.Scrollbar(scroll_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # scrollable Frame (= 既存 widgets の親、self の代わり)
        scroll_frame = tk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

        def _on_frame_configure(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        scroll_frame.bind("<Configure>", _on_frame_configure)

        def _on_canvas_configure(e):
            # inner Frame を canvas 幅にフィット (= 水平 scroll は出さない)
            canvas.itemconfig(canvas_window, width=e.width)
        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        # mainloop 中の全ての MouseWheel イベントを canvas に流す
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 既存 _scroll_frame を後続の widgets の親として使う
        self._scroll_frame = scroll_frame
        parent = scroll_frame

        # ヘッダー
        header = tk.Label(parent, text="抽出", font=("Meiryo UI", 14, "bold"), anchor="w")
        header.pack(fill="x", padx=12, pady=(10, 4))

        # サービス選択
        svc = tk.LabelFrame(parent, text="サービスを選択してね", padx=10, pady=8,
                            font=("Meiryo UI", 10))
        svc.pack(fill="x", padx=12, pady=4)
        self._service_buttons: dict[str, tk.Button] = {}
        for key, label, desc, enabled, note in SERVICE_DEFS:
            self._service_buttons[key] = self._make_service_row(svc, key, label, desc, enabled, note)

        # Amazon ウィッシュリスト URL 入力欄
        amzn = tk.LabelFrame(parent, text="Amazon ウィッシュリスト URL (公開リスト)",
                             padx=10, pady=8, font=("Meiryo UI", 10))
        amzn.pack(fill="x", padx=12, pady=4)
        self.amazon_url_var = tk.StringVar(value=_load_amazon_url())
        self.amazon_url_entry = tk.Entry(amzn, textvariable=self.amazon_url_var,
                                          font=("Consolas", 9))
        self.amazon_url_entry.pack(fill="x")
        tk.Label(amzn,
                 text="※ 例: https://www.amazon.co.jp/hz/wishlist/ls/XXXXXXXXXXXXX  "
                      "(リストを「公開」設定にしておくこと)",
                 fg="#666", font=("Meiryo UI", 8)).pack(anchor="w", pady=(4, 0))

        # ワークマン公式商品 URL 入力欄 (multiline、改行区切りで複数 URL)
        wm = tk.LabelFrame(parent, text="ワークマン公式商品 URL (1 行 1 URL、改行区切りで複数可)",
                           padx=10, pady=8, font=("Meiryo UI", 10))
        wm.pack(fill="x", padx=12, pady=4)
        self.workman_urls_text = scrolledtext.ScrolledText(wm, height=4,
                                                            font=("Consolas", 9))
        self.workman_urls_text.pack(fill="x")
        tk.Label(wm,
                 text="※ 例: https://workman.jp/shop/g/g2300011882014/  "
                      "(空欄なら「ワークマン」ボタン無効)",
                 fg="#666", font=("Meiryo UI", 8)).pack(anchor="w", pady=(4, 0))

        # メルカリセラー (= user profile URL 抽出) の入力欄
        msel = tk.LabelFrame(parent, text="メルカリセラー (= /user/profile/<id> URL から出品抽出)",
                             padx=10, pady=8, font=("Meiryo UI", 10))
        msel.pack(fill="x", padx=12, pady=4)
        self.mercari_seller_url_var = tk.StringVar()
        tk.Entry(msel, textvariable=self.mercari_seller_url_var,
                 font=("Consolas", 9)).pack(fill="x")
        msel_row = tk.Frame(msel)
        msel_row.pack(fill="x", pady=(4, 0))
        tk.Label(msel_row,
                 text=f"最大抽出件数 (空欄/0 で無制限希望 → ハード CAP "
                      f"{mercari_seller.HARD_CAP_PER_SESSION} で打切):",
                 font=("Meiryo UI", 9)).pack(side="left")
        self.mercari_seller_limit_var = tk.StringVar(
            value=str(mercari_seller.DEFAULT_USER_LIMIT)
        )
        tk.Entry(msel_row, textvariable=self.mercari_seller_limit_var, width=8,
                 font=("Consolas", 9)).pack(side="left", padx=(4, 0))
        # Phase 2: Vision API で画像から card_id 認識
        self.mercari_seller_vision_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            msel,
            text="Vision で画像から card_id 認識 (= title 取れない時の補強、 1 件 ¥0.15 程度の API コスト)",
            variable=self.mercari_seller_vision_var,
            font=("Meiryo UI", 9)
        ).pack(anchor="w", pady=(4, 0))
        tk.Label(msel,
                 text="※ 例: https://jp.mercari.com/user/profile/623636774  "
                      "出力先 = 中間スプシ seller_<id> タブ (= 自動 create、 タブ単位 dedup)",
                 fg="#666", font=("Meiryo UI", 8)).pack(anchor="w", pady=(4, 0))

        # SNKRDUNK オプション (PSA10 補仕入 URL 投入)
        snk = tk.LabelFrame(parent, text="SNKRDUNK オプション (PSA10 補仕入 URL 投入)",
                            padx=10, pady=8, font=("Meiryo UI", 10))
        snk.pack(fill="x", padx=12, pady=4)
        self.snkrdunk_dry_run_var = tk.BooleanVar(value=False)
        tk.Checkbutton(snk,
                       text="dry-run (= スプシ書込なし、収集 URL を c:/tmp/snkrdunk_dryrun_<ts>.json に出力)",
                       variable=self.snkrdunk_dry_run_var,
                       font=("Meiryo UI", 9)).pack(anchor="w")
        row1 = tk.Frame(snk)
        row1.pack(fill="x", pady=(4, 0))
        tk.Label(row1, text="max-rows (空欄=全件):",
                 font=("Meiryo UI", 9)).pack(side="left")
        self.snkrdunk_max_rows_var = tk.StringVar()
        tk.Entry(row1, textvariable=self.snkrdunk_max_rows_var, width=8,
                 font=("Consolas", 9)).pack(side="left", padx=(4, 16))
        tk.Label(row1, text="target-row (1 行のみ、空欄=全件、例: 266):",
                 font=("Meiryo UI", 9)).pack(side="left")
        self.snkrdunk_target_row_var = tk.StringVar()
        tk.Entry(row1, textvariable=self.snkrdunk_target_row_var, width=8,
                 font=("Consolas", 9)).pack(side="left", padx=4)
        tk.Label(snk,
                 text="※ 出力先スプシ選択 (HIGH/LOW/任意 URL) は SNKRDUNK 補仕入では HIGH 固定。"
                      "1 件あたり 約 60-100 秒 (= Selenium UI 操作 + hydration 待機)。",
                 fg="#666", font=("Meiryo UI", 8)).pack(anchor="w", pady=(4, 0))
        # 抽出くん 補仕入連携 option (= snkrdunk_fav button 用)
        self.snkrdunk_fav_with_aux_var = tk.BooleanVar(value=False)
        tk.Checkbutton(snk,
                       text="SNKRDUNK 抽出 で同 card_id の PSA10 補仕入も併せて取得 "
                            "(= 価格 ≤ 元価格、AC-AG 列に同時投入。1 件あたり +60-100 秒)",
                       variable=self.snkrdunk_fav_with_aux_var,
                       font=("Meiryo UI", 9)).pack(anchor="w", pady=(4, 0))

        # 出力先スプシ
        out = tk.LabelFrame(parent, text="出力先スプシ", padx=10, pady=8, font=("Meiryo UI", 10))
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
        opt = tk.LabelFrame(parent, text="オプション", padx=10, pady=8, font=("Meiryo UI", 10))
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

        # ステータス + ログ は _build_ui 冒頭で side="bottom" で既に確保済

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
        if key == "mercari":
            self._dispatch_mercari()
            return
        if key == "mercari_shops":
            self._dispatch_mercari_shops()
            return
        if key == "workman":
            self._dispatch_workman()
            return
        if key == "amazon":
            self._dispatch_amazon()
            return
        if key == "snkrdunk":
            self._dispatch_snkrdunk()
            return
        if key == "snkrdunk_fav":
            self._dispatch_snkrdunk_favorites()
            return
        if key == "mercari_seller":
            self._dispatch_mercari_seller()
            return
        messagebox.showinfo("未実装", f"{key} は未実装です。")

    def _dispatch_mercari(self) -> None:
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

    def _dispatch_mercari_shops(self) -> None:
        try:
            sheet_id, gid, label = self._resolve_sheet()
        except ValueError as e:
            messagebox.showerror("スプシ URL エラー", str(e))
            return
        if not messagebox.askyesno(
            "確認",
            f"メルカリShops のいいね一覧から URL を収集し、\n"
            f"出力先スプシ「{label}」に追記します。\n\n実行しますか？",
        ):
            return
        threading.Thread(
            target=self._run_mercari_shops_thread,
            args=(sheet_id, gid, label),
            daemon=True,
        ).start()

    def _dispatch_workman(self) -> None:
        # multiline Text widget から URL list を取得
        raw_text = self.workman_urls_text.get("1.0", "end").strip()
        urls = [
            ln.strip() for ln in raw_text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if not urls:
            messagebox.showerror(
                "URL 未入力",
                "ワークマン公式商品 URL を入力してください (改行区切りで複数可)。\n"
                "例: https://workman.jp/shop/g/g2300011882014/",
            )
            return
        # 簡易バリデーション: workman.jp/shop/g/ を含むか
        invalid = [u for u in urls if "workman.jp/shop/g/" not in u]
        if invalid:
            messagebox.showerror(
                "URL 形式エラー",
                f"以下の URL は形式が不正です:\n" + "\n".join(invalid[:5])
                + ("\n..." if len(invalid) > 5 else ""),
            )
            return
        # Phase 2 v2: 出力先は★公式在庫要チェック シート1 固定 (HIGH/LOW 選択は無視)
        if not messagebox.askyesno(
            "確認",
            f"ワークマン公式商品 {len(urls)} 件 を harvest し、\n"
            f"★公式在庫要チェック シート1 に B 列 (title) + F 列 (URL) を追記します。\n\n"
            f"※ 出力先スプシ選択 (HIGH/LOW/任意 URL) は Workman では無視されます。\n\n"
            f"実行しますか？",
        ):
            return
        threading.Thread(
            target=self._run_workman_thread,
            args=(urls,),
            daemon=True,
        ).start()

    def _dispatch_amazon(self) -> None:
        wishlist_url = (self.amazon_url_var.get() or "").strip()
        # ウィッシュリスト URL バリデーション
        if not wishlist_url:
            messagebox.showerror(
                "URL 未入力",
                "Amazon ウィッシュリスト URL を入力してください。\n"
                "例: https://www.amazon.co.jp/hz/wishlist/ls/XXXXXXXXXXXXX",
            )
            return
        try:
            normalized_url = amazon_wishlist.normalize_wishlist_url(wishlist_url)
        except ValueError as e:
            messagebox.showerror("URL 不正", str(e))
            return
        try:
            sheet_id, gid, label = self._resolve_sheet()
        except ValueError as e:
            messagebox.showerror("スプシ URL エラー", str(e))
            return
        if not messagebox.askyesno(
            "確認",
            f"Amazon のウィッシュリストから URL を収集し、\n"
            f"出力先スプシ「{label}」に追記します。\n\n"
            f"対象リスト:\n{normalized_url}\n\n実行しますか？",
        ):
            return
        # 入力 URL を次回起動時のために保存 (実行が確定してから)
        _save_amazon_url(wishlist_url)
        threading.Thread(
            target=self._run_amazon_thread,
            args=(normalized_url, sheet_id, gid, label),
            daemon=True,
        ).start()

    def _dispatch_mercari_seller(self) -> None:
        url = (self.mercari_seller_url_var.get() or "").strip()
        if not url:
            messagebox.showerror(
                "URL 未入力",
                "メルカリセラー URL を入力してください。\n"
                "例: https://jp.mercari.com/user/profile/623636774",
            )
            return
        seller_id = mercari_seller.parse_seller_id(url)
        if not seller_id:
            messagebox.showerror(
                "URL 不正",
                "メルカリセラー URL の形式が不正です。\n"
                "正しい形式: https://jp.mercari.com/user/profile/<id>\n\n"
                "(Shops の URL は Phase 1 では未対応です)"
            )
            return
        # 件数 entry 検証 (= 空/0 で無制限希望 = None 渡し)
        raw_limit = (self.mercari_seller_limit_var.get() or "").strip()
        user_limit: Optional[int] = None
        if raw_limit:
            try:
                v = int(raw_limit)
                if v > 0:
                    user_limit = v
            except ValueError:
                messagebox.showerror(
                    "件数 不正",
                    f"最大抽出件数は 1 以上の整数で指定してください (入力値: {raw_limit!r})\n"
                    f"空欄 / 0 なら ハード CAP ({mercari_seller.HARD_CAP_PER_SESSION}) で打切。",
                )
                return
        effective = mercari_seller.resolve_effective_cap(user_limit)
        if not messagebox.askyesno(
            "確認",
            f"メルカリセラー {seller_id} の出品中商品を最大 {effective} 件まで収集し、\n"
            f"中間スプシ seller_{seller_id} タブに追記します。\n\n"
            f"※ 出力先スプシ選択 (HIGH/LOW/任意 URL) はメルカリセラーでは無視されます。\n"
            f"※ 同 card_id (= OP/ST/EB/P 系) は最安を主、 残りを AC-AG 補に group 化。\n"
            f"※ ハード CAP {mercari_seller.HARD_CAP_PER_SESSION} 件を超えるセラーは複数セッションで取得してください。\n\n"
            f"実行しますか？",
        ):
            return
        threading.Thread(
            target=self._run_mercari_seller_thread,
            args=(seller_id, user_limit),
            daemon=True,
        ).start()

    def _dispatch_snkrdunk_favorites(self) -> None:
        try:
            sheet_id, gid, label = self._resolve_sheet()
        except ValueError as e:
            messagebox.showerror("スプシ URL エラー", str(e))
            return
        if not messagebox.askyesno(
            "確認",
            f"SNKRDUNK のお気に入り商品 URL を収集し、\n"
            f"出力先スプシ「{label}」に追記します。\n\n"
            f"※ SNKRDUNK login 必須 (= 未 login なら error)。初回は\n"
            f"   python -m scrapers.snkrdunk_favorites --login\n"
            f"で手動ログイン後に再実行してください。\n\n"
            f"実行しますか？",
        ):
            return
        threading.Thread(
            target=self._run_snkrdunk_favorites_thread,
            args=(sheet_id, gid, label),
            daemon=True,
        ).start()

    def _dispatch_snkrdunk(self) -> None:
        # オプション値の入力検証 (= max-rows / target-row が数値か)
        max_rows: int | None = None
        target_row: int | None = None
        raw_mr = (self.snkrdunk_max_rows_var.get() or "").strip()
        if raw_mr:
            try:
                max_rows = int(raw_mr)
                if max_rows <= 0:
                    raise ValueError("max-rows は 1 以上の整数")
            except ValueError:
                messagebox.showerror(
                    "max-rows 不正",
                    f"max-rows は 1 以上の整数で指定してください (入力値: {raw_mr!r})\n空欄なら全件処理。",
                )
                return
        raw_tr = (self.snkrdunk_target_row_var.get() or "").strip()
        if raw_tr:
            try:
                target_row = int(raw_tr)
                if target_row <= 1:
                    raise ValueError("target-row は 2 以上の整数 (1=ヘッダー)")
            except ValueError:
                messagebox.showerror(
                    "target-row 不正",
                    f"target-row は 2 以上の整数で指定してください (入力値: {raw_tr!r})\n"
                    "空欄なら全件処理。1 はヘッダー行で対象外。",
                )
                return

        dry_run = self.snkrdunk_dry_run_var.get()
        mode = "dry-run (= 書込なし)" if dry_run else "本投入 (= AC-AG 列書込)"
        scope_parts = []
        if target_row is not None:
            scope_parts.append(f"target-row={target_row} 1 行のみ")
        elif max_rows is not None:
            scope_parts.append(f"先頭 {max_rows} 件")
        else:
            scope_parts.append("HIGH 全行 (OP card_id 抽出可 + 出品済)")
        scope_txt = ", ".join(scope_parts)

        if not messagebox.askyesno(
            "確認",
            f"SNKRDUNK PSA10 補仕入 URL 投入を実行します。\n\n"
            f"モード: {mode}\n"
            f"対象  : {scope_txt}\n"
            f"出力先: HIGH 商品管理シート (= sheet_id 末尾 ..2J10HCjk)\n\n"
            f"※ Selenium 起動、1 件約 60-100 秒。GUI は別 thread で進捗を流します。\n\n"
            f"実行しますか？",
        ):
            return
        threading.Thread(
            target=self._run_snkrdunk_thread,
            args=(max_rows, target_row, dry_run),
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

    def _run_mercari_shops_thread(self, sheet_id: str, gid: int, label: str) -> None:
        self._running = True
        self._set_buttons_state(disabled=True)
        headless = not self.show_browser_var.get()
        fetch_detail = self.fetch_detail_var.get()
        exclude_sold = self.exclude_sold_var.get()

        self._set_status("メルカリShops 収集中...")
        self._log("=== メルカリShops いいね収集 開始 ===")
        self._log(f"  出力先     : {label} (sheet_id={sheet_id[:14]}.., gid={gid})")
        self._log(f"  headless   : {headless}")
        self._log(f"  詳細取得   : {fetch_detail}")
        self._log(f"  SOLD除外   : {exclude_sold}")
        try:
            if fetch_detail:
                def progress(cur, total, msg):
                    self._set_status(f"商品詳細取得中... [{cur}/{total}]")
                    self._log(f"  [{cur}/{total}] {msg}")

                items = mercari_shops_likes.collect_shops_likes_with_details(
                    headless=headless,
                    exclude_sold=exclude_sold,
                    progress_callback=progress,
                )
            else:
                items = mercari_shops_likes.collect_shops_liked_urls(headless=headless)
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

    def _run_workman_thread(self, urls: list[str]) -> None:
        """Phase 2 v2: ★公式在庫要チェック シート1 固定投入、B 列 + F 列のみ."""
        self._running = True
        self._set_buttons_state(disabled=True)

        self._set_status(f"ワークマン {len(urls)} 件取得中...")
        self._log("=== ワークマン公式 harvest 開始 (Phase 2 v2) ===")
        self._log(f"  投入先     : ★公式在庫要チェック シート1 "
                  f"(sheet_id={WORKMAN_OFFICIAL_SHEET_ID[:14]}.., gid=0)")
        self._log(f"  対象 URL   : {len(urls)} 件")
        try:
            def progress(cur, total, url):
                self._set_status(f"取得中... [{cur}/{total}]")
                self._log(f"  [{cur}/{total}] {url}")

            items = workman_official.fetch_products(urls, progress_callback=progress)
            self._log(f"  title 取得成功: {len(items)} / {len(urls)} 件")
            if not items:
                self._set_status("収集 0 件、スプシ書込スキップ")
                messagebox.showwarning(
                    "収集 0 件",
                    "Workman 商品データが 1 件も取得できませんでした。\n"
                    "(title が JSON-LD から取れない URL は fail-closed で skip)"
                )
                return
            self._set_status(f"スプシ書込中... ({len(items)} 件)")
            result = write_to_workman_official_sheet(items)
            self._log(
                f"  書込結果   : appended={result['appended']}, "
                f"skipped_existing={result['skipped_existing']}, "
                f"skipped_invalid={result['skipped_invalid']}, "
                f"input={result['input']}"
            )
            self._set_status(
                f"完了: 新規 {result['appended']} 件 / "
                f"既出 skip {result['skipped_existing']} 件 / "
                f"無効 skip {result['skipped_invalid']} 件"
            )
            self._log("=== 完了 ===")
            messagebox.showinfo(
                "完了",
                f"title 取得 {len(items)} 件 → 新規追加 {result['appended']} 件\n"
                f"(既出 skip {result['skipped_existing']} 件、"
                f"無効 skip {result['skipped_invalid']} 件)"
            )
        except Exception as e:
            self._log(f"!!! エラー: {e}")
            self._set_status(f"失敗: {type(e).__name__}")
            messagebox.showerror("エラー", str(e))
        finally:
            self._running = False
            self._set_buttons_state(disabled=False)

    def _run_amazon_thread(self, wishlist_url: str, sheet_id: str, gid: int, label: str) -> None:
        self._running = True
        self._set_buttons_state(disabled=True)
        headless = not self.show_browser_var.get()
        fetch_detail = self.fetch_detail_var.get()
        # exclude_sold は Amazon では「在庫切れ・取扱中止を除外」の意味で使い回す
        exclude_unavailable = self.exclude_sold_var.get()

        self._set_status("Amazon 収集中...")
        self._log("=== Amazon ウィッシュリスト収集 開始 ===")
        self._log(f"  対象 URL    : {wishlist_url}")
        self._log(f"  出力先     : {label} (sheet_id={sheet_id[:14]}.., gid={gid})")
        self._log(f"  headless   : {headless}")
        self._log(f"  詳細取得   : {fetch_detail}")
        self._log(f"  在庫切れ除外: {exclude_unavailable}")
        try:
            if fetch_detail:
                def progress(cur, total, msg):
                    self._set_status(f"商品詳細取得中... [{cur}/{total}]")
                    self._log(f"  [{cur}/{total}] {msg}")

                items = amazon_wishlist.collect_wishlist_with_details(
                    wishlist_url=wishlist_url,
                    headless=headless,
                    exclude_unavailable=exclude_unavailable,
                    progress_callback=progress,
                )
            else:
                items = amazon_wishlist.collect_wishlist_urls(
                    wishlist_url=wishlist_url,
                    headless=headless,
                )
            self._log(f"  収集完了   : {len(items)} 件")
            self._set_status(f"スプシ書込中... ({len(items)} 件)")
            result = write_to_sheet_amazon(items, spreadsheet_id=sheet_id, gid=gid)
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

    def _run_mercari_seller_thread(
        self,
        seller_id: str,
        user_limit: Optional[int],
    ) -> None:
        """メルカリセラー出品 → 中間スプシ seller_<id> タブに append."""
        self._running = True
        self._set_buttons_state(disabled=True)
        headless = not self.show_browser_var.get()
        exclude_sold = self.exclude_sold_var.get()
        effective_cap = mercari_seller.resolve_effective_cap(user_limit)

        use_vision = self.mercari_seller_vision_var.get()
        self._set_status(f"メルカリセラー {seller_id} 出品収集中...")
        self._log("=== メルカリセラー 抽出 開始 ===")
        self._log(f"  seller_id  : {seller_id}")
        self._log(f"  ユーザー上限: {user_limit if user_limit else '(無制限希望)'}")
        self._log(f"  effective  : {effective_cap} (= min(ユーザー上限, HARD_CAP {mercari_seller.HARD_CAP_PER_SESSION}))")
        self._log(f"  headless   : {headless}")
        self._log(f"  SOLD除外   : {exclude_sold}")
        self._log(f"  Vision 補強: {use_vision} (= 画像から card_id 認識、 title × Vision 合議)")
        self._log(f"  投入先     : 中間スプシ seller_{seller_id} タブ")
        try:
            def progress(cur, total, msg):
                self._set_status(f"商品詳細取得中... [{cur}/{total}]")
                self._log(f"  [{cur}/{total}] {msg}")

            result = mercari_seller.collect_seller_with_details(
                seller_id=seller_id,
                headless=headless,
                user_limit=user_limit,
                exclude_sold=exclude_sold,
                progress_callback=progress,
            )
            items = result["items"]
            self._log(
                f"  収集結果   : 出現 {result['total_seen']} 件 / "
                f"取得 {len(items)} 件 / SOLD skip {result['skipped_sold']} / "
                f"CAP到達 {result['cap_hit']}"
            )
            if result["cap_hit"]:
                self._log(
                    f"  ⚠ ハード CAP {mercari_seller.HARD_CAP_PER_SESSION} 件 到達 = "
                    f"残り未取得 {max(0, result['total_seen'] - effective_cap)} 件、 "
                    f"続きは時間空けて別セッションで取得してください (bot 検出回避)"
                )

            # card_id で group 化 (= 同 card_id 主 + 補、 Vision 補強 任意)
            vision_stats: dict = {}
            if use_vision:
                self._set_status(f"Vision で card_id 認識中... ({len(items)} 件)")
            grouped_rows = mercari_seller.group_items_by_card_id(
                items, use_vision=use_vision, vision_stats=vision_stats,
            )
            aux_rows = sum(1 for r in grouped_rows if r.get("auxiliary_urls"))
            aux_urls = sum(len(r.get("auxiliary_urls") or []) for r in grouped_rows)
            self._log(
                f"  group 化   : {len(items)} listings → {len(grouped_rows)} rows "
                f"(= aux あり {aux_rows} rows, aux URL 計 {aux_urls})"
            )
            if use_vision:
                self._log(
                    f"  Vision 統計: calls={vision_stats.get('vision_calls', 0)} "
                    f"hits={vision_stats.get('vision_hits', 0)} "
                    f"title_vs_vision_disagree={vision_stats.get('title_vs_vision_disagree', 0)}"
                )

            if not grouped_rows:
                self._set_status("収集 0 件、スプシ書込スキップ")
                messagebox.showwarning(
                    "収集 0 件",
                    "メルカリセラー出品が 1 件も取得できませんでした。\n"
                    "(セラー出品ゼロ / 全件 SOLD / DOM 構造変更 を確認してください)"
                )
                return

            self._set_status(f"スプシ書込中... ({len(grouped_rows)} rows)")
            ws_result = append_seller_items(seller_id, grouped_rows)
            self._log(
                f"  書込結果   : tab={ws_result['tab']} "
                f"appended={ws_result['appended']} "
                f"skipped_existing={ws_result['skipped_existing']} "
                f"input={ws_result['input']}"
            )
            self._set_status(
                f"完了: 新規 {ws_result['appended']} rows / 既出 skip {ws_result['skipped_existing']} rows"
            )
            self._log("=== 完了 ===")
            messagebox.showinfo(
                "完了",
                f"メルカリセラー {seller_id}\n\n"
                f"listing 取得: {len(items)} 件 (SOLD skip {result['skipped_sold']})\n"
                f"group 化:    {len(grouped_rows)} rows (aux あり {aux_rows})\n"
                f"スプシ書込:   新規 {ws_result['appended']} / 既出 skip {ws_result['skipped_existing']}\n"
                f"CAP 到達:    {result['cap_hit']}",
            )
        except Exception as e:
            self._log(f"!!! エラー: {e}")
            self._set_status(f"失敗: {type(e).__name__}")
            messagebox.showerror("エラー", str(e))
        finally:
            self._running = False
            self._set_buttons_state(disabled=False)

    def _run_snkrdunk_favorites_thread(self, sheet_id: str, gid: int, label: str) -> None:
        """SNKRDUNK お気に入り → スプシ append (= メルカリ いいねと同等パターン)."""
        self._running = True
        self._set_buttons_state(disabled=True)
        headless = not self.show_browser_var.get()
        fetch_detail = self.fetch_detail_var.get()

        with_aux = self.snkrdunk_fav_with_aux_var.get()
        exclude_sold = self.exclude_sold_var.get()

        self._set_status("SNKRDUNK お気に入り収集中...")
        self._log("=== SNKRDUNK お気に入り収集 開始 ===")
        self._log(f"  出力先     : {label} (sheet_id={sheet_id[:14]}.., gid={gid})")
        self._log(f"  headless   : {headless}")
        self._log(f"  詳細取得   : {fetch_detail}")
        self._log(f"  補仕入連携 : {with_aux} (= 同 card_id PSA10 を AC-AG 列に併せて投入)")
        self._log(f"  SOLD除外   : {exclude_sold} (= API status != 0 を skip、メルカリと同仕様)")
        try:
            if fetch_detail:
                def progress(cur, total, msg):
                    self._set_status(f"商品詳細取得中... [{cur}/{total}]")
                    self._log(f"  [{cur}/{total}] {msg}")

                items = snkrdunk_favorites.collect_favorites_with_details(
                    headless=headless,
                    progress_callback=progress,
                    enable_auxiliary=with_aux,
                    exclude_sold=exclude_sold,
                )
            else:
                urls = snkrdunk_favorites.collect_favorite_urls(headless=headless)
                # 詳細なし時は url だけ持つ item dict を作る
                items = [{"url": u} for u in urls]
            self._log(f"  収集完了   : {len(items)} 件")
            if not items:
                self._set_status("収集 0 件、スプシ書込スキップ")
                messagebox.showwarning(
                    "収集 0 件",
                    "SNKRDUNK お気に入りが 1 件も取れませんでした。\n"
                    "(login 状態 / お気に入り 0 件 / URL pattern 変更 を確認してください)"
                )
                return
            self._set_status(f"スプシ書込中... ({len(items)} 件)")
            result = write_to_sheet(items, spreadsheet_id=sheet_id, gid=gid)
            self._log(
                f"  書込結果   : appended={result['appended']}, "
                f"skipped_existing={result['skipped_existing']}, "
                f"input={result['input']}"
            )
            self._set_status(
                f"完了: 新規 {result['appended']} 件 / 既出 skip {result['skipped_existing']} 件"
            )
            self._log("=== 完了 ===")
            messagebox.showinfo(
                "完了",
                f"収集 {len(items)} 件 → 新規追加 {result['appended']} 件 "
                f"(既出 skip {result['skipped_existing']} 件)"
            )
        except Exception as e:
            self._log(f"!!! エラー: {e}")
            self._set_status(f"失敗: {type(e).__name__}")
            messagebox.showerror("エラー", str(e))
        finally:
            self._running = False
            self._set_buttons_state(disabled=False)

    def _run_snkrdunk_thread(
        self,
        max_rows: int | None,
        target_row: int | None,
        dry_run: bool,
    ) -> None:
        """SNKRDUNK PSA10 補仕入 URL 投入 thread.

        既存 run_harvest_snkrdunk.py の main を踏襲、GUI log/status に流すよう書き換え。
        """
        import json as _json
        import os as _os
        from datetime import datetime as _dt

        self._running = True
        self._set_buttons_state(disabled=True)
        headless = not self.show_browser_var.get()

        self._set_status("SNKRDUNK PSA10 抽出開始...")
        self._log("=== SNKRDUNK PSA10 補仕入 URL 投入 開始 ===")
        self._log(f"  モード     : {'dry-run' if dry_run else '本投入'}")
        self._log(f"  max-rows   : {max_rows if max_rows is not None else '全件'}")
        self._log(f"  target-row : {target_row if target_row is not None else '全件'}")
        self._log(f"  headless   : {headless}")
        self._log(f"  投入先     : HIGH 商品管理シート (= AC-AG 列、dry-run なら書込なし)")

        driver = None
        try:
            # 既存 sheet_writer の列定数を再利用 (= COL_EBAY_ITEM_ID=2, COL_TITLE=3)
            from sheet_writer import COL_EBAY_ITEM_ID, COL_TITLE

            self._set_status("HIGH スプシ全行 fetch 中...")
            sh = open_snkrdunk_sheet(HIGH_SHEET_ID)
            ws = get_snkrdunk_listings_ws(sh, gid=LISTINGS_GID)
            all_values = ws.get_all_values()
            self._log(f"  全行数     : {len(all_values)} (ヘッダー含む)")

            # 対象行選定 (= run_harvest_snkrdunk._select_target_rows と同等)
            targets: list[tuple[int, str, str]] = []
            for idx, row in enumerate(all_values, start=1):
                if idx == 1:
                    continue
                if target_row is not None and idx != target_row:
                    continue
                title = (row[COL_TITLE - 1] if len(row) >= COL_TITLE else "") or ""
                item_id = (row[COL_EBAY_ITEM_ID - 1] if len(row) >= COL_EBAY_ITEM_ID else "") or ""
                title = title.strip()
                item_id = item_id.strip()
                if not item_id or not title:
                    continue
                card_id = snkrdunk_official.extract_op_card_id(title)
                if not card_id:
                    continue
                targets.append((idx, card_id, title))
                if max_rows is not None and len(targets) >= max_rows:
                    break

            self._log(f"  対象行     : {len(targets)} 件")
            if not targets:
                self._set_status("対象 0 件、終了")
                messagebox.showinfo("完了", "対象 0 件で終了しました (= OP card_id 抽出可 + 出品済 行なし)。")
                return

            self._set_status("Selenium 起動中...")
            driver = snkrdunk_official.create_driver(headless=headless)

            results: list[dict] = []
            total_inserted = 0
            for i, (row_idx, card_id, title) in enumerate(targets, start=1):
                self._set_status(f"取得中... [{i}/{len(targets)}] row={row_idx} {card_id}")
                self._log(f"  [{i}/{len(targets)}] row={row_idx} card={card_id!r}")
                self._log(f"           title: {title[:80]}")

                info = snkrdunk_official.find_psa10_urls_for_card(card_id, driver, max_results=5)
                self._log(
                    f"           model_id={info['model_id']!r}, "
                    f"PSA10 candidates={info['psa10_count']}, "
                    f"search_failed={info['search_failed']}"
                )
                for url in info["psa10_urls"]:
                    self._log(f"             → {url}")

                row_result = {
                    "row_index": row_idx,
                    "card_id": card_id,
                    "title": title,
                    "snkrdunk": info,
                    "insertion": None,
                }

                if dry_run:
                    results.append(row_result)
                    continue

                if not info["psa10_urls"]:
                    row_result["insertion"] = {"inserted": 0, "reason": "no PSA10 urls"}
                    results.append(row_result)
                    continue

                row_values = ws.row_values(row_idx)
                ins = insert_aux_urls_for_row(ws, row_idx, row_values, info["psa10_urls"])
                self._log(
                    f"           AC-AG 投入: inserted={ins['inserted']}, "
                    f"skipped_existing={ins['skipped_existing']}, "
                    f"skipped_overflow={ins['skipped_overflow']}"
                )
                for col_letter, url in ins["plans"]:
                    self._log(f"             {col_letter}{row_idx} = {url}")
                row_result["insertion"] = ins
                total_inserted += ins["inserted"]
                results.append(row_result)

            self._log("=== 完了 ===")
            if dry_run:
                ts = _dt.now().strftime("%Y-%m-%dT%H-%M-%S")
                out_dir = r"c:\tmp"
                _os.makedirs(out_dir, exist_ok=True)
                out_path = _os.path.join(out_dir, f"snkrdunk_dryrun_{ts}.json")
                with open(out_path, "w", encoding="utf-8") as f:
                    _json.dump(results, f, ensure_ascii=False, indent=2)
                self._log(f"dry-run 結果 JSON: {out_path}")
                self._set_status(f"dry-run 完了: {len(results)} 行収集 → {out_path}")
                messagebox.showinfo(
                    "完了 (dry-run)",
                    f"dry-run 完了: {len(results)} 行収集\n\nJSON 出力:\n{out_path}",
                )
            else:
                self._set_status(f"完了: スプシ投入 {total_inserted} セル ({len(results)} 行処理)")
                messagebox.showinfo(
                    "完了",
                    f"SNKRDUNK PSA10 投入完了\n\n"
                    f"処理行数: {len(results)}\n"
                    f"投入セル: {total_inserted}",
                )
        except Exception as e:
            self._log(f"!!! エラー: {e}")
            self._set_status(f"失敗: {type(e).__name__}")
            messagebox.showerror("エラー", str(e))
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            self._running = False
            self._set_buttons_state(disabled=False)

    def _set_buttons_state(self, disabled: bool) -> None:
        # active なサービスボタンのみ disable/enable 切替
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
