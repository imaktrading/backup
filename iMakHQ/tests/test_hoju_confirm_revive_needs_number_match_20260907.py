"""一度「違う」と判定した札は、**番号まで一致した供給**が出るまで戻さない (2026-09-07).

> 目視したカードが再度出ている気がする。時間の無駄やからちゃんとしろや

9/06 に「新しい供給が出るまで伏せる」を入れたが、戻す条件が **URL が1本でも増えたら**
だったため、夜の探すが毎晩1本 拾うたびに同じ札が戻ってきていた。
実測 (2026-09-07): 台帳65件中 **50件が復活状態** → この修正で 13件。
"""
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import psa_hoju_fill as H  # noqa: E402

HDR = ["itemID", "cert", "title", "理由", "日付", "その時の候補URL"]


def _rows(iid="1", seen=("https://jp.mercari.com/item/a",)):
    return [HDR, [iid, "c", "t", "違う", "2026-09-01", " ".join(seen)]]


def test_number_unconfirmed_new_url_does_not_revive():
    """番号未確認の候補が増えただけでは戻さない (毎晩1本で復活していた形)."""
    rows = _rows()
    cur = ["https://jp.mercari.com/item/a", "https://jp.mercari.com/item/NEW"]
    skip = H.skip_iids_now(rows, {"1": cur}, {"1": []})     # strict = 0本
    assert "1" in skip


def test_number_matched_new_url_revives():
    """番号まで一致した供給が出たら戻す (本当に見る価値がある)."""
    rows = _rows()
    cur = ["https://jp.mercari.com/item/a", "https://jp.mercari.com/item/NEW"]
    skip = H.skip_iids_now(rows, {"1": cur}, {"1": ["https://jp.mercari.com/item/NEW"]})
    assert "1" not in skip


def test_no_record_still_shows():
    """前回の候補を記録していない旧行は、判断材料が無いので出す (伏せ過ぎない)."""
    rows = [HDR, ["1", "c", "t", "違う", "2026-09-01", ""]]
    assert "1" not in H.skip_iids_now(rows, {"1": ["https://x/1"]}, {"1": []})


def test_without_strict_map_behaves_as_before():
    """strict を渡さない呼び方は従来どおり (呼び側が用意できない時に伏せ過ぎない)."""
    rows = _rows()
    cur = ["https://jp.mercari.com/item/a", "https://jp.mercari.com/item/NEW"]
    assert "1" not in H.skip_iids_now(rows, {"1": cur})


def test_strict_urls_reads_only_confirmed_bucket():
    entry = {"mercari": {"cands": [[100, "https://x/ok", "t"]],
                         "all_cands": [[100, "https://x/ok", "t"], [200, "https://x/loose", "t"]]}}
    assert H._cache_strict_candidate_urls(entry) == ["https://x/ok"]
    assert len(H._cache_candidate_urls(entry)) == 2
