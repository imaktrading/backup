# -*- coding: utf-8 -*-
"""ボタンの残数は **引き算で出さない** (2026-09-10 ユーザー指示).

> 全部のボタンで同じようにしてほしい。残1と出て、押しても直らないなら、意味がない。

残数がずれる原因は毎回同じで、「母数 − A − B − C …」と件数を引いていくこと。
A と B に同じ札が居ると二重に引かれ、居ないと引き忘れる。実際に同じボタンで3回起きた:
  2026-09-04 ff38dd1 / 2026-09-07 b9575a2 / 2026-09-10 4e26749

**集合で数えれば二重に引けない。** `len(押せる集合 - 押せない集合)` の形にする。
`len(a - b)` (集合の引き算) は可。`max(x - y, 0)` のような件数どうしの引き算は不可。
"""
import glob
import os
import re

TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


def _bodies():
    """{ファイル名: count_workload の中身} を返す。"""
    out = {}
    for path in glob.glob(os.path.join(TOOLS, "*.py")):
        src = open(path, encoding="utf-8").read()
        i = src.find("def count_workload")
        if i < 0:
            continue
        j = src.find(chr(10) + "def ", i + 10)
        out[os.path.basename(path)] = src[i:j if j > 0 else len(src)]
    return out


def _actionable_exprs(body):
    """`"actionable": <式>` の <式> を取り出す (カンマの深さを見る)。"""
    exprs = []
    for m in re.finditer(r'"actionable":\s*', body):
        k, depth, buf = m.end(), 0, []
        while k < len(body):
            ch = body[k]
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                if depth == 0:
                    break
                depth -= 1
            elif ch == "," and depth == 0:
                break
            buf.append(ch)
            k += 1
        exprs.append("".join(buf).strip())
    return exprs


def _strip_len_calls(expr):
    """`len(...)` の中身を消す (集合の引き算は許すため)。"""
    out, i = [], 0
    while i < len(expr):
        if expr.startswith("len(", i):
            depth, i = 1, i + 4
            while i < len(expr) and depth:
                if expr[i] == "(":
                    depth += 1
                elif expr[i] == ")":
                    depth -= 1
                i += 1
            out.append("LEN")
            continue
        out.append(expr[i])
        i += 1
    return "".join(out)


def test_no_button_counts_by_subtracting_numbers():
    """どのボタンの残数も、件数どうしの引き算で作らないこと。"""
    bad = []
    for name, body in _bodies().items():
        for expr in _actionable_exprs(body):
            if "-" in _strip_len_calls(expr):
                bad.append("%s: %s" % (name, expr[:80]))
    assert not bad, (
        "残数を引き算で出しています (集合にしてください): " + " / ".join(bad))


# 1つの count_workload が **複数ボタン分**を返すもの。キー名が actionable ではない。
# (新しく作った counter が黙って外れないよう、ここに列挙する形で許可する)
_MULTI_BUTTON = {
    "psa_hoju_fill.py":    ("search", "confirm"),      # 補URL ①②③
    "newcand_confirm.py":  ("show", "auto"),           # 🌱 新しい仕入元
}


def test_every_counter_says_how_many_the_press_moves():
    """全部のボタンが『押したら動く件数』を返すこと (複数ボタン分は上の表で許可)。"""
    missing = []
    for n, b in _bodies().items():
        if '"actionable"' in b or '"error"' in b:
            continue
        keys = _MULTI_BUTTON.get(n)
        if keys and all('"%s"' % k in b for k in keys):
            continue
        missing.append(n)
    assert not missing, missing


def test_the_psa_chain_agrees_between_2_and_3():
    """②が「作れない」と言った札は、③でも押せる数に入れない (集合で受け渡す)。"""
    src = open(os.path.join(TOOLS, "psa_restock_writeback.py"), encoding="utf-8").read()
    assert 'b.get("blocked_iids")' in src, "件数ではなく itemID の集合を受け取ること"
    assert "todo_iids - blocked_iids" in src
    src2 = open(os.path.join(TOOLS, "psa_restock_build.py"), encoding="utf-8").read()
    assert '"blocked_iids"' in src2, "②は作れない itemID を公開すること"
