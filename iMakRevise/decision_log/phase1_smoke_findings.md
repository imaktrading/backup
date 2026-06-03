# Phase 1 smoke test 発見事項 (2026-05-03)

## ✅ 動作確認済

- pytest: 21 件 pass (`tests/test_price_revise.py`)
- スプシ読込: 925 行取得成功 (`1RbGaiQxhYDd7s8nqT0jHeh7sQ6FJNCVnVxkEJLFmz9s` sheet1)
- 認証 JSON: `c:/dev/iMak/double-hold-421922-7c0d38d3f73d.json` でフォールバック動作
- 検知ロジック: F+N 揃った行のみ候補化 (fail-closed)、結果 0 件 = 期待通り
- Browse API GetItem: import + path 解決 OK (実呼出は credentials 不足で未完)

## ⚠️ ユーザー判断要請

### 1. F 列が全 925 行で空欄

| 列 | ユーザー仕様 | 実 header | 値あり行 |
|---|---|---|---|
| F (idx 5) | 出品時の価格 (旧) | 「商品価格」 | **0 / 925** |
| N (idx 13) | 現在の仕入価格 (新) | 「仕入れ価格（円）」 | 159 / 925 |
| M (idx 12) | revise フラグ | 「価格上昇有無」 | (未確認) |

→ F に値がない = 比較ベースラインなし = revise 不能。設計判断必要:

  - (a) **出品くん が出品時に F に書き込む** (本元修正、HQ 依頼)
  - (b) **リバイスくん が "F 空欄なら N を F に初期化"** (= 初回 cycle で書き込み、次回から比較)
  - (c) ユーザー手動で過去出品の仕入価格を F に投入

### 2. T 列ヘッダ相違 (Phase 2-4 で問題化)

仕様: T = 出品日 / 実 header: T = 「利益」

→ Phase 1 では未参照のため影響なし。Phase 2-4 着手前に列番号再特定要。

### 3. eBay 認証ファイルが revise worktree にない

`iMakeBayAPI/ebay keys.txt` が revise worktree 内に存在しない。Browse API 実呼出が
できない。原本は他 worktree (= touch 禁止) にあるため、user に手動で revise worktree
の `iMakeBayAPI/ebay keys.txt` に配置してもらう必要あり。

同様に `double-hold-421922-7c0d38d3f73d.json` も理想は revise worktree root に。

## 進め方提案

Phase 1 は (b) **F 自己初期化方式** が修正連鎖最小:

1. F 空 + N 値あり: F=N で初期化 (M クリア、CSV 出力なし)
2. F 値あり + N 値あり + |delta| > 3%: revise 実行 (CSV + M クリア + F=N)
3. F 値あり + N 値あり + |delta| <= 3%: skip
4. F 値あり + N 空: skip (= 監視くん未更新)

確認後、price_revise.py に F 初期化分岐追加 + 認証ファイル配置 +
本格 cron 統合 (Step 4) に進む。
