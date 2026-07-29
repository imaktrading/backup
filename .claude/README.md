# iMakInventory `.claude/` — 権限 deny 運用メモ

`settings.json` は Claude Code の権限設定 (Inventory worktree 限定)。
グローバルの `defaultMode: bypassPermissions` を継承しつつ、**戻せない操作だけ**を
deny で塞ぐ運用。

## deny に入れているもの

| pattern | 理由 |
|---|---|
| `Bash(git push --force*)` / `Bash(git push -f*)` | 上流破壊。原則 push しない worktree 運用 |
| `Bash(git reset --hard*)` | uncommitted 破壊、事故履歴多数 |
| `Bash(rm -rf *)` / `Bash(rm -fr *)` | 一般シェル破壊 |
| `Bash(*_clear_sku_sheet.py*)` | SKU 詳細シートを header 残して全行 clear する 1 回限定初期化ツール |

**HQ (`iMakHQ`) の deny 例からは、Inventory に存在しないファイル名 pattern**
(`*cull_end.py*` / `*relist_*.py*` / `*gshock_revise_descriptions.py*` /
`*ebay_update_all_policies.py*` / `*fix_de_speedpak_shipping.py*`) は **意図的に除外**
してある。列挙しても該当ゼロで一覧が形骸化するため。追加が必要になった時点で拡張する。

## deny に入れて **いない** eBay 書込系 (cron 本業)

これらは cron で無人実行される **本業**。deny すると 1 日 13 回の巡回が止まり
在庫切れ品が残る → 買われる → キャンセル → Defect Rate → 永久 BAN。

- `iMakInventory/ebay_actions/trading_api_client.py` (低レイヤ)
- `iMakInventory/ebay_actions/trading_api_uploader.py` (bulk 実行)
- `iMakInventory/ebay_actions/revise_csv_generator.py` (qty=0 CSV)
- `iMakInventory/run_cycle.py` (ReviseInventoryStatus)
- `iMakeBayAPI/inventory_monitor/audit_and_heal.py` (日次 heal)
- `iMakeBayAPI/inventory_monitor/auto_qty_zero.py`
- `iMakeBayAPI/inventory_monitor/ebay_qty_sync.py`
- `iMakeBayAPI/inventory_monitor/revise_qty_csv_generator.py`

「手動運用でも使われる」グレー層 (`tools/release_holdouts.py --execute` /
`tools/supervised_backup_drain.py --execute` / `tools/drain_stale_holdouts.py --execute`)
も **日常運用の一部** なので deny 見送り。誤爆防止は `--dry-run` 先行運用で担保。

## `_clear_sku_sheet.py` が必要になった時

1 回限定の初期化ツールなので通常は封じたままで OK。もし必要になった場合:

1. 対話 (headed) Claude セッションを開く
2. この `settings.json` の deny 配列から `Bash(*_clear_sku_sheet.py*)` の行を **一時的に削除**
3. 実行 → 完了後に deny を **必ず戻す** (commit しなくても次セッションで戻す)

これは "誰も回せない" 状態にならないための脱出ハッチ。実装者に直接手を動かして
もらう前提の手順。

## この設定が効いていることを確認する方法

Claude Code は settings を **セッション起動時に読む**。この設定は新規セッションから
効く (書換直後の同一セッションでは効かない)。

対話セッションで:
```
$ git push --force
```
を叩いて deny 発火 (permission error) を確認する。
