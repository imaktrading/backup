"""`.ps1` に日本語を書くなら **BOM 付き UTF-8** で保存する (2026-08-02)。

なぜ (実害):
    Windows PowerShell 5.1 は **BOM が無い `.ps1` を ANSI (CP932) として読む**。
    `desk_autorun_register.ps1` を BOM 無し UTF-8 で置いたところ、冒頭の日本語コメントが
    化けて後続の `param([int]$Minutes = 5)` まで壊れ、ユーザーの画面に

        FAILED: パラメーター 'Minutes' をターゲットにバインドできません。
                "null を型 System.Int32 に変換できません。"

    が出て登録できなかった。**`.bat` の CP932 事故と同じ構造**を `.ps1` でもやった。

対策の原則 (2026-08-02 に .bat/.ps1 で計4回壊した末の結論):
    **外部プロセスが読むファイルは「ASCII だけ」か「codepage を明示 (BOM)」の二択。**
    どちらでもないものを置かない。人間向けの日本語は、encoding を自分で決められる
    Python 側 (`desk_autorun_setup.py`) に寄せる。
"""
from pathlib import Path

ROOT = Path(r"C:/dev/iMak")


def _ps1_files():
    if not ROOT.is_dir():
        return []
    # `_archive/obsolete` は実行されない置き場なので対象外 (直すと差分が増えるだけ)。
    skip = {".git", "_archive"}
    return [p for p in ROOT.rglob("*.ps1") if not skip & set(p.parts)]


def test_non_ascii_ps1_has_bom():
    """非 ASCII を含む `.ps1` は BOM 必須 (無いと PS 5.1 が CP932 で読んで壊す)."""
    bad = []
    for p in _ps1_files():
        raw = p.read_bytes()
        if all(b < 128 for b in raw):
            continue                       # ASCII のみ = codepage 非依存で安全
        if raw[:3] != b"\xef\xbb\xbf":
            bad.append(str(p))
    assert not bad, ("BOM 無しで日本語を含む .ps1 がある "
                     "(utf-8-sig で保存し直すこと):\n" + "\n".join(bad))


def test_autorun_register_is_intact():
    """自走の登録スクリプトが読める形であること (ここが壊れると ON にできない)."""
    p = ROOT / "iMakHQ" / "tools" / "desk_autorun_register.ps1"
    assert p.exists(), "desk_autorun_register.ps1 が無い"
    raw = p.read_bytes()
    body = raw.decode("utf-8-sig")
    assert "param([int]$Minutes" in body, "間隔パラメータが壊れている"
    assert "Register-ScheduledTask" in body
    assert "iMakHQ_DeskAutorun_ALPHA" in body
    # param は最初の実行文であること (コメントは可)。ここが崩れると bind に失敗する。
    stmts = [ln.strip() for ln in body.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    assert stmts and stmts[0].startswith("param("), \
        f"param が先頭の実行文でない: {stmts[0] if stmts else '(空)'}"
