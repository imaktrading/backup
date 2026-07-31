# 2026-07-30 リバイスくん `.claude/settings.json` の deny 設定を追加

- 依頼書: `iMak_data/revise/requests/2026-07-29_permission_deny_for_irreversible_ops.md`
- 回答書 (正式): `..._response.md` (Advisor GO / IMPLEMENT-GO)

## 追加した deny (`.claude/settings.json`)

`defaultMode: bypassPermissions` を明示指定した上で、以下を deny:

| deny パターン | 目的 |
|---|---|
| `Bash(*revise/variation_upload.py*)` / `*revise\variation_upload.py*` | FileExchange 直 UP バイパスを止める (Defect Rate 直撃防止) |
| `Bash(*revise/ebay_trading_api.py*)` / `*revise\ebay_trading_api.py*` | Trading API 直叩き封じ |
| `Bash(git push --force*)` / `git push -f*` / `git push --force-with-lease*` | 事故時の巻き戻し不能を防ぐ |
| `Bash(git reset --hard*)` | working tree 破壊防止 |
| `Bash(rm -rf *)` / `rm -fr *` | 汎用の破壊予防 |

## cron / 本業への影響なし (実測)

- `pythonw.exe ... run_daily.py` (毎日 04:30 の `iMakRevise_DailyAutoRevise`) は
  `variation_upload` を **Python import** で呼ぶだけで、Bash cmdline に
  `variation_upload.py` の文字列は現れない → deny に一致しない
- 実測: `python -m revise.run_daily --dry-run` は deny に引っかからず起動する
- 実測: `python revise/variation_upload.py --help` は deny で拒否される
- 実測: `git push --force --dry-run <fake-remote> main` は deny で拒否される

## 回帰テスト

`iMakRevise/tests/test_claude_settings_deny.py` を新設 (34 pass / 1 skip):
- settings.json の妥当性 + `defaultMode` の明示指定
- 危険コマンド 14 種が deny に一致 (fnmatch)
- 本業コマンド 17 種 (run_daily / send_reminder / price_revise / control_panel /
  通常 git push / git reset / rm -f 等) が deny に一致しないことを固定
- `run_daily.py` が `from revise.variation_upload import ...` を保持している
  ことを固定 (import 経由での deny 無効化前提を守る)

## `.gitignore` との関係

- 依頼書と回答書 draft は「リバイスくんの `.gitignore` に `.claude/` は無い」と
  記述されていたが、実測では `**/.claude/` が 107 行目に存在
- 回答書は commit して恒久化する方針。今回は `git add -f` で強制追跡し
  commit することでこの方針を満たす
- (`.gitignore` の書換えは範囲外として本回では見送り)
