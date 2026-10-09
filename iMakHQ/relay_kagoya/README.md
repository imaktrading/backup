# KAGOYA 中継の窓 (RELAY) の控え — 2026-10-09 新生ブラボー

KAGOYA で動くプログラムの呼び鈴を、家のブラボーへ渡す窓。KAGOYA で起動した短い Claude からは家の窓が見えないため
(同じ PC の窓には届く・普通の窓からは別の PC にも届く)、この窓を挟む。

KAGOYA での置き場 (作り直す時はここから写す):
- `C:\dev\iMakRelay\CLAUDE.md` ← CLAUDE.md
- `C:\dev\iMakRelay\.claude\settings.json` ← settings.json (model haiku・ListAgents / SendMessage を許可)
- `C:\Users\Administrator\Desktop\Relay.bat` ← Relay.bat (Remote Control 名 RELAY)
- `~/.claude.json` の projects に `C:/dev/iMakRelay` を hasTrustDialogAccepted: true (起動時の確認で止まらないように)

起動: KAGOYA の画面で Relay.bat をダブルクリック (家からは予約タスク iMak_Claude_RELAY を /it で走らせる)。
★KAGOYA を再起動したら、もう一度起動が要る。
★2026-10-09 の初回試験で、中継が本文の「対応不要」を読んで転送しなかった → 「中身が何でも必ず転送」に強めて解決。
