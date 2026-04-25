# iMakHQ — iMak Trading Japan 司令塔

iMak Trading Japan 全プロジェクトを統括する中央拠点。コードは置かない。ここで扱うのは横断的・メタ的な相談や新規構想。

---

## 🛡️ 執行原則 (Step 6: AI協調プロトコル — 2026-04-25 制定)

修正連鎖を断ち切るため、以下を **毎修正前に Claude が自問** すること:

### 3つの呪文（Gemini Round 4 推奨、3AI 全員合意）

1. **「その修正、YAML でできないか？」**
   - ロジック (Python) を汚す前に、`iMakeBayAPI/config/global.yaml` の値追加で済まないか
   - 値が SSOT 経由で読まれているなら、コード変更不要

2. **「この共通化、`if 分岐` を含んでいないか？」**
   - 共通モジュール内に `if category == "TCG"` / `if project == "G-shock"` を書いた瞬間に負債復活
   - プロジェクト固有の差異は **外部から注入されるデータ** として扱う（yaml / 引数）

3. **「Step 6.5 の全テストを回したか？」**
   - TCG の修正でも G-Shock / Mercari / 一番くじ のテストを必須実行
   - pre-commit hook で物理的に強制（commit 拒否される）

### 修正時の指示テンプレ（ユーザー → Claude）

```
変更対象: <ファイルパス>
変更理由: <何を解決するか>
影響範囲: <他に影響しうるモジュール>
追加テスト: <regression を防ぐ test ケース>
触ってはいけない範囲: <既存のロジックで保護したい箇所>
```

### バグ＝テスト追加運用（Step 6 不文律）

- **新しいバグを直す時、必ず1個 pytest を追加する**
- regression test は資産。蓄積すれば修正連鎖は構造的に減る
- テストなしの bugfix commit は pre-commit が拒否（テストが既存だけだと検知できない）

---

## ここで扱うこと

- **新規プロジェクト構想**: 「こんなことできない？」「Pokemon 未鑑定品も売りたい」など、既存プロジェクトに収まらない話
- **横断的リファクタ**: 「TCG と一番くじで重複してるロジックを共通ライブラリ化したい」など複数プロジェクトをまたぐ作業
- **全体管理・進捗確認**: 各プロジェクトの状態（活動中 / 休眠中 / Phase 等）を一覧化、優先順位の相談
- **共通ルールの議論**: グローバル `~/.claude/CLAUDE.md` に追記すべきルールの検討
- **メタ作業**: 売上集計・KPI・全プロジェクト横断の分析

## 各プロジェクトの場所と概要

| プロジェクト | パス | 概要 | 状態 |
|---|---|---|---|
| iMakTCG | `..\iMakTCG` | PSA鑑定TCG → eBay出品自動化 | 稼働中 |
| iMakG-shock | `..\iMakG-shock` | G-SHOCK → eBay出品自動化 | 稼働中 |
| iMakMercari | `..\iMakMercari` | メルカリ仕入れ系（Porter含む） | 稼働中 |
| iMak_ichibankuji | `..\iMak_ichibankuji` | 一番くじ景品 → eBay出品自動化 | 稼働中 |
| iMakeBayAPI | `..\iMakeBayAPI` | eBay API 連携・共通化候補 | - |
| iMakKeywords | `..\iMakKeywords` | キーワード調査用PDF置き場 | リファレンス |
| iMakGU | `..\iMakGU`（未作成） | GU公式 → eBay Multi-Variation 出品 | Phase 1 計画中 |
| iMakAudit | `..\iMakAudit` | 独立実装監査部隊（HQの自己申告を検証） | 稼働中 |

## 作業ルール

- iMakHQは全プロジェクトの司令塔。構想だけでなく実装・リスティング・バイヤー対応も全てここから行う
- 各プロジェクトのコードに変更が必要なら、絶対パスで該当フォルダのファイルを編集する
- 共通化が必要だと判断したものはグローバル `~/.claude/CLAUDE.md` に追記

## セッション開始時の必須読み込み

iMakHQから全プロジェクトを操作するため、セッション開始時に以下を必ず読み込むこと：

1. **修正バックログ**: `~/.claude/projects/.../memory/project_fix_backlog.md`
2. **各プロジェクトのCLAUDE.md**（作業対象のプロジェクトに関連する場合）:
   - `C:\dev\iMak\iMakTCG\CLAUDE.md`
   - `C:\dev\iMak\iMakMercari\CLAUDE.md`
   - `C:\dev\iMak\iMakG-shock\CLAUDE.md`
   - `C:\dev\iMak\iMak_ichibankuji\CLAUDE.md`

## 作業環境（2026-04-25 移行）

- **作業ルート**: `C:\dev\iMak\` （OneDrive 同期外、Git monorepo）
- **バックアップ**: `C:\Users\imax2\iMak_backup_20260425.zip`
- **OneDrive 旧パス**: `c:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\` は当面保持（削除はユーザー判断、Claude が自発的に削除することは禁止）
- **Git**: ローカル master ブランチ運用、ブランチ切換で実験可
- **Pre-commit hook**: `tools/hooks/pre-commit` （pytest 失敗で commit 拒否）

### 移行ステータス
- **物理ファイル配置**: 2026-04-25 完了（`iMak_backup_20260425.zip` で原本保全済）
- **コード参照書換**: 2026-04-25 19:50 完了（5 .py + 2 .bat + settings.json の OneDrive ハードコード除去、grep 0件確認）
- **CLAUDE.md / docs 内のパス記述**: 2026-04-25 19:55 完了
- **実走証跡**: 2026-04-25 20:30 確認済（出品くん起動時パネルに `v2 [C:\dev\iMak]` 表記が表示される＝C:\dev\iMak\ 側 control_panel.py が動作している証拠）。psa_to_csv.py の cwd ログ確認は次回 PSA TCG ボタン押下時に取得予定
