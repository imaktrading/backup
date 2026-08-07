# iMak Trading Japan — SYSTEM MAP（全貌の地図）

> 「何が何だか分からなくなった」時にまずここを見る。各層・各ツールの役割を1行で。
> 詳細な現在地は `~/.claude/projects/c--dev-iMak/memory/daily_report.md` の最上段。
> 最終更新: 2026-06-07

---

## 0. これは何のシステムか（一文）
**eBay 無在庫販売（drop-shipping）の自動化**。eBay に出品 → 売れたらメルカリ/Amazon等で仕入れて発送。
在庫を持たない。だから指標は Sell-through / 仕入れ可能性 / 同型番リピート性（在庫回転率ではない）。
絶対前提＝**間違った内容で出品しない**（Precision 100% / Recall は諦める。認識できなければ skip）。

---

## 1. 第1層：worktree（誰がどこで作業するか）
5 worktree 分離。各 Claude は自分の worktree 配下のみ作業（他は touch 禁止）。

| 場所 | 担当 | branch | 役割 |
|---|---|---|---|
| `C:/dev/iMak`（本元） | **HQ / Advisor / Catalog** | master 固定 | 司令塔。出品くん制御 + 下記 HQ ツール群 |
| `C:/dev/iMak_catalog` | Catalog Claude | feature/catalog-phase2 | 商品マスターDB の番人 |
| `C:/dev/iMak_inventory` | Inventory Claude | feature/inventory-phase1 | 在庫監視（売れ筋の在庫切れ検知） |
| `C:/dev/iMak_harvest` | Harvest Claude | feature/harvest-phase1 | 公式サイトのスクレイプ |
| `C:/dev/iMak_revise` | Revise Claude | feature/revise-phase1 | 出品の改訂（タイトル/IS リフレッシュ） |
| `C:/dev/iMak_data` | 全員共有 | — | `products.sqlite` ＋ 依頼書 `requests/` |
| `C:/dev/iMak_dedupe` | 重複くん | — | 重複排除 |

**HQ⇄worker のやり取り = 依頼書**: `iMak_data/<worker>/requests/` に markdown を置く（3段階: feasibility→POC→本実装）。
対話中のセッション（HQ or Advisor）が中継ハブを担い、依頼投入＋統合報告する。

---

## 2. 第2層：2つの大きなループ（システムの背骨）

### ループA：新規出品パイプライン（仕入れ元 → eBay）
```
Harvest(公式scrape) → Catalog DB(products.sqlite) ← 全listingが引く唯一の辞書(SSOT)
   → 各商材の出品スクリプト(psa_to_csv 等)が catalog 値を転記
   → check_csv(出品前ゲート: タイトル/価格/送料/カタログ整合を検査)
   → FileExchange CSV を eBay へアップ
```
**カタログ＝辞書**。タイトル①と Item Specifics②は辞書の転記、価格③は V8 計算。
①②の誤り＝辞書(カタログ)の誤り。だから「カタログ品質」ツール群が重要（第4層参照）。

### ループB：既存メンテ PDCA（出した後の改善）
```
Check: listing_funnel(Seller Hubレポート→出品を5状態に分類)
Plan : demand_winners(需要強化) / 各バケツ別ワークリスト
Act  : 取下再出品(relist 3コマンド) / 価格抵抗 / 再仕入れ / 整理
Check戻り: funnel_diff(直した結果が効いたか世代間diff)
```
5状態 = NO_SEARCH(露出無)/NO_CLICK(クリック無)/NO_CONVERT(売れ無)/RESTOCK(在庫切れ&需要有)/CULL(需要無)。

---

## 3. 第3層：商材プロジェクト（何を売るか / C:/dev/iMak 直下）
出品スクリプト本体は各商材フォルダ内。HQ はそれらを統括・呼び出す。

| プロジェクト | 商材 | 状態 |
|---|---|---|
| iMakTCG | PSA鑑定 TCG（Pokemon/One Piece/DBZ/Gundam） | 稼働中 |
| iMakG-shock | G-SHOCK | 稼働中 |
| iMakMercari | メルカリ仕入れ系（Porter 含む） | 稼働中 |
| iMak_ichibankuji | 一番くじ景品 | 稼働中 |
| iMakeBayAPI | eBay API 連携・共通基盤 | 基盤 |
| iMakCatalog | 全商材の商品マスターDB（SSOT） | 稼働中 |
| iMakKeywords | カテゴリ別キーワード PDF（タイトル生成の必読リファレンス） | 参照 |
| iMakAudit | 独立実装監査部隊（HQの自己申告を検証。Claude+Gemini 2段） | 稼働中 |
| iMakAdvisor | 相談・バイヤー対応・壁打ち（コード修正しない） | 稼働中 |

---

## 4. 第4層：HQ ツール索引（iMakHQ/tools/ — 仕事別）

> 現役 38本。役目を終えた単発スクリプト14本は `tools/_archive/` に退避済（履歴保持・可逆）。

