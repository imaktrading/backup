"""iMak Trading Japan - 月次 Seller Hub snapshot リマインダー通知.

Windows タスクスケジューラから毎月 1 日 04:00 に呼ばれ、デスクトップに
toast 通知を表示する。ユーザーが通知を見て手動で以下を実行:

  1. eBay Seller Hub > Reports > Unsold listings CSV を DL
     → C:\\dev\\iMak_data\\seller_hub\\official_unsold_YYYYMMDD.csv に rename 保存
  2. tools/monthly_seller_hub_snapshot.bat を実行 (scrape + View data 取得)

自動実行ではなく通知のみにする理由:
  - cookie 切れ等の失敗を人間が認識できる
  - 公式 CSV DL とセットで人手介入の方が確実
  - Profile lock 衝突回避 (Inventory cron 並走考慮)

依存: pip install win10toast
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
    "eBay データ 90 日消失防止のリマインダー\n"
    "1. Seller Hub > Reports > Unsold CSV を DL\n"
    "2. monthly_seller_hub_snapshot.bat を実行"
)


def show_toast(title: str, message: str, duration: int = 30) -> bool:
    """Windows toast 通知を表示. win10toast が無ければ msg.exe にフォールバック."""
    # win10toast を優先 (Python 製、確実)
    try:
        from win10toast import ToastNotifier  # type: ignore
        toaster = ToastNotifier()
        toaster.show_toast(title, message, duration=duration, threaded=False)
        return True
    except ImportError:
        pass

    # フォールバック: PowerShell の標準通知 (Windows.UI.Notifications)
    import subprocess
    ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.Visible = $true
$notify.ShowBalloonTip({duration * 1000}, "{title}", "{message}", [System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Seconds {duration}
'''
    try:
        subprocess.Popen([
            "powershell", "-NoProfile", "-Command", ps_script
        ], creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception as e:
        print(f"[ERROR] 通知失敗: {e}")
        return False


def main() -> int:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[INFO] {timestamp} - 月次 Seller Hub snapshot リマインダー通知発火")
    ok = show_toast(TITLE, MESSAGE)
    print("[OK] 通知表示成功" if ok else "[WARN] 通知表示失敗")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
