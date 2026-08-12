"""`_question` を「幹に付いた別タスクの完了報告」で決着扱いにしない (2026-08-12).

実害: catalog が adapter 反転に「1,016行が fresh→stale に劣化する」と待ったをかけた
`..._response_question.md` が、同じ幹の `..._response_done.md` (別タスクの完了報告) に
よって board から消え、窓口が指摘に気づけないまま一晩過ぎた。同型で 10件が埋もれていた。

`_draft` の base-stem 判定 (2026-07-30 に入れた正しい挙動) は壊さないこと。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import worktree_board as wb  # noqa: E402


def _stems(*names):
    return set(names)


def test_question_not_closed_by_done_on_base_stem():
    """★本命: 幹に `_done` が付いても質問は開いたまま."""
    q = Path("2026-08-11_pdca_catalog_queue_tcg_response_question.md")
    stems = _stems(
        "2026-08-11_pdca_catalog_queue_tcg_response",
        "2026-08-11_pdca_catalog_queue_tcg_response_done",
        q.stem,
    )
    assert wb._draft_is_closed(q, stems) is False
    assert wb._is_closed(q, stems) is False


def test_question_closed_only_by_its_own_answer():
    q = Path("2026-08-11_pdca_catalog_queue_tcg_response_question.md")
    stems = _stems(
        "2026-08-11_pdca_catalog_queue_tcg_response",
        "2026-08-11_pdca_catalog_queue_tcg_response_done",
        q.stem,
        "2026-08-11_pdca_catalog_queue_tcg_response_question_response",
    )
    assert wb._is_closed(q, stems) is True


def test_draft_still_closed_by_sibling_response():
    """2026-07-30 の挙動 (draft は幹の closure で決着) を壊していないこと."""
    d = Path("2026-08-10_missing_images_blocking_listing_draft.md")
    stems = _stems(
        d.stem,
        "2026-08-10_missing_images_blocking_listing",
        "2026-08-10_missing_images_blocking_listing_response",
    )
    assert wb._draft_is_closed(d, stems) is True


def test_draft_open_when_no_closure():
    d = Path("2026-08-10_missing_images_blocking_listing_draft.md")
    stems = _stems(d.stem, "2026-08-10_missing_images_blocking_listing")
    assert wb._draft_is_closed(d, stems) is False


def test_non_draft_file_untouched():
    p = Path("2026-08-10_something.md")
    assert wb._draft_is_closed(p, _stems(p.stem)) is False
