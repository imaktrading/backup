"""補URL は **必ず目視を通す** — 無確証の自動書込を禁じる (2026-08-03 ユーザー指示)。

ユーザー指示:
    「確認する前に、目視を経由せずにカードを特定することはやめよう。
      スニダンも目視を経由するように修正して」

## 何が起きていたか (実害)

`psa_resource_gate.py` が `aux_writeback` (= **メルカリ + SNKRDUNK 混合**の候補URL) を
**確証UIを一度も通さずに**商品管理シートの補URL(AC-AG)へ直接書いていた。

「SNKRDUNK は cert で個体特定できるから目視不要」という理解は**誤り**だった。実装は
`check_by_keyword(card_number)` = **カード番号での検索**で、同番号に複数変種があれば
メルカリと同じく別変種を掴む。

誤った補URLは表示が汚れるだけでは済まない:
    誤URL → 監視くんがその価格を M列に書く → `N=(M or F)-K` が拾う
          → **価格エンジンが出品価格をその安値から決める**

2026-08-03 の実例: オカルトマニアの **通常版 ¥12,200** を掴んだ結果、
**ミラー版 ¥57,500** の出品が **$169.98** で出ていた (正しくは **$640.98** = 3.8倍差)。
バイヤーからオファーが来て偶然気づいた。気づかなければ大赤字で成約していた。

## この test が守るもの

目視を通す経路 (`psa_hoju_fill.confirm` / `ichibankuji_restock` の確証UI) 以外から
`write_aux_urls` を呼ばないこと。**供給は cache に残るので失われない。**
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, "iMakHQ", "tools")


def _src(name):
    return io.open(os.path.join(TOOLS, name), encoding="utf-8").read()


def _calls_write_aux(src):
    """`write_aux_urls(...)` を **実際に呼んでいる** 行だけ返す.

    除外するもの (呼出ではない):
      - `def write_aux_urls(` … 定義そのもの (sheet_io)
      - `#` で始まる行 … コメント
      - 説明文中の言及 … 行頭が識別子/代入でないもの (docstring の散文)
    """
    out = []
    for ln in src.splitlines():
        s = ln.strip()
        if not re.search(r"write_aux_urls\s*\(", s) or s.startswith("#"):
            continue
        if s.startswith("def "):
            continue
        # 呼出は「行頭が識別子・代入・return 等」。散文 (日本語や矢印で始まる) は除く。
        if not re.match(r"^[A-Za-z_][\w.]*\s*(=|\()|^(return|n\s*=|_\w+\s*=)", s):
            continue
        out.append(s)
    return out


def test_psa_resource_gate_does_not_write_aux_urls():
    """★本丸。ここが目視を通さずに書いていた (メルカリ + SNKRDUNK 混合)."""
    calls = _calls_write_aux(_src("psa_resource_gate.py"))
    assert not calls, (
        "psa_resource_gate が補URLを書いている (目視を通さない自動特定):\n"
        + "\n".join(calls))


def test_psa_resource_gate_still_keeps_candidates():
    """候補は捨てない。cache に残し、確証UIが拾って人に見せる (供給を減らさない)."""
    src = _src("psa_resource_gate.py")
    assert "psa_research_cache" in src or "研究キャッシュ" in src, \
        "候補の保存が消えている = 供給が失われる"
    assert "停止中" in src and "confirm" in src, \
        "止めた理由と、どこで目視するかが書かれていない"


def test_visual_confirm_paths_are_the_only_writers():
    """補URL を書いてよいのは **目視UIを持つ2つ** だけ。

    - `psa_hoju_fill.py`      … 昼確認 (視覚確証ビューア)
    - `ichibankuji_restock.py`… 一番くじ 補URL特定 (目視UI。夜間cronは候補を貯めるだけ)
    - `dup_guard.py`          … 削除方向のみ (共有URLを外す = 供給が減るだけ・安全)
    - `hoju_url_from_dupes.py`… cert/KEY で特定済みの実在個体を同KEYに紐づけるだけ
    - `kuji_hoju_fill.py`     … 一番くじ 補URL (目視UI。候補を写真・価格付きで並べて人が選ぶ。
                                2026-08-20 追加。検索は文字列一致なので **目視が唯一の担保**)
    - `ut_hoju_fill.py`       … UT 補URL (2026-09-03 追加)。PSA と同じ目視ビューア
                                (`psa_resource_confirm.restock_confirm`) を通してから書く。
                                UT は 作品+柄+サイズ+状態 が揃って初めて同じ商品なので、
                                機械の絞り込みだけでは決められない = **目視が唯一の担保**
    """
    allowed = {"psa_hoju_fill.py", "ichibankuji_restock.py",
               "dup_guard.py", "hoju_url_from_dupes.py", "kuji_hoju_fill.py",
               "ut_hoju_fill.py",
               "sheet_io.py",                 # 定義そのもの (書き手ではない)
               "ichibankuji_restock_poc.py"}  # POC。本番フローから呼ばれない
    offenders = {}
    for fn in os.listdir(TOOLS):
        if not fn.endswith(".py") or fn in allowed:
            continue
        try:
            calls = _calls_write_aux(_src(fn))
        except OSError:
            continue
        if calls:
            offenders[fn] = calls
    assert not offenders, (
        "目視UIを持たないツールが補URLを書いている:\n"
        + "\n".join(f"  {k}: {v}" for k, v in offenders.items()))


def test_snkrdunk_is_keyword_search_not_cert():
    """「SNKRDUNK は cert で特定できる」は誤り — この誤解が目視省略の根拠だった.

    実装は `check_by_keyword(card_number)`。同番号の別変種を掴みうる。
    """
    import glob
    hits = []
    for p in glob.glob(os.path.join(TOOLS, "snkrdunk*.py")):
        if "def check_by_keyword" in io.open(p, encoding="utf-8").read():
            hits.append(os.path.basename(p))
    assert hits, "snkrdunk の検索関数が見つからない (名前が変わったら本 test を見直す)"
