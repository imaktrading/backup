"""Phase 2 verification: 21 検体に対し新ロジック候補を機械的に適用、全件正解か確認."""
from __future__ import annotations
import json
import re
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parent / "html_samples"


def detect(html: str) -> tuple[str, str]:
    """Returns (verdict, reason).

    verdict: "IN_STOCK" / "SOLD" / "real_err"
    reason:  デバッグ用一行説明
    """
    # 1) 必須コンテナ (hydration 完了の proxy)
    if 'data-testid="checkout-button-container"' not in html:
        return "real_err", "checkout-button-container not found (hydration?)"

    # 2) checkout-button div の探索 (container 内側)
    # パターン: <div ... data-testid="checkout-button" ... ></div>
    m = re.search(
        r'<div\b([^>]*?)data-testid="checkout-button"([^>]*)>',
        html,
    )
    if not m:
        # checkout-button 不在 = transaction-in-progress (取引中) 等の派生 sold ステート
        # checkout-button-container 内に view-transaction-button or 同等が出ている。
        return "SOLD", "checkout-button absent in container (transaction or similar)"

    div_attrs_full = m.group(0).lower()
    # 3) disabled 系シグナル
    if "disabled__" in div_attrs_full:
        return "SOLD", "checkout-button div has disabled__ class"
    if 'name="disabled"' in div_attrs_full:
        return "SOLD", 'checkout-button div has name="disabled"'

    # 4) IN_STOCK シグナル (name="purchase" / 無条件 active)
    if 'name="purchase"' in div_attrs_full:
        return "IN_STOCK", 'checkout-button div has name="purchase"'

    # 5) 既知パターンのいずれにも合致せず → 安全側 (誤取下げ防止) で real_err
    return "real_err", f"unknown checkout-button state: {m.group(0)[:100]}"


def main():
    print(f"=== Phase 2 verification: 21 samples ===\n")
    n_correct = 0
    n_wrong = []
    n_err = []
    log = json.loads((SAMPLES_DIR / "_collection_log.json").read_text(encoding="utf-8"))
    for entry in log:
        if entry["status"] != "ok":
            continue
        label = entry["label"]
        item_id = entry["item_id"]
        html_path = SAMPLES_DIR / f"{label}_{item_id}.html"
        html = html_path.read_text(encoding="utf-8", errors="replace")
        verdict, reason = detect(html)

        expected = "IN_STOCK" if label == "in_stock" else "SOLD"
        ok = verdict == expected
        mark = "✅" if ok else "❌"
        print(f"  {mark} {label:>8} {item_id}  → {verdict:>9}  ({reason})")
        if ok:
            n_correct += 1
        elif verdict == "real_err":
            n_err.append((label, item_id, reason))
        else:
            n_wrong.append((label, item_id, expected, verdict, reason))

    total = sum(1 for e in log if e["status"] == "ok")
    print(f"\n=== 結果 ===")
    print(f"  正解:    {n_correct}/{total}")
    print(f"  誤判定:  {len(n_wrong)}")
    print(f"  real_err:{len(n_err)}")
    if n_wrong:
        print(f"\n誤判定詳細:")
        for label, item_id, exp, got, reason in n_wrong:
            print(f"  {label} {item_id}: expected={exp}, got={got} ({reason})")
    if n_err:
        print(f"\nreal_err 詳細:")
        for label, item_id, reason in n_err:
            print(f"  {label} {item_id}: {reason}")


if __name__ == "__main__":
    main()
