# iMakHQ — iMak Trading Japan 司令塔

## 🔀 1丁目1番地 — カタログ絡みの判定手順

**全文はグローバル `~/.claude/CLAUDE.md` の同名節が正** (常時読み込まれる)。
判定は ①カタログのデータ / ②出品くんの引き方 の2択で、判定を書かずに個別修正を始めない。
経緯: `memory/catalog_vs_lookup_triage.md`

### 依頼書で外してはいけない点 (グローバルと同じ・片方だけ直すと事故が再発する)

- ★**窓口から出す質問に `_question` / `_draft` を付けてはいけない**。プレーンな依頼名
  (`YYYY-MM-DD_<topic>.md`) にする。`worktree_board.DRAFT_SUFFIXES` がこれらを
  「担当が書いた下書き = 窓口レビュー待ち」と解釈し、**相手に配られない**
  (2026-08-03 の catalog 質問が4日間届かず、その間 重複が4日連続で入稿CSVに載った)
- ★`_question` は **担当 → 窓口の差し戻し**にだけ使う。既知に疑いがあるなら答え直さず
  `_question.md` で指摘して止める
- ★窓口が実装させたい時は `_response.md` の本文に **`[IMPLEMENT-GO]`** を1行入れる。
  日本語で「実装 GO」と書いても実装キューに入らない
- 依頼書は **「既に判明していること (再調査するな)」と「聞きたいこと (未回答のみ)」を分ける**

## 📍「現在地は?」と聞かれたら — **作文しない**

```
python iMakHQ/tools/status_now.py
```

**この出力が現在地。そのまま示す。** 補足は後ろに足してよいが、出力自体は書き換えない。
(2026-08-01: 同じ問いに窓口ごとに違う答えが返ったため、定義をコマンドに固定した)

## 🎫 「残務やって」と言われたら — **claim を取ってから着手する**

```
python iMakHQ/tools/claim.py next
```

**取れた1件だけをやる。** 取れなかった件は他の窓口が持っているので触らない。
4窓口は同じ worktree / 同じ daily_report を見ているため、claim が無いと
**全員が同じ1件目に着手する**。

## 📋「残務一覧を出して」と言われたら — **作文しない**

```
python iMakHQ/tools/claim.py list
```

**この出力が残務一覧。そのまま示す。** 補足は後ろに足してよいが、出力自体は書き換えない。
memory や daily_report から自分で組み立てると、窓口ごとに違う一覧が出る
(2026-08-01 に「現在地」で実際に起きた事故と同型)。

- 一覧: `python iMakHQ/tools/claim.py list` — **№付き**で出る
- **番号で指示される**: 「4番やって」= `python iMakHQ/tools/claim.py take 4`。
  番号は**一度振ったら変わらない**(閉じても欠番のまま)ので、4窓口とも同じ番号を見ている
- 完了: `python iMakHQ/tools/claim.py done <ID> --note "..."`
- 着手しないなら返す: `python iMakHQ/tools/claim.py release <ID>`
- 残務に気づいたら足す: `python iMakHQ/tools/claim.py add "<件名>" --priority 3 --detail "..."`

(2026-08-01: 「着手前に daily_report で名乗る」は口約束で、board も status_now も
『着手』を読んでいなかった。取り合いは仕組みで防ぐ)

---

## 🛡️ Worktree 分離ルール (2026-05-01 制定・絶対厳守)

**HQ は元 monorepo (`C:/dev/iMak/`) 内に配置**。Catalog Claude と同じ worktree。

- ✅ HQ Claude (使う場合) / Catalog Claude / Advisor: ここで作業
- ❌ Inventory Claude / Harvest Claude: **絶対 touch 禁止**
- ❌ 他 worktree (`C:/dev/iMak_inventory/` `C:/dev/iMak_harvest/`) への touch も禁止

詳細は `C:/dev/iMak/.PROJECT_LOCKED.md` 参照。グローバル `~/.claude/CLAUDE.md` の
Worktree 分離ルールも厳守。

## 📋 セッション運用 (2026-08-15 実態に更新)

**HQ セッションは毎日立ち上げる**。ここが出品くん (control_panel.py / 出品くん.vbs) を
回す担当で、生成・監査・入稿・補URL・カタログ依頼まで見る。
役割の詳細は下の「セッションの役割」節を参照。

★旧記述 (2026-05-01「実運用では HQ セッションは立ち上げない / Advisor が兼任」) は
  実態と逆。2026-06-21 に HQ=出品専任 と分担した以降ずっと HQ が回している。

---

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
| iMakCatalog | `..\iMakCatalog` | 全カテゴリ商品マスターDB（公式DB集約・listing scriptが共通参照） | Phase 0 完了（2026-04-26） |
| iMakAdvisor | `..\iMakAdvisor` | 相談相手・バイヤー対応・雑談・アイディア壁打ち（コード修正はしない） | 2026-04-26 開設 |

## セッションの役割 (2026-08-15 実態に更新)

窓口は4つ。**HQ だけ役割が違い、ADV / ALPHA / BRAVO は同列**。

- **HQ (ここ)** = **出品くん担当**。生成・監査・入稿・補URL・カタログ依頼まで、出品を回す一切
- **ADV / ALPHA / BRAVO** = 同列の窓口。worktree 間の調整・調査・相談・横断インフラ・
  バイヤー対応。**互いに役割の区別は無い**ので、空いている窓口が拾う

同列の3窓口は**同じ worktree・同じ daily_report・同じ残務ボード**を見ている。
放っておくと全員が同じ1件目に着手するので、着手前に必ず claim を取る:

```
python iMakHQ/tools/claim.py next     # 最優先を1件だけ取る
python iMakHQ/tools/claim.py take 4   # 番号で指定
```

全窓口とも全プロジェクトを把握している前提 (セッション開始時に全 CLAUDE.md 読込)。

★旧記述 (2026-04-26「HQ=実行屋 / Advisor=相談相手」「実運用では HQ セッションを
  立ち上げない」) は**実態と逆**だったので置き換えた。実際は HQ が毎日の出品を回している。

## 作業ルール

- iMakHQは全プロジェクトの司令塔。構想だけでなく実装・リスティング・バイヤー対応も全てここから行う
- 各プロジェクトのコードに変更が必要なら、絶対パスで該当フォルダのファイルを編集する
- 共通化が必要だと判断したものはグローバル `~/.claude/CLAUDE.md` に追記

## セッション開始時の必須読み込み

- **修正バックログ**: `~/.claude/projects/.../memory/project_fix_backlog.md`
- 各プロジェクトの CLAUDE.md 一覧はグローバル `~/.claude/CLAUDE.md` の同名節を参照

## 作業環境（2026-04-25 移行）

- **作業ルート**: `C:\dev\iMak\` （OneDrive 同期外、Git monorepo）
- **バックアップ**: `C:\Users\imax2\iMak_backup_20260425.zip`
- **OneDrive 旧パス**: `c:\Users\imax2\OneDrive\デスクトップ\iMak_workspace\` は当面保持（削除はユーザー判断、Claude が自発的に削除することは禁止）
- **Git**: ローカル master ブランチ運用、ブランチ切換で実験可
- **Pre-commit hook**: `tools/hooks/pre-commit` （pytest 失敗で commit 拒否）
