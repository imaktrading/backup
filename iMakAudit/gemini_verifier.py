#!/usr/bin/env python3
"""
iMakAudit - Gemini Verifier
Claude監査官レポートの二次監査をGemini（別ベンダー）で行う。

使い方:
  python gemini_verifier.py <audit_report.md>
  または標準入力からレポートを流し込む:
  echo "..." | python gemini_verifier.py

出力:
  verified.md  — Gemini判定を付記した検証済みレポート
  disputed.md  — Claude監査官とGeminiで結論不一致の項目（ユーザー裁定待ち）
"""
import os
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPT_DIR = Path(__file__).resolve().parent
KEY_FILE = SCRIPT_DIR / "gemini_key.txt"
LOGS_DIR = SCRIPT_DIR / "audit_logs"
LOGS_DIR.mkdir(exist_ok=True)

MODEL = "gemini-2.5-flash"

# file:line 形式の抽出パターン（Markdownで登場する形を幅広く拾う）
FILE_LINE_PATTERN = re.compile(
    r"([A-Za-z]:[\\/][^\s`'\"]+?\.(?:py|md)|[a-zA-Z0-9_][\w./\\-]*\.(?:py|md)):(\d+)"
)

# ワークスペースルート（basename解決のフォールバック用）
WORKSPACE_ROOT = SCRIPT_DIR.parent  # c:/.../iMak_workspace

VERIFIER_SYSTEM = """あなたはiMak Trading Japanの**二次監査官**です。
Claudeの一次監査官（implementation-auditor）が出したレポートの真偽を、別ベンダーAI（Gemini）として独立検証します。

## あなたの仕事
1. 一次監査レポートの各判定（✅/❌/⚠️/🚫/📌）を1件ずつ検証する
2. 引用された `file:line` が実コードと一致するか確認する（コード抜粋が添付される）
3. 結論が妥当か、論理的に判定する
4. 一次監査官と同じ盲点に陥らないよう、独立して考える

## 判定カテゴリ
- **AGREE**: 一次監査の判定に同意。根拠も正しい
- **PARTIAL**: 判定は概ね正しいが、一部誇張/欠落がある
- **DISPUTE**: 一次監査の判定が誤っている。引用先にそのコードがない、または解釈が違う
- **UNVERIFIABLE**: コード抜粋が不足で検証不能

## 出力形式（必須）
各項目について以下の形式で記述:

```
### [元項目のタイトル]
- Gemini判定: AGREE | PARTIAL | DISPUTE | UNVERIFIABLE
- 根拠: <なぜその判定か。引用した実コードを具体的に参照>
- 補足: <一次監査が見逃している観点があれば>
```

最後に総合判定:
```
## 総合判定
- AGREE: N件 / PARTIAL: N件 / DISPUTE: N件 / UNVERIFIABLE: N件
- 信頼度: <高/中/低> — Claude監査官のレポート全体の信頼度
- 推奨: ユーザーへの助言
```

忖度せず、Claude監査官が間違っていたら DISPUTE してください。
"""


def load_key():
    if not KEY_FILE.exists():
        print(f"ERROR: {KEY_FILE} が存在しません", file=sys.stderr)
        sys.exit(1)
    return KEY_FILE.read_text(encoding="utf-8").strip()


def extract_code_excerpts(report_text, context_lines=3):
    """レポートに登場する file:line を見つけて、該当コードを抜粋"""
    excerpts = {}
    seen = set()
    for match in FILE_LINE_PATTERN.finditer(report_text):
        raw_path = match.group(1).replace("\\", "/")
        line_no = int(match.group(2))
        key = (raw_path, line_no)
        if key in seen:
            continue
        seen.add(key)

        # 絶対パス化（相対ならワークスペース基準、見つからなければbasenameで全走査）
        candidates = [
            Path(raw_path),
            WORKSPACE_ROOT / raw_path,
        ]
        path = None
        for c in candidates:
            try:
                if c.exists():
                    path = c
                    break
            except OSError:
                pass
        if not path:
            # basenameでワークスペース全体から検索（短縮表記 "montbell_listing.py:65" などを救う）
            basename = Path(raw_path).name
            matches = list(WORKSPACE_ROOT.rglob(basename))
            # backup_ フォルダを除外して最有力を選ぶ
            matches = [m for m in matches if "backup_" not in str(m)]
            if len(matches) == 1:
                path = matches[0]
            elif len(matches) > 1:
                # 複数ヒット: 最も短いパス（トップレベル優先）を採用
                path = sorted(matches, key=lambda p: len(str(p)))[0]
        if not path:
            excerpts[f"{raw_path}:{line_no}"] = f"<FILE NOT FOUND: {raw_path}>"
            continue

        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as e:
            excerpts[f"{raw_path}:{line_no}"] = f"<READ ERROR: {e}>"
            continue

        start = max(0, line_no - context_lines - 1)
        end = min(len(lines), line_no + context_lines)
        snippet = []
        for i in range(start, end):
            marker = ">>>" if (i + 1) == line_no else "   "
            snippet.append(f"{marker} {i+1}: {lines[i]}")
        excerpts[f"{raw_path}:{line_no}"] = "\n".join(snippet)
    return excerpts


def build_verification_prompt(report_text, excerpts):
    parts = [
        "# 一次監査レポート（Claude implementation-auditor 作成）",
        "",
        report_text,
        "",
        "---",
        "",
        "# 引用された file:line の実コード抜粋",
        "",
    ]
    if not excerpts:
        parts.append("（file:line引用なし）")
    else:
        for key, snippet in excerpts.items():
            parts.append(f"## {key}")
            parts.append("```")
            parts.append(snippet)
            parts.append("```")
            parts.append("")
    parts += [
        "---",
        "",
        "上記レポートを独立検証し、指定の出力形式で判定してください。",
    ]
    return "\n".join(parts)


def verify(report_text):
    from google import genai
    from google.genai import types

    key = load_key()
    client = genai.Client(api_key=key)

    excerpts = extract_code_excerpts(report_text)
    prompt = build_verification_prompt(report_text, excerpts)

    resp = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=VERIFIER_SYSTEM,
            temperature=0.2,
        ),
    )
    return resp.text, excerpts


def main():
    # レポート読み込み
    if len(sys.argv) > 1:
        report_path = Path(sys.argv[1])
        if not report_path.exists():
            print(f"ERROR: {report_path} が存在しません", file=sys.stderr)
            sys.exit(1)
        report_text = report_path.read_text(encoding="utf-8")
    else:
        report_text = sys.stdin.read()

    if not report_text.strip():
        print("ERROR: レポートが空です", file=sys.stderr)
        sys.exit(1)

    print(f"[Gemini Verifier] モデル={MODEL} 報告文字数={len(report_text)}")
    verdict, excerpts = verify(report_text)
    print(f"[Gemini Verifier] 抜粋取得={len(excerpts)}件")

    # 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = LOGS_DIR / f"gemini_verdict_{ts}.md"
    out_path.write_text(
        f"# Gemini 二次監査 [{ts}]\n\n"
        f"## 対象レポート\n\n{report_text}\n\n---\n\n"
        f"## Gemini検証結果\n\n{verdict}\n",
        encoding="utf-8",
    )
    print(f"[Gemini Verifier] 保存: {out_path}")

    # 標準出力にも結果を
    print("\n" + "=" * 60)
    print("GEMINI VERDICT")
    print("=" * 60)
    print(verdict)


if __name__ == "__main__":
    main()
