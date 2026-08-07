@echo off
REM ====================================================================
REM PSA Cloudflare 突破用 chrome profile 手動 setup
REM
REM 用途: psa_to_csv が PSA Cloudflare bot 検出で失敗する時、
REM       user が 1 回手動で Cloudflare チェック クリア → cookie 保存。
REM       以降 24-72h は psa_to_csv が自動 scrape 通る想定。
REM
REM 手順:
REM   1. このバッチをダブルクリック
REM   2. Chrome が PSA cert ページを開く
REM   3. Cloudflare の「I'm not a robot」 チェックボックスがあれば click
REM   4. PSA cert 詳細ページ (= グレード等) が見えれば成功
REM   5. Chrome を閉じる (= cookie が profile に保存される)
REM   6. psa_to_csv を再走 → Cloudflare 突破できるか確認
REM
REM 再実行タイミング: psa_to_csv で再び Cloudflare 失敗が出たら (= 24-72h 後想定)
REM ====================================================================

set PROFILE_DIR=C:\Users\imax2\local_data\iMakHQ\chrome_profile_psa
set TEST_CERT_URL=https://www.psacard.com/cert/89631139

if not exist "%PROFILE_DIR%" mkdir "%PROFILE_DIR%"

start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="%PROFILE_DIR%" --no-first-run --no-default-browser-check --disable-features=ChromeWhatsNewUI "%TEST_CERT_URL%"

echo.
echo Chrome 起動済。 PSA cert ページで Cloudflare チェック クリア後、 Chrome を閉じてください。
echo cookie が以下に保存されます: %PROFILE_DIR%
echo.
pause
