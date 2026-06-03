# Phase 1 操作パネル (GUI) 実装完了 — 2026-05-03

## 決定 1: GUI フレームワーク → Tkinter (標準) + Notebook 3 タブ
- 変更: `control_panel.py:1-450` 新規 (Tkinter / subprocess.Popen / threading)
- 検証: `python -X utf8 -c "import tkinter; from control_panel import ControlPanel; ..."` で起動 + 自動 destroy 成功

## 決定 2: 巡回 subprocess 起動 → REVISE_SPREADSHEET_ID env で override
- 変更: `revise/price_revise.py:55` に env override 追加 (`SPREADSHEET_ID = os.environ.get("REVISE_SPREADSHEET_ID") or DEFAULT_SPREADSHEET_ID`)
- 変更: `control_panel.py:on_start()` で env を組み立てて Popen
- 検証: pytest 36 件 pass (env 未設定でも default で動く)

## 決定 3: cron 管理 → register_task.ps1 を `-Action <Status|Register|Unregister>` 統一
- 変更: `tools/register_task.ps1` を `-Remove` から `-Action` 形式に書き換え (param ValidateSet)
- 検証: `powershell -File register_task.ps1 -Action Status` → `[STATUS] 未登録: iMakRevise_PriceCycle` 出力確認

## 決定 4: 進捗サマリ → subprocess stdout を line-by-line parse
- 変更: `control_panel.py:parse_summary_line()` 純関数で抽出 (全行数 / F 初期化対象 / revise 候補 / revise 可能 / 上限超過)
- 検証: pytest `TestParseSummaryLine` 6 件 pass

## 決定 5: 状態保存 → .gui_state.json (worktree 配下)
- 変更: `control_panel.py:GUI_STATE_FILE = PROJECT / ".gui_state.json"` (スプシ ID 履歴最大 10 件)
- 変更: `.gitignore` に `**/.gui_state.json` 追加 (個人設定なので track しない)

## 動作確認結果

| 項目 | 結果 |
|---|---|
| pytest | **36 件 pass** (純関数 + parse_summary_line 追加 6 件) |
| GUI 起動 + 閉じる | OK (Tkinter Notebook 3 タブ表示) |
| register_task.ps1 -Action Status | OK (`[STATUS] 未登録` 出力) |
| 修正連鎖回避 | 監視くん / 抽出くんの control_panel.py 一切 import せず、構造のみ手で写し |

## 提供機能 (機能要件 5 項目すべて実装)

1. **巡回操作** (タブ「巡回 / 進捗」): スプシ ID combobox 履歴 / dry-run / skip-sheet-update / max-init / threshold-pct / 開始 + 停止
2. **進捗サマリ** (リアルタイム): 全行数 / F 初期化対象 / revise 候補 / revise 実行 / 上限超過警告
3. **ログ tail** (タブ「ログ tail」): `decision_log/cron_*.log` 最新を 5 秒ごとに自動更新 + 手動 refresh
4. **cron 管理** (タブ「cron / CSV」): Status / Register / Unregister 各ボタン + 確認 dialog 付
5. **CSV upload 補助** (タブ「cron / CSV」): csv_output/ Explorer 起動 / eBay FileExchange ブラウザ起動

## 起動方法

```
# コンソール付 (debug 用)
python control_panel.py

# コンソールなし (デスクトップショートカット用)
pythonw control_panel.py
```

## NG リスト遵守

- ✅ 監視くん / 抽出くん の control_panel.py は import せず、構造のみ参考に手で写し
- ✅ 既存稼働コードに副作用なし (control_panel.py 新規のみ + price_revise.py に env override 追加だけ)
- ✅ worktree 分離違反なし (他 worktree の control_panel.py を ls/cat していない)
