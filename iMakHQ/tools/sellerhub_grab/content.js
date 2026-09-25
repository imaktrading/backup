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
    if (!p.firstChild) {
      const t = document.createElement("div");
      t.style.cssText = "font-weight:bold;margin-bottom:6px";
      t.textContent = "Seller Hub レポート取り";
      p.append(t);
    }
    const b = document.createElement("button");
    b.textContent = label;
    b.style.cssText = "display:block;margin:4px 0;background:#0654ba;color:#fff;border:0;border-radius:4px;padding:6px 12px;cursor:pointer";
    b.onclick = async () => { b.disabled = true; await fn(); b.disabled = false; };
    p.append(b);
  }

  // ── 新しく作る (2026-09-26 追加) ─────────────────────────────
  // 「Download report」の入力画面は Source / Type / Date range の3つの欄 (.se-field-card) で、
  // 欄を押すと選択肢が出る。選択肢の作りは未確認なので **文字で探して押し、欄の表示が
  // 狙いどおりになったか必ず確かめる**。違えば作らずに止める (間違った物を作らない)。
  const visible = (el) => !!(el && (el.offsetParent || el.getClientRects().length));
  const dialog = () => [...document.querySelectorAll(".se-dialog[role=dialog]")]
    .find((d) => !d.hidden && d.getAttribute("aria-hidden") !== "true" && visible(d.querySelector(".lightbox-dialog__window")));
  const cardValue = (cls) => txt((dialog() || document).querySelector(
    `.${cls} .se-field-card__content-description`));

  async function waitFor(fn, ms = 8000) {
    for (let t = 0; t < ms; t += 250) { const v = fn(); if (v) return v; await sleep(250); }
    return null;
  }

  function clickText(label) {
    const d = dialog();
    if (!d) return false;
    const want = label.toLowerCase();
    const hit = [...d.querySelectorAll("button,label,li,[role=radio],[role=option],[role=menuitem],span,div")]
      .filter((el) => visible(el) && txt(el).toLowerCase() === want
        && !el.closest(".se-field-card__content"));        // 欄に今出ている値は押さない
    if (!hit.length) return false;
    const el = hit[hit.length - 1];
    (el.closest("button,label,li,[role=radio],[role=option],[role=menuitem]") || el).click();
    return true;
  }

  async function choose(cls, label) {
    if (cardValue(cls).toLowerCase() === label.toLowerCase()) return true;
    const btn = (dialog() || document).querySelector(`.${cls} button.se-field-card__body`);
    if (!btn) return false;
    btn.click();
    if (!(await waitFor(() => clickText(label), 5000))) return false;
    // 選ぶと元の画面に戻る作りでなければ「戻る」を押す
    if (!(await waitFor(() => cardValue(cls).toLowerCase() === label.toLowerCase(), 3000))) {
      const back = [...(dialog() || document).querySelectorAll("button")]
        .find((b) => visible(b) && /back|戻る|done|apply/i.test(b.getAttribute("aria-label") || txt(b)));
      if (back) back.click();
    }
    return !!(await waitFor(() => cardValue(cls).toLowerCase() === label.toLowerCase(), 3000));
  }

  const MAKE = [
    { source: "Listings", type: "All active listings", label: "出品中" },
    { source: "Listings", type: "Inactive Listings", label: "売れ残り" },
    { source: "Orders", type: "All orders", label: "注文", days90: true },
    { source: "Advertising", type: "Listing", label: "広告", days90: true },
  ];

  async function makeOne(w) {
    const open = [...document.querySelectorAll("button")].find((b) => txt(b) === "Download report");
    if (!open) { log("❌ 「Download report」ボタンが見つかりません"); return false; }
    open.click();
    if (!(await waitFor(dialog))) { log(`❌ ${w.label}: 入力画面が開きません`); return false; }
    const ok = (await choose("sourceSlider", w.source)) && (await choose("typeSlider", w.type));
    // 期間: 注文と広告は90日 (広告は短いとファネルが止まる: PROMOTED_MIN_DAYS=85)
    const range = cardValue("dateRangeSlider");
    const rangeOk = !w.days90 || /90/.test(range) || (await choose("dateRangeSlider", "Last 90 Days"));
    const got = `${cardValue("sourceSlider")} / ${cardValue("typeSlider")}` + (range ? ` / ${cardValue("dateRangeSlider")}` : "");
    if (!ok || !rangeOk) {
      log(`❌ ${w.label}: 選べませんでした (今の表示: ${got})。作らずに閉じます`);
      const cancel = [...dialog().querySelectorAll("button")].find((b) => txt(b) === "Cancel");
      if (cancel) cancel.click();
      return false;
    }
    const dl = [...dialog().querySelectorAll(".lightbox-dialog__footer button")].find((b) => txt(b) === "Download");
    dl.click();
    log(`🛠 ${w.label}: 作成を頼みました (${got})`);
    // 「Creating your report / In progress」が消えるまで待つ (最大5分)
    await sleep(3000);
    // (この文言は隠れた状態で常にページにあるので、見えているかで判定する)
    const creating = () => [...document.querySelectorAll("h2,h3,p,div,span")]
      .some((el) => visible(el) && txt(el) === "Creating your report");
    await waitFor(() => !creating(), 300000);
    await sleep(2000);
    return true;
  }

  async function makeAll() {
    let n = 0;
    for (const w of MAKE) { if (await makeOne(w)) n++; await sleep(2000); }
    log(`作成: ${n}/${MAKE.length} 本。一覧で Completed になったら「まとめて取る」を押してください`);
  }

  if (location.pathname.startsWith("/sh/reports/downloads")) {
    startButton("① 新しく作る (4本)", makeAll);
    startButton("② ファネル用レポートをまとめて取る", async () => {
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
