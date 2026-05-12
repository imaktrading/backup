"""iMak Trading Japan - 月次 Seller Hub snapshot リマインダー通知.

Windows タスクスケジューラから毎月 1 日 04:00 に呼ばれ、デスクトップに
modal メッセージボックスを表示する (OK 押すまで永続)。

通知方式: Tkinter MessageBox (modal)
  - 朝 PC 触った瞬間に必ず気付く
  - OK 押すまで画面中央に表示
  - Python 標準 (追加 install 不要)

ユーザーが OK を押した後、以下を手動実行:
  1. eBay Seller Hub > Reports > Unsold listings CSV を DL
     → C:\\dev\\iMak_data\\seller_hub\\official_unsold_YYYYMMDD.csv に rename 保存
  2. tools/monthly_seller_hub_snapshot.bat を実行 (scrape + View data 取得)
"""
from __future__ import annotations

import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TITLE = "📊 iMak Seller Hub 月次 snapshot"
MESSAGE = (
    "eBay データ 90 日消失防止のリマインダーです。\n\n"
    "以下を順番に実行してください:\n\n"
    "  1. Seller Hub > Reports > Unsold CSV をダウンロード\n"
    "     https://www.ebay.com/sh/reports/downloads\n"
    "     → iMak_data/seller_hub/ にリネーム保存\n\n"
    "  2. tools/monthly_seller_hub_snapshot.bat を実行\n"
    "     (Active/Ended 全件 scrape、約 10 分)\n\n"
    "OK を押すと閉じます。"
)


def show_modal_alert(title: str, message: str) -> bool:
    """Tkinter MessageBox で modal 通知. OK 押すまで永続."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()  # メインウィンドウ隠す
        root.attributes("-topmost", True)  # 最前面固定
        messagebox.showinfo(title, message, parent=root)
        root.destroy()
        return True
    except Exception as e:
        print(f"[ERROR] Tkinter messagebox 失敗: {e}")
        # フォールバック: PowerShell MessageBox
        try:
            import subprocess
            ps = (
                f'Add-Type -AssemblyName PresentationFramework;'
                f'[System.Windows.MessageBox]::Show('
                f'"{message}", "{title}", "OK", "Information")'
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            return True
        except Exception as e2:
            print(f"[ERROR] PowerShell MessageBox も失敗: {e2}")
            return False


def main() -> int:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[INFO] {timestamp} - 月次 Seller Hub snapshot リマインダー発火")
    ok = show_modal_alert(TITLE, MESSAGE)
    print("[OK] modal 通知表示完了" if ok else "[WARN] 通知表示失敗")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
