# iMakInventory — 自社在庫監視 + eBay 自動取り下げ

## 🛡️ Worktree 分離ルール (2026-05-01 制定・絶対厳守)

**この worktree (`C:/dev/iMak_inventory/`) は Inventory Claude 専用**。

- ✅ Inventory Claude: ここで作業
- ❌ Catalog Claude / Harvest Claude / その他: **絶対 touch 禁止**
- ❌ 他 worktree (`C:/dev/iMak/` `C:/dev/iMak_harvest/`) への touch も禁止

詳細は `.PROJECT_LOCKED.md` 参照。グローバル `~/.claude/CLAUDE.md` の Worktree 分離
ルールも厳守。違反は cron 自動巡回を破壊する致命行為。

---

トラバホ代替の自社開発プロジェクト。仕入元在庫監視と eBay 自動取り下げを統合運用する。

---

## 立ち上げ背景 (2026-04-29)

- トラバホ (市販ツール) の仕様変更が頻発、運用の安定性に欠ける
- 「軌道に乗り始めた瞬間に仕様変更」 = 市販ツール依存の最大リスク
- 月額サブスク + 仕様変更追従のコストを、自社インフラに置き換える戦略
- iMak の主力 (TCG / G-shock / montbell / Porter) を長期運用するための基盤

## 役割

| やる | やらない |
|---|---|
| 仕入元在庫の自動監視 (メルカリ / Amazon / ラクマ / ヤフオク等) | 出品 CSV 生成 (各 listing project が担当) |
| eBay listing の自動取り下げ (Sell API) | 商品マスター管理 (iMakCatalog が担当) |
| 在庫管理スプシ (101KL6...) との連携 | バイヤー対応 (iMakAdvisor が担当) |
| 通知 (在庫切れ検知 → Slack/Discord/メール) | |
| 監視間隔・スケジュール管理 | |

## 連携プロジェクト

### 必須連携 (機能依存)

| プロジェクト | 連携内容 | 再利用方針 |
|---|---|---|
| **iMakeBayAPI** | eBay Sell API (取り下げ実行) / 認証情報 | 既存 API クライアント import 再利用 |
| **iMakMercari** | メルカリ商品ページスクレイピング | `mercari_to_ebay_csv.py` の URL パース・画像取得関数を import 再利用 (新規実装ゼロ方針) |
| **在庫管理スプシ** (101KL6...) | SKU/FLG 同期、監視結果反映 | gspread 経由 |

### 任意連携 (運用統合)

| プロジェクト | 用途 |
|---|---|
| **iMakCatalog** | 商品識別 (将来 Phase 2 で利用、現状 URL ベース運用で OK) |
| **iMakHQ** | control_panel.py からの起動ボタン化 |
| **iMakAudit** | 監視結果の独立検証 (任意) |

### 既存資産活用方針 (新規実装最小化)

iMakCatalog Phase 3 (G-shock) と同じパターン:
- 既存スクレイピングロジックを **import で再利用**、新規スクレイピング実装は最小限
- メルカリ: iMakMercari の既存関数 (URL parse, 画像取得等)
- Amazon: 新規実装必要 (既存資産なし、PA-API or scrape)
- ラクマ / ヤフオク等: 新規実装必要

### 新規実装が必要な領域

1. **Amazon 在庫スクレイパー** (既存資産なし)
2. **eBay Sell API の取り下げ wrapper** (iMakeBayAPI 経由で薄ラッパー)
3. **監視オーケストレーション** (cron / 並列 / IP ブロック対策)
4. **通知** (Slack/Discord/メール)
5. **スプシ状態同期** (在庫変化 → スプシ FLG 更新)

## ディレクトリ構成

```
iMakInventory/
├── CLAUDE.md                    # このファイル
├── scrapers/                    # サイト別在庫スクレイパー
│   ├── mercari_scraper.py       # メルカリ商品ページ → 売り切れ判定
│   ├── amazon_scraper.py        # Amazon → 在庫判定 (PA-API or scrape)
│   ├── rakuma_scraper.py        # ラクマ
│   └── yahoo_auc_scraper.py     # ヤフオク
├── ebay_actions/                # eBay 自動取り下げ
│   ├── sell_api_client.py       # Sell API ラッパー
│   └── revise_inventory.py      # qty=0 化 / 取り下げ
├── monitor.py                   # 監視オーケストレーション (cron)
├── notifier.py                  # 通知 (Slack/Discord/メール)
└── tests/
```

## Phase 計画

| Phase | 内容 | 期間 |
|---|---|---|
| **0** | 設計フェーズ (構造調査 + 設計案) | 1-2日 |
| **1** | メルカリ在庫スクレイパー (主力商材最多) | 2-3日 |
| **2** | Amazon 在庫スクレイパー | 2-3日 |
| **3** | eBay 自動取り下げ (Sell API) | 3-5日 |
| **4** | ラクマ / ヤフオク / 他サイト追加 | 各 2-3日 |
| **5** | 統合運用 (cron / 通知 / スプシ連携) | 3-5日 |

合計想定: **3-4週間**

## 運用ルール

- 各 scraper は単独実行可能 (offline テスト想定)
- 在庫変化検知時のみ通知 (連続 OK 時はサイレント)
- IP ブロックリスク回避: pacing (sleep) + retry + driver 再起動
- 失敗時は eBay 自動取り下げを発動しない (誤検知防止、Precision 100% 大前提)
- 月額ベースで運用効果測定 (節約時間 / 検知精度 / 誤検知率)

## 注意事項

- グローバル CLAUDE.md「無在庫モデル前提」「出品の正確性原則」を遵守
- スクレイピング規約・レート制限への配慮
- IP ブロック時は即時 sleep + retry (Akamai WAF 経験あり)
- メンテナンス工数を継続的に確保 (HTML 構造変更追従)
