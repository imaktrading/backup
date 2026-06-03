# Phase 1 (価格 revise) 実装完了 — 2026-05-03

## 決定事項 (3 点セット形式)

### 決定 1: F 列空欄問題 → リバイスくん側で「F=N」初期化
- 変更: `revise/price_revise.py:detect_init_targets()` 新規 (l. 175-200 付近)
- 変更: `revise/price_revise.py:apply_init_targets()` 新規
- 変更: `run_price_revise()` に init 分岐追加
- 検証: pytest 30 件 pass / 実 Sheet row2 で F=N=4660 書込確認

### 決定 2: 認証ファイル → 絶対 path 直書き + env override
- 変更: `revise/price_revise.py` `DEFAULT_GOOGLE_CREDS_PATH = r"C:/dev/iMak/double-hold-421922-7c0d38d3f73d.json"` + `GOOGLE_CREDS_PATH` env var
- 変更: `revise/ebay_browse_price.py` `DEFAULT_EBAY_KEYS_PATH = r"C:/dev/iMak/iMakeBayAPI/ebay keys.txt"` + `EBAY_KEYS_PATH` env var
- 検証: Browse API 単体実呼出 listing 358022202286 → $66.99 取得成功 / Sheet API 925 行読込成功

### 決定 3: T 列再特定 → Phase 2 着手前に実シート確認
- 変更: 未実装 (Phase 2 タスク)
- 検証: 現 header [19] T='利益' (出品日でない) を inspect_sheet.py で目視確認

### 決定 4: cron トリガー → 監視くん +30min offset
- 変更: `tools/run_cycle.ps1` 新規 (1 cycle 実行 wrapper)
- 変更: `tools/register_task.ps1` 新規 (タスクスケジューラ登録)
- 検証: 未登録 (ユーザー実行待ち、register_task.ps1 でいつでも登録可)

## 動作確認結果

| 項目 | 結果 |
|---|---|
| pytest | **30 件 pass** (純関数テスト + init/revise 排他性) |
| Sheet API 認証 + 読込 | OK (925 行) |
| F 初期化対象抽出 | 159 件 (F 空 + N 値あり) |
| revise 候補抽出 | 0 件 (F 全空 = 比較不能、初回 cycle 後に出現する想定) |
| Browse API GetItem | OK ($66.99 取得 / listing 358022202286) |
| 実 Sheet 1 件 init 書込 | OK (row2 F=4660 反映確認) |

## 修正連鎖回避ステータス

| 連携先 | 修正の有無 |
|---|---|
| 監視くん (iMak_inventory) | 一切修正なし |
| 出品くん (iMak/listing_common) | 一切修正なし (import すらしない、ratio 計算で完結) |
| iMakeBayAPI/check_csv_core.py | 一切修正なし (`get_oauth_token` のみ import) |
| iMakeBayAPI/ebay_sku_fetcher.py | 一切修正なし (load_ebay_keys path 衝突回避のため自前実装) |

## 想定運用フロー

```
監視くん cycle (4h: 00, 04, 08, 12, 16, 20)
  └─ N 列更新

リバイスくん cycle (+30min: 00:30, 04:30, 08:30, 12:30, 16:30, 20:30)
  ├─ F 空 + N 値あり: F=N で初期化 (= ベースライン作成、CSV なし)
  └─ F+N 値あり + |delta|>3%: Browse API → 新 USD = 現 USD × N/F → revise CSV
       └─ CSV を eBay FileExchange 手動 upload (or 将来 Sell Feed 自動化)
       └─ upload 完了後、M クリア + F=N 上書き (= 無限ループ防止)
```

初回運用イメージ:
- cycle #1: 159 件で F=N 初期化 (revise 0 件)
- cycle #2 以降: N が変動した行のみ revise 対象に。50 件/cycle 上限あり。

## 残事項 (Phase 1)

- [ ] `tools/register_task.ps1` 実行 (ユーザー側でタスクスケジューラに登録)
- [ ] eBay FileExchange CSV upload 経路 (現状: csv_output/ 出力のみ。手動 upload を想定)
  - 自動化が必要なら別途 sell_feed_uploader 連携 (= iMakHQ 経由)

## ファイル一覧

```
iMakRevise/
├── CLAUDE.md (既存)
├── revise/
│   ├── __init__.py
│   ├── price_revise.py        # 主実装
│   └── ebay_browse_price.py   # Browse API 薄 wrapper (修正連鎖回避用)
├── run_revise.py              # CLI entry
├── tools/
│   ├── inspect_sheet.py       # スプシ確認用
│   ├── run_cycle.ps1          # cron 1 cycle wrapper
│   └── register_task.ps1      # タスクスケジューラ登録
├── tests/
│   ├── __init__.py
│   └── test_price_revise.py   # pytest 30 件
├── csv_output/                # revise CSV 出力先
└── decision_log/              # cron ログ + 決定記録
    ├── phase1_smoke_findings.md
    └── phase1_complete.md (this)
```