### A. カタログ品質（辞書の正しさを機械監査 / read-only）
| ツール | 役割 |
|---|---|
| catalog_audit.py | B層(eBay派生フィールド)を eBay Taxonomy と照合 |
| catalog_set_audit.py | set_name_ebay の内部整合監査（世代/年/total 矛盾検出）+ check_csv ゲート用 helper |
| name_en_audit.py | Pokemon name_en の自己整合監査（多数決で Durant型誤りを検出） |
| catalog_to_sheet.py | products.sqlite をスプシに可視化書出し |
| auto_catalog_add_request.py | missing_models.csv 監視→Catalog への追加依頼を自動投入 |

### B. 既存メンテ PDCA（測る→直す）
| ツール | 役割 |
|---|---|
| listing_funnel.py | Seller Hub 5レポート→出品を5状態に分類（Check の中核） |
| funnel_diff.py | funnel 世代間 diff＝直した結果が効いたか（PDCA を閉じる） |
| demand_winners.py | 需要実証系統で「まだ出してない売れそうな商品」を出す（Plan） |
| noclick_targets.py | NO_CLICK∩watcher有 をタイトル改修候補に |
| price_resistance.py | NO_CONVERT「クリック来るが買われない」を自分の実売と照合 |
| restock_worklist.py | RESTOCK（在庫切れだが需要実証済）の再仕入れワークリスト |
| cull_end.py | CULL（需要皆無）の段階的 出品停止 End CSV |
| existing_maint_dashboard.py | 上記を「既存メンテ」スプシに集約表示 |

### C. 取下再出品（relist 3コマンド + 補助）
| ツール | 役割 |
|---|---|
| relist_from_funnel.py | ①取下げ: RELIST候補を End CSV + 保留リスト化 |
| relist_add_from_pending.py | ②再出品: 保留リスト→カテゴリ別に出品くん呼出→Add CSV |
| relist_writeback.py | ③書戻し: Add結果の新ItemID を管理スプシ B列へ |
| relist_dashboard.py | 取下再出品の進捗ダッシュボード |

### D. 価格/利益（V8 利益計算スプシ ※命名は旧"v6"だが中身 V8）
| ツール | 役割 |
|---|---|
| v6_fetch_costs.py | 4スプシから ItemID→仕入¥ を取得（価格改訂で再利用） |
| v6_generate_revise_xlsx_v2.py | 価格改訂 XLSX 生成（再利用） |
| （スプシ構造構築・検証の単発7本は _archive/ へ退避） | v6_setup_sheet/complete/apply_continuous/rewrite_*・verify_* |

### E. eBay Policy / API
| ツール | 役割 |
|---|---|
| ebay_oauth_consent_url / ebay_oauth_exchange | OAuth トークン取得（期限切れ時に使用） |
| ebay_update_all_policies / ebay_check_policies | 送料/返品ポリシーの一括更新・確認 |
| ebay_rate_limits.py | API レート残量の可視化 |
| （ポリシー新規作成の実験variant・一覧出力5本は _archive/ へ退避） | create_policy_v2/create_shipping/rest_create・generate_policy_xlsx/write_policy_to_sheet |

### F. PSA 検品（出品くん後 hook）
| ツール | 役割 |
|---|---|
| post_psa_review.py | 全カテゴリ cert を HTML viewer で目視確認 |
| post_psa_don_check.py | DON(One Piece) cert 検出→viewer |
| post_no_go_sentinel.py | NO-GO 除外 cert をスプシに赤字 sentinel |

### G. 仕入れ候補
| ツール | 役割 |
|---|---|
| mercari_psa_resource.py | RESTOCK PSA の再仕入れ可否判定 |
| mercari_gshock_resource.py | 撤退寄り G-SHOCK の代替仕入れ先検証 |
| amazon_v8_check.py | NO_CONVERT G-SHOCK の Amazon原価→V8黒字判定 |

### H. レポート/可視化/通知
| ツール | 役割 |
|---|---|
| report_analyzer.py | Seller Hub 4レポートを全観点分析 |
| listing_category_summary.py | US 出品をカテゴリ別サマリー |
| make_*_pptx.py | PDCA 説明パワポ生成 |
| monthly_snapshot_alert.py | 月次 snapshot リマインダー |
| sheet_io.py | スプシ書込みの共有ヘルパ |
| title_keyword_proposal.py | NO_SEARCH のタイトル改修案（Keywords PDF 準拠） |

---

## 5. 横断ルール（迷ったら）
- **出品の正確性が最優先**: ID完全一致のみ・フォールバック禁止・不明は空欄（fail-closed）。
- **カタログ=SSOT**: 出品スクリプトは catalog 値を転記するだけ。カタログ不備は override せず Catalog へ修正依頼。
- **検証してから答える**: 日時/git/ファイル/コードは実機確認（memory やシステム情報を鵜呑みにしない）。
- **作業区切りで commit**: 「保存した」≠「永続化」。git commit して初めて永続化。
- **監査**: 「監査して」と言われたら implementation-auditor（Claude）→ Gemini 二次 の2段必須。
