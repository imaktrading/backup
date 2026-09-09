# 2026-09-09: 窓口回答 2026-09-09_sheet_append_must_not_touch_n_column_response_response_question_response.md
#
# 商品管理シート(HIGH, 19kj8Nq...)の N 列は =ARRAYFORMULA((M or F)-K) の spill 出力。
# 1セルでも書込レンジに含めると spill が壊れる(2026-09-09 commit 5a29092 の実害と同型)。
# 「人はシートを手で触らない」= 次に壊すとしたらコードだけ、なので書く前に静的検査で落とす。
#
# 手順(窓口指定のまま): 商品管理シートのIDを含む.pyを全部読む
#   → 書込のレンジ指定の行 (range_name= / "range":) だけ見る
#   → レンジの列を数えて 開始 <= N(14) <= 終了 なら落とす
#
# scope は iMakRevise/ 配下だけ(= 自 worktree の領域)。worktree 分離のため、この branch には
# 他プロジェクト(iMakHQ/iMak_ichibankuji 等)の古いコードが同梱されており、そちらは他セッションの
# 領域で別途修正が入る。全repoを見ると他所の古さで自分の commit が止まる(2026-09-09 判明)。
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1] / "iMakRevise"
THIS_FILE = Path(__file__).resolve()

SHEET_ID = "19kj8NqWHIGP1ptQDeGePw077hpdl6dNOO-v2J10HCjk"
N_COL = 14  # A=1 ... N=14

RANGE_ASSIGN_RE = re.compile(
    r"""range_name\s*=\s*f?(['"])(?P<v1>.*?)\1
      | ['"]range['"]\s*:\s*f?(['"])(?P<v2>.*?)\3
    """,
    re.VERBOSE,
)

EXCLUDE_DIR_NAMES = {".git", "__pycache__", "node_modules", ".venv", "venv"}


def _iter_repo_py_files():
    for path in REPO_ROOT.rglob("*.py"):
        if path.resolve() == THIS_FILE:
            continue
        if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
            continue
        yield path


def _col_to_num(col: str) -> int:
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _range_columns(range_str: str):
    """レンジ文字列から列レターだけ抜く({row_var} 等の f-string 埋込は無視)."""
    cleaned = re.sub(r"\{[^}]*\}", "", range_str)
    cleaned = cleaned.split("!")[-1]  # "Sheet1!A1:B2" 形式のシート名部分を除去
    cols = []
    for part in cleaned.split(":"):
        m = re.match(r"^([A-Za-z]+)", part)
        if m:
            cols.append(_col_to_num(m.group(1)))
    return cols


def find_n_column_write_violations():
    violations = []
    for path in _iter_repo_py_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if SHEET_ID not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in RANGE_ASSIGN_RE.finditer(line):
                range_str = m.group("v1") or m.group("v2")
                cols = _range_columns(range_str)
                if not cols:
                    continue
                start, end = min(cols), max(cols)
                if start <= N_COL <= end:
                    violations.append((str(path.relative_to(REPO_ROOT)), lineno, range_str))
    return violations


def test_no_write_range_touches_n_column_of_product_sheet():
    violations = find_n_column_write_violations()
    assert not violations, (
        "商品管理シート(HIGH, 19kj8Nq...)の N 列(仕入¥, ARRAYFORMULA spill)を含む書込レンジを検出:\n"
        + "\n".join(f"  {f}:{ln}  range={r!r}" for f, ln, r in violations)
        + "\nN 列は監視くんの ARRAYFORMULA 専用。書込レンジから外すこと。"
    )


def test_detector_flags_known_bad_pattern():
    """検出器自体の自己テスト: N を跨ぐレンジ文字列は必ず引っかかる."""
    assert _range_columns("A1:AG1") and min(_range_columns("A1:AG1")) <= N_COL <= max(_range_columns("A1:AG1"))
    assert not (
        _range_columns("A1:H1") and min(_range_columns("A1:H1")) <= N_COL <= max(_range_columns("A1:H1"))
    )
