"""Regression: 2026-06-16 — 全プロジェクトの実コードに retire 済 Claude モデルを残さない。

経緯: `claude-sonnet-4-20250514` (Claude Sonnet 4) が 2026-06-15 に Anthropic 公式に
retire され、Claude API 上で 404 を返すようになった。当初 TCG だけ直したが、横断 grep で
G-shock / Mercari / 一番くじ の計11箇所にも同じベタ書きが残っており全プロジェクトの
出品くん AI 部分が 404 していたことが発覚 (公式メールで全社対象と確認)。

この test は「retire 済モデル ID が iMak 配下のどの .py にも二度と現れない」を横断で固定し、
将来モデルが廃止された時の同型再発 (一部プロジェクトだけ直し漏れ) を検知する。
新たにモデルが retire されたら _RETIRED に追記する運用。
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Anthropic が retire 済 = 使うと 404 になるモデル ID
_RETIRED = {
    "claude-sonnet-4-20250514",   # Sonnet 4   — 2026-06-15 retire → claude-sonnet-4-6
    "claude-3-5-sonnet-20241022",
    "claude-3-5-sonnet-20240620",
    "claude-3-opus-20240229",
    "claude-3-7-sonnet-20250219",
    "claude-3-5-haiku-20241022",
}

# 対象プロジェクト (master 配下で HQ が直せる範囲)。他 worktree は各 worktree の責務。
_PROJECTS = ["iMakTCG", "iMakG-shock", "iMakMercari", "iMak_ichibankuji", "iMakeBayAPI", "iMakHQ"]


def test_no_retired_model_in_any_project_py():
    offenders = []
    for proj in _PROJECTS:
        base = _ROOT / proj
        if not base.exists():
            continue
        for py in base.rglob("*.py"):
            if py.name.startswith("test_"):
                continue  # test は _RETIRED を文字列として持つので除外
            try:
                src = py.read_text(encoding="utf-8")
            except Exception:
                continue
            for rid in _RETIRED:
                if rid in src:
                    offenders.append(f"{py.relative_to(_ROOT)} → {rid}")
    assert not offenders, "retire 済 Claude モデルが実コードに残存:\n" + "\n".join(offenders)
