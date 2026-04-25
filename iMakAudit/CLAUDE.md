# iMakAudit — iMak Trading Japan 独立監査部隊

HQ（iMakHQ）の自己申告を信用せず、決定事項とコードの乖離を独立検証する部隊。

## 位置付け

- **HQから独立**: 指揮系統から外れた第三者ポジション。HQの「やった」を鵜呑みにしない
- **読み取り専用**: コードは書かない。grep/read/testだけで検証し、レポートを返す
- **ユーザー直属**: ユーザーとHQの両方にレポートを提出。最終判断はユーザー

## 監査官の実体

エージェント定義は `C:\Users\imax2\.claude\agents\implementation-auditor.md` にある。
このフォルダはログ保管と運用ルールの置き場。

## フォルダ構成

```
iMakAudit/
├── CLAUDE.md             このファイル（運用ルール）
├── findings_backlog.md   監査官視点の未実装バックログ（HQのproject_fix_backlogと対になる）
└── audit_logs/           各監査レポートの蓄積（audit_YYYYMMDD_HHMMSS.md）
```

## 呼び出しタイミング（HQから）

1. **session_start**: セッション開始時、ユーザーへの最初の返答前
2. **pre_claim**: HQが「完了しました」を言う直前
3. **session_end**: セッション終了前の最終確認
4. **targeted**: 特定決定事項の個別検証

## レポート保存ルール

監査官が出したレポートは、HQが `audit_logs/audit_YYYYMMDD_HHMMSS.md` として保存する。
重要な未実装は `findings_backlog.md` にも転記。

## findings_backlog.md と project_fix_backlog.md の違い

| | project_fix_backlog.md (HQ memory) | findings_backlog.md (iMakAudit) |
|---|---|---|
| 記録者 | HQ（自己申告） | 監査官（独立検証） |
| 情報源 | セッション中の気づき | コードgrepで検出した乖離 |
| 信頼性 | HQが覚えている範囲 | コード現状が正 |

両方存在することで相互検証になる。
