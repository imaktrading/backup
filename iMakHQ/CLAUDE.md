# iMakHQ — iMak Trading Japan 司令塔

iMak Trading Japan 全プロジェクトを統括する中央拠点。コードは置かない。ここで扱うのは横断的・メタ的な相談や新規構想。

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
   - `c:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\iMakTCG\CLAUDE.md`
   - `c:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\iMakMercari\CLAUDE.md`
   - `c:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\iMakG-shock\CLAUDE.md`
   - `c:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\iMak_ichibankuji\CLAUDE.md`
