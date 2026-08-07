"""`import sys as _sys` している走行スクリプトに bare `sys.` を残さない (2026-08-03)。

## 実害

`gshock_to_csv.py` は module top で `import sys as _sys` に統一しているのに、
`main()` 末尾の対話プロンプト分岐だけ bare `sys.stdin` を参照していた。

```
File ".../gshock_to_csv.py", line 1989, in main
    if sys.stdin and sys.stdin.isatty():
NameError: name 'sys' is not defined. Did you mean: '_sys'?
```

**CSV 生成は完了しているのに、末尾で落ちて returncode=1** になる。
出品くんパネルは returncode で成否を判定するので、**成功した走行が失敗に見える**。
「入稿してよいのか分からない」状態を作るので、出品を止めうる。

同型は 2026-08-01 に psa_to_csv (`8cf56f2`) でも起きている。**走行の最後で落ちる**のは
CSV が出来た後なので気づきにくく、パネルの表示だけが赤くなる。

## この test が守るもの

`import sys as _sys` を採っているスクリプトで、**実行される行**に bare `sys.` が無いこと。
(コメント・docstring 内の `sys.path` 等への言及は対象外)
"""
import io
import os
import re

ROOT = r"C:\dev\iMak"

# `import sys as _sys` 方針を採っている走行スクリプト (走行の最後で落ちると影響が大きい)
TARGETS = [
    os.path.join(ROOT, "iMakG-shock", "gshock_to_csv.py"),
]

RE_ALIAS_IMPORT = re.compile(r"^\s*import\s+sys\s+as\s+_sys", re.M)
RE_PLAIN_IMPORT = re.compile(r"^\s*(import\s+sys\s*$|from\s+sys\s+import)", re.M)


def _code_lines(src):
    """コメント行と、明らかな docstring 行を除いた行を (行番号, 本文) で返す.

    厳密な構文解析はしない。`#` 始まりを落とし、三重引用符の内側を飛ばすだけで
    今回の誤検出 (docstring 内の `sys.path` への言及) は除ける。
    """
    out, in_doc = [], False
    for i, ln in enumerate(src.splitlines(), 1):
        s = ln.strip()
        if in_doc:
            if '"""' in s or "'''" in s:
                in_doc = False
            continue
        if s.startswith('"""') or s.startswith("'''"):
            if not (s.count('"""') >= 2 or s.count("'''") >= 2):
                in_doc = True
            continue
        if s.startswith("#"):
            continue
        out.append((i, ln))
    return out


def test_no_bare_sys_when_aliased_as_underscore_sys():
    for path in TARGETS:
        if not os.path.exists(path):
            continue
        src = io.open(path, encoding="utf-8").read()
        if not RE_ALIAS_IMPORT.search(src):
            continue                       # alias 方針でないファイルは対象外
        if RE_PLAIN_IMPORT.search(src):
            continue                       # bare import もあるなら bare 参照は合法
        bad = [(i, ln.strip()) for i, ln in _code_lines(src)
               if re.search(r"(?<![\w.])sys\s*\.", ln)]
        assert not bad, (
            f"{os.path.basename(path)} は `import sys as _sys` なのに bare `sys.` がある "
            f"(実行時 NameError → 走行の最後で returncode=1):\n"
            + "\n".join(f"  L{i}: {t}" for i, t in bad))
