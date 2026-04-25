#!/usr/bin/env python3
"""
iMak Trading Japan - Listing 共通基盤 (SSOT)

全プロジェクトのlistingスクリプトはここから共通機能を取得する。
段階移行のため、小さく機能を集約していく。

提供機能:
- get_csv_output_path(project, purpose): CSV出力先を中央フォルダに統一
- load_keyword_pdf(category): iMakKeywords PDF を pdftotext で読み、上位語リストを返す
- 利益計算は profit_params.py を直接importして使う
- 品質チェックは listing_validator.py を使う
"""
import os
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = SCRIPT_DIR.parent

# ===== CSV 出力先 =====
CSV_OUTPUT_DIR = WORKSPACE_ROOT / "iMakHQ" / "csv_output"
CSV_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_csv_output_path(project, purpose="upload", ext="csv"):
    """
    中央CSVフォルダ内のパスを返す。
    例: get_csv_output_path("tcg", "upload") → ".../iMakHQ/csv_output/tcg_upload_20260415_103000.csv"
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{project}_{purpose}_{ts}.{ext}"
    return str(CSV_OUTPUT_DIR / fname)


# ===== PDF キーワード読込 =====
KEYWORDS_DIR = WORKSPACE_ROOT / "iMakKeywords"

# プロジェクト/カテゴリ → (PDFファイル名, 先頭セクション見出しの正規表現)
# 見出し正規表現に該当する行以降のRankだけを抽出（PDFに複数サブカテゴリが含まれる問題を回避）
KEYWORD_PDF_MAP = {
    "tcg":         ("Toys_Hobbies_2026Q1.pdf",           r"CCG Individual Cards"),
    "gshock":      ("Jewelry_Watches_2026Q1.pdf",        r"Watches"),
    "ichibankuji": ("Collectibles_2026Q1.pdf",           r"Animation Art"),
    # 注: Clothing PDFはTシャツ/アウター個別セクションなし。Men's Bagsで代用（商品属性違うが同カテゴリ群）
    "tshirt":      ("Clothing_Shoes_Accessories_2026Q1.pdf", r"\bMen's Bags"),
    "montbell":    ("Clothing_Shoes_Accessories_2026Q1.pdf", r"\bMen's Bags"),
    "porter":      ("Clothing_Shoes_Accessories_2026Q1.pdf", r"\bMen's Bags"),
    "tomica":      ("Toys_Hobbies_2026Q1.pdf",           r"Action Figures"),
    "fishing":     ("Sporting_goods_2026Q1.pdf",         r"Fishing"),
}


def load_keyword_pdf(project, top_n=30):
    """
    プロジェクト名からPDFを引き、該当サブカテゴリセクション内の上位N件を返す。
    PDFが読めない/見つからない場合は [] を返す。
    """
    import re as _re
    entry = KEYWORD_PDF_MAP.get(project)
    if not entry:
        return []
    if isinstance(entry, str):
        pdf_name, section_pat = entry, None
    else:
        pdf_name, section_pat = entry
    pdf_path = KEYWORDS_DIR / pdf_name
    if not pdf_path.exists():
        return []
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            return []
        text = result.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    # セクション見出しパターンがあれば、該当セクションだけを抽出
    lines = text.splitlines()
    if section_pat:
        section_re = _re.compile(section_pat, _re.IGNORECASE)
        start = None
        for i, line in enumerate(lines):
            if section_re.search(line) and "top searched keywords" in line.lower():
                start = i
                break
        if start is None:
            # 見出しが見つからなければ全体から抽出（フォールバック）
            scoped = lines
        else:
            # 次の "top searched keywords" 行まで
            end = len(lines)
            for j in range(start + 1, len(lines)):
                if "top searched keywords" in lines[j].lower():
                    end = j
                    break
            scoped = lines[start:end]
    else:
        scoped = lines

    keywords = []
    seen_ranks = set()
    for line in scoped:
        parts = line.split()
        if not parts or not parts[0].isdigit():
            continue
        rank = int(parts[0])
        if rank > top_n or rank in seen_ranks:
            continue
        seen_ranks.add(rank)
        if len(parts) >= 4:
            keyword = " ".join(parts[3:]).strip()
            if keyword and not keyword.replace(" ", "").isdigit():
                keywords.append({"rank": rank, "keyword": keyword})
    return sorted(keywords, key=lambda x: x["rank"])[:top_n]


def format_keywords_for_prompt(keywords):
    """Claude API の SYSTEM_PROMPT に注入するためのフォーマット"""
    if not keywords:
        return "(キーワードPDFなし)"
    lines = [f"Rank {k['rank']}: {k['keyword']}" for k in keywords]
    return "## 優先キーワード（検索ボリューム順、必ずタイトルに反映）\n" + "\n".join(lines)


if __name__ == "__main__":
    # セルフテスト
    print("CSV出力先:", CSV_OUTPUT_DIR)
    print("サンプルパス:", get_csv_output_path("tcg"))
    print()
    for proj in ["tcg", "tshirt", "montbell", "gshock"]:
        kws = load_keyword_pdf(proj, top_n=10)
        print(f"[{proj}] 上位{len(kws)}件:")
        for kw in kws[:5]:
            print(f"  {kw['rank']}. {kw['keyword']}")
        print()
