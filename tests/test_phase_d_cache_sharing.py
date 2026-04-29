"""Phase D regression: market_gate cache must be shared between psa_to_csv and check_csv.

Why this test exists (memory dual_gate_disagreement.md):
  Phase C で SSOT module (iMakeBayAPI/market_gate.py) 化したが、psa_to_csv が
  subprocess.run([sys.executable, "check_csv.py", ...]) で別プロセス起動していたため
  in-memory cache が引き継がれず、median ブレ (psa $140 vs check $115) が再発した。

  Phase D で subprocess.run → from check_csv import main; main(csv) に切替えた。
  本テストは 2 つの不変条件を物理ギブスとして固定する:
    1. market_gate モジュールが同一プロセス内で同一インスタンスとしてロードされる
    2. psa_to_csv 側 wrapper の cache write を check_csv 側 wrapper が cache read で取出せる
    3. psa_to_csv のチェッカー起動経路が subprocess.run ではない (= 関数呼出に戻されない保険)
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TCG = _REPO_ROOT / "iMakTCG"
_EBAY_API = _REPO_ROOT / "iMakeBayAPI"
for p in (_TCG, _EBAY_API):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def test_check_csv_main_accepts_csv_path():
    """check_csv.main() must accept csv_path kwarg (Phase D-1)."""
    import check_csv
    sig = inspect.signature(check_csv.main)
    assert "csv_path" in sig.parameters, (
        "check_csv.main は csv_path 引数を受け取る必要がある (Phase D-1)"
    )
    # default は None (CLI 互換)
    assert sig.parameters["csv_path"].default is None


def test_market_gate_cache_shared_across_modules():
    """psa_to_csv と check_csv が同一の market_gate._CACHE を参照すること (Phase D-2)."""
    import market_gate
    # 直接 cache 投入 (psa_to_csv 側 wrapper の代理)
    market_gate.cache_clear()
    sentinel_key = ("PHASE_D_SENTINEL", market_gate._fetch_items_raw.__defaults__[0], 50)
    market_gate._cache_put(
        sentinel_key,
        items=[{"price": {"value": "100"}, "seller": {"feedbackScore": 0, "feedbackPercentage": "0"}}],
        total=42,
    )

    # check_csv の wrapper を呼ぶと cache hit するはず (= API 叩かない)
    import check_csv
    items, total = check_csv.search_ebay_active("FAKE_TOKEN", "PHASE_D_SENTINEL", limit=50)
    assert total == 42, "cache hit による total が一致するはず"
    assert len(items) == 1, "cache hit による items が一致するはず"

    # モジュール identity も検証 (sys.modules 上で同一インスタンス)
    import market_gate as mg2
    assert market_gate is mg2
    assert id(market_gate._CACHE) == id(mg2._CACHE)

    market_gate.cache_clear()


def test_psa_to_csv_does_not_subprocess_check_csv():
    """psa_to_csv 末尾は subprocess.run([..., 'check_csv.py', ...]) を含まない (Phase D-2)."""
    src = (_TCG / "psa_to_csv.py").read_text(encoding="utf-8")
    # subprocess.run 自体は別用途 (PSA Selenium 等) で残ってよいが、check_csv.py を起動する経路は禁止
    forbidden_patterns = [
        'subprocess.run(\n            [sys.executable, "check_csv.py"',
        'subprocess.run([sys.executable, "check_csv.py"',
    ]
    for pat in forbidden_patterns:
        assert pat not in src, (
            f"psa_to_csv が check_csv を subprocess 起動している (Phase D 違反): {pat}"
        )

    # 代わりに import 経路があること
    assert "from check_csv import main" in src, (
        "psa_to_csv は from check_csv import main で同一プロセス呼出するべき"
    )


def test_psa_to_csv_uses_csv_character_for_market_search():
    """psa_to_csv の market search は CSV C:Character を使う (Phase D 補完 / 2026-04-29).

    背景:
      psa_to_csv は L1958 で C:Card Number を CSV から読み取って query 構築に使うが、
      character は L1953 で raw subject から smart_titlecase(extract_character_name(...)) で
      別途生成していた. これにより C:Character (catalog localize 済) と
      query 用 character (subject 残骸付き) が乖離 → check_csv 側 query と一致せず
      cache miss → median ブレ (Bonney $175 vs $135 等).

    本テストは以下を物理ギブス化:
      1. psa_to_csv が search_market_price 呼出前に C:Character 列を読み出す
      2. search_market_price 呼出には character_full が渡る (not raw `character`)
    """
    src = (_TCG / "psa_to_csv.py").read_text(encoding="utf-8")

    # 1. C:Character の lookup が存在
    assert 'headers.index("C:Character")' in src, (
        "psa_to_csv は C:Character 列を CSV から読み取って query 用 character として使うべき"
    )
    # 2. search_market_price に character_full を渡している (旧: character)
    #    複数の呼出パターンを吸収するため正規表現で柔軟に
    import re
    m = re.search(
        r"search_market_price\(\s*ebay_token\s*,\s*game\s*,\s*card_number_full\s*,\s*character_full\s*\)",
        src,
    )
    assert m, (
        "search_market_price は (token, game, card_number_full, character_full) の順で "
        "character_full を渡すべき (Phase D 補完)"
    )
