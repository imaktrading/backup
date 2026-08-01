@echo off
title Window ALPHA jisou ON
echo.
echo  ============================================================
echo   窓口 ALPHA の自走を ON にします
echo  ============================================================
echo.
echo   5分ごとに、残務を「1件だけ」自動で片付けます。
echo   ・残務が無い時は agent を立てずに終わるので、空振りのコストはゼロ
echo   ・他の窓口が持っている件、担当が別の件には手を出しません
echo   ・eBay書込 / CSV入稿 / スプシ一括書換 / 出品くん本体 は禁止済み
echo   ・止めたくなったら 自走OFF_ALPHA.bat をダブルクリック
echo.
echo  ------------------------------------------------------------
echo   まず「今なら何を取るか」だけ見ます (まだ何もしません)
echo  ------------------------------------------------------------
echo.
python "C:\dev\iMak\iMakHQ\tools\desk_autorun.py" --who ALPHA --dry-run
echo.
echo  ------------------------------------------------------------
echo.
choice /c YN /m "これで ON にしますか (Y=する / N=やめる)"
if errorlevel 2 goto cancel

powershell -NoProfile -ExecutionPolicy Bypass -File "C:\dev\iMak\iMakHQ\tools\desk_autorun_register.ps1"
if errorlevel 1 goto failed
echo.
echo   [OK] ON にしました。5分以内に最初の1件を取りにいきます。
echo        動いたかは iMakHQ\review_logs\desk_*.log で見られます。
echo.
pause
exit /b 0

:cancel
echo.
echo   やめました。何も変更していません。
echo.
pause
exit /b 0

:failed
echo.
echo   [NG] 登録に失敗しました。この画面の文字をそのまま Claude に貼ってください。
echo.
pause
exit /b 1
