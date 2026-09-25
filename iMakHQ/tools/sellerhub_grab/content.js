// Seller Hub レポート取り — ファネルの材料4つをボタン1回で落とす (2026-09-26)。
//
// なぜ拡張か: ブラウザの自動操作は eBay に弾かれた (「Something went wrong on our end」)。
//   いつものブラウザの中で、人が押したボタンの続きとして画面のボタンを押すだけにする。
//   レポートを「作る」操作はしない。Seller Hub の Schedule で毎日作られた完成品を押すだけ。
//
// 流れ: Reports > Downloads で「まとめて取る」
//   → 4種類 (出品中 / 売れ残り / 注文 / 広告) の一番新しい Completed の Download を押す
//   → Performance に移って「Download listings quality report」を押す
// 落ちた物は「ダウンロード」フォルダに入る。夜間バッチ (seller_hub_collect.py) が
// C:\dev\iMak_data\seller_hub\reports\<日付>\ に移し、ファネルがそれを読む。
(() => {
  "use strict";

  const WANT = [
    { source: "Listings", type: "All active listings", label: "出品中" },
    { source: "Listings", type: "Inactive Listings", label: "売れ残り" },
    { source: "Orders", type: "All orders", label: "注文" },
    // ファネルは広告レポートの古さも見て止まる (listing_funnel.py の鮮度ガード)
    { source: "Advertising", type: "Listing", label: "広告" },
  ];
  const FLAG = "shg_next_lqr";
  const OLD_HOURS = 48;          // これより古い完成品しか無い = Schedule が動いていない

  const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function panel() {
    let p = document.getElementById("shg-panel");
    if (p) return p;
    p = document.createElement("div");
    p.id = "shg-panel";
    p.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:99999;background:#fff;" +
      "border:2px solid #0654ba;border-radius:8px;padding:12px 14px;font:13px/1.5 sans-serif;" +
      "box-shadow:0 4px 16px rgba(0,0,0,.2);max-width:360px;color:#111";
    document.body.appendChild(p);
    return p;
  }

  function log(msg) {
    const p = panel();
    const d = document.createElement("div");
    d.textContent = msg;
    p.appendChild(d);
  }

  // "Sep 13, 2026 at 11:01pm PDT" → Date (PDT/PST を UTC に直す)
  function parseReq(s) {
    const m = /([A-Z][a-z]{2}) (\d{1,2}), (\d{4}) at (\d{1,2}):(\d{2})(am|pm) (PDT|PST)/.exec(s || "");
    if (!m) return null;
    const mon = "JanFebMarAprMayJunJulAugSepOctNovDec".indexOf(m[1]) / 3;
    let h = +m[4] % 12 + (m[6] === "pm" ? 12 : 0);
    const off = m[7] === "PDT" ? 7 : 8;
    return new Date(Date.UTC(+m[3], mon, +m[2], h + off, +m[5]));
  }

  function rows() {
    return [...document.querySelectorAll("tr.grid-row")].map((tr) => {
      const c = (k) => txt(tr.querySelector(".shui-dt-column__" + k));
      return {
        source: c("source"), type: c("type"), id: c("requestId"),
        when: parseReq(c("requestDate")), status: c("status"),
        btn: tr.querySelector(".shui-dt-column__downloadAction button"),
      };
    });
  }

  async function grabDownloads() {
    const all = rows();
    if (!all.length) { log("⚠️ 一覧が読めません。ページを開き直してから押してください"); return false; }
    let stale = [];
    for (const w of WANT) {
      // 一覧は新しい順。同じ種類の一番上の「Completed」を取る
      const r = all.find((x) => x.source === w.source && x.type.toLowerCase() === w.type.toLowerCase()
        && x.status === "Completed" && x.btn);
      if (!r) { log(`❌ ${w.label}: 完成済みのレポートがありません`); stale.push(w.label); continue; }
      const age = r.when ? (Date.now() - r.when.getTime()) / 3600e3 : 999;
      r.btn.click();
      log(`✅ ${w.label}: ${r.id} (${Math.round(age)}時間前に作成) を落としました`);
      if (age > OLD_HOURS) stale.push(w.label);
      await sleep(2500);
    }
    if (stale.length) {
      log(`⚠️ 古い/無い: ${stale.join("・")}。Reports > Schedule で毎日作る設定を確かめてください`);
    }
    return true;
  }

  function lqrButton() {
    return [...document.querySelectorAll("#sh-perf-page-nsa button")]
      .find((b) => /Download listings quality report/i.test(txt(b)));
  }

  async function grabLqr() {
    for (let i = 0; i < 20 && !lqrButton(); i++) await sleep(500);
    const b = lqrButton();
    if (!b) { log("❌ 品質レポートのボタンが見つかりません (画面が United States か確かめてください)"); return; }
    b.click();
    log("✅ 品質レポート: 押しました (出来上がるまで数十秒かかることがあります)");
    log("🎉 5つとも完了。夜のバッチがファネルの置き場へ移します");
  }

  function startButton(label, fn) {
    const p = panel();
    const t = document.createElement("div");
    t.style.cssText = "font-weight:bold;margin-bottom:6px";
    t.textContent = "Seller Hub レポート取り";
    const b = document.createElement("button");
    b.textContent = label;
    b.style.cssText = "background:#0654ba;color:#fff;border:0;border-radius:4px;padding:6px 12px;cursor:pointer";
    b.onclick = async () => { b.disabled = true; await fn(); };
    p.append(t, b);
  }

  if (location.pathname.startsWith("/sh/reports/downloads")) {
    startButton("ファネル用レポートをまとめて取る", async () => {
      if (await grabDownloads()) {
        sessionStorage.setItem(FLAG, "1");
        log("→ 品質レポートの画面へ移ります…");
        await sleep(3000);
        location.href = "https://www.ebay.com/sh/performance";
      }
    });
  } else if (location.pathname.startsWith("/sh/performance")) {
    if (sessionStorage.getItem(FLAG) === "1") {
      sessionStorage.removeItem(FLAG);
      panel();
      log("Seller Hub レポート取り (続き)");
      grabLqr();
    } else {
      startButton("品質レポートだけ取る", grabLqr);
    }
  }
})();
