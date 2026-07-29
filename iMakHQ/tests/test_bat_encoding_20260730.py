"""`.bat` は cmd.exe が **OEM codepage (932)** で読む — UTF-8 で保存してはいけない (2026-07-30).

実害: `run_hoju_search.bat` が UTF-8 だったため日本語コメントが文字化けし、
`'do' is not recognized ...` で **for ループごと壊れて何も実行されない**のに、タスクは
`LastTaskResult=0` (成功) を返していた。7/28 の作成以降 **一度も走っていなかった**
(psa_research_cache.json の更新が手動実行分しか無いことで発覚)。

文字化けは「REM の後ろだから安全」ではない: CP932 の 2 バイト文字として解釈された時に
**次の ASCII 文字 (引用符・括弧・改行) を食う**ため、任意の行が壊れうる。

この test は「UTF-8 の .bat を置いたら落とす」ためのもの。
日本語を書きたいなら CP932 で保存する。迷うなら ASCII だけで書く。
"""
import os
from pathlib import Path

ROOT = Path(r"C:/dev/iMak")


def _bat_files():
    if not ROOT.is_dir():
        return []
    out = []
    for ext in ("*.bat", "*.cmd"):
        out += [p for p in ROOT.rglob(ext) if ".git" not in p.parts]
    return out


def test_no_utf8_encoded_batch_files():
    """非 ASCII を含む .bat は CP932 でデコードできること (= UTF-8 で保存されていない)。"""
    bad = []
    for p in _bat_files():
        raw = p.read_bytes()
        if all(b < 128 for b in raw):
            continue                      # ASCII のみ = codepage 非依存で安全
        try:
            raw.decode("cp932")
        except UnicodeDecodeError:
            bad.append(str(p))
            continue
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            continue                      # CP932 で読めて UTF-8 では読めない = 正しい
        # 両方で読める = 非ASCIIが1バイト系のみ。実害は出にくいが、判別できないので報告
        if any(b >= 0x80 for b in raw):
            bad.append(str(p) + " (UTF-8 としても解釈可能 = 要確認)")
    assert not bad, "cmd.exe が読めない .bat がある (CP932 で保存し直すこと):\n" + "\n".join(bad)


def test_batch_files_have_no_bom():
    """BOM 付きだと 1 行目 (`@echo off`) が壊れて画面にゴミが出る。"""
    bom = [str(p) for p in _bat_files() if p.read_bytes()[:3] == b"\xef\xbb\xbf"]
    assert not bom, "BOM 付きの .bat がある:\n" + "\n".join(bom)


def test_hoju_search_bat_is_ascii_only():
    """夜間検索の本体は ASCII のみを維持する (codepage に一切依存させない)。"""
    p = ROOT / "iMakHQ" / "tools" / "run_hoju_search.bat"
    if not p.exists():
        return
    raw = p.read_bytes()
    assert all(b < 128 for b in raw), "run_hoju_search.bat に非ASCIIが入った (再発経路)"
    assert b"search --limit=30" in raw, "zero-backup ステップが消えている"
