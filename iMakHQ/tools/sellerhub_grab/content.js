// Seller Hub レポート取り — ファネルの材料4つをボタン1回で落とす (2026-09-26)。
//
// なぜ拡張か: ブラウザの自動操作ツール (Selenium) は eBay に弾かれた (「Something went wrong on
//   our end」)。いつものブラウザの拡張が画面のボタンを押す形にする。
//
// 流れ (出品くん Console が起動時に1日1回、Downloads を #shg-auto 付きで開く。ボタンでも同じ):
//   ① 4種類 (出品中 / 売れ残り / 注文 / 広告90日) を作る (20時間以内の完成品がある種類は作らない)
//   → 1分ごとに開き直して、4種類とも完成するまで待つ (最大40分)
//   ② 4種類の一番新しい Completed の Download を押す
//   → Performance に移って「Download listings quality report」を押す → タブを閉じる
// 経過は ダウンロード フォルダの sellerhub_grab_log.txt に残す (うまく行かなかった時に読む)。
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
  const FLAG_TRAFFIC = "shg_next_traffic";
  const OLD_HOURS = 48;          // これより古い完成品しか無い = Schedule が動いていない

  const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function panel() {
    let p = document.getElementById("shg-panel");
    if (p) return p;
    p = document.createElement("div");
    p.id = "shg-panel";
    p.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;background:#fff;" +
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
    try { chrome.runtime.sendMessage({ type: "log", msg }); } catch (e) { /* 拡張の再読み込み直後 */ }
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

  const FRESH_HOURS = 20;        // これより新しい完成品があれば、その晩は作り直さない
  const ageH = (r) => (r && r.when ? (Date.now() - r.when.getTime()) / 3600e3 : 999);
  const newest = (all, w, status) => all.find((x) => x.source === w.source
    && x.type.toLowerCase() === w.type.toLowerCase() && (!status || x.status === status));

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

  // 画面の押せる物と、開いている小窓の中身を控える (ダウンロード フォルダの sellerhub_traffic_dump_N.txt)
  let dumpN = 0;
  function dumpPage() {
    // ★2026-10-04: 画面全体だと大きすぎてファイルにならなかった → 「Your listings」の周りと、文字の無いボタンだけ控える
    dumpN += 1;
    const head = [...document.querySelectorAll("h1,h2,h3,h4")].find((h) => /Your listings/i.test(txt(h)));
    let box = head ? head.parentElement : null;
    for (let i = 0; box && i < 3 && box.parentElement && !box.querySelector("table"); i++) box = box.parentElement;
    let around = "";
    if (box) {
      const c = box.cloneNode(true);
      c.querySelectorAll("table, tbody, img").forEach((t) => t.remove());
      around = c.outerHTML.slice(0, 20000);
    }
    const iconBtns = [...document.querySelectorAll("button, [role=button], a")].filter(visible)
      .filter((b) => !txt(b)).map((b) => b.outerHTML.slice(0, 600));
    const named = [...document.querySelectorAll("button, [role=button], a")].filter(visible)
      .filter((b) => /download|export/i.test((b.getAttribute("aria-label") || "") + " " + txt(b)))
      .map((b) => b.outerHTML.slice(0, 600));
    const text = [`URL ${location.href}`, `時刻 ${new Date().toLocaleString()}`,
                  `見出し Your listings ${head ? "あり" : "なし"}`, "", "== download/export の名前のボタン", ...named,
                  "", "== 文字の無いボタン", ...iconBtns.slice(0, 60), "", "== Your listings の周り", around].join("\r\n");
    chrome.runtime.sendMessage({ type: "dump", n: dumpN, text });
    log(`✅ 控えた (${dumpN}回目・${Math.round(text.length / 1000)}KB)。ダウンロードに sellerhub_traffic_dump_${dumpN}.txt`);
  }

  // ★2026-10-05 オファーを画面から送る (カウンターを受けるため・API では受けられない) 前に、
  //   「Send offer」の小窓の作りを控える。押す所を推測で作らない (1回で作り切るため)
  let offerDumpN = 0;
  function dumpOffer() {
    offerDumpN += 1;
    const strip = (el) => {
      const c = el.cloneNode(true);
      c.querySelectorAll("img, svg, script, style").forEach((t) => t.remove());
      return c.outerHTML;
    };
    const dialogs = [...document.querySelectorAll("[role=dialog], [aria-modal=true], .lightbox-dialog, .drawer-dialog, " +
      "[class*=dialog], [class*=drawer], [class*=modal], [class*=panel]")]
      .filter(visible).filter((d) => /offer/i.test(txt(d)))
      .filter((d, i, all) => !all.some((o) => o !== d && o.contains(d)))     // 一番外側だけ
      .map((d) => strip(d).slice(0, 60000));
    // ★2.8: 小窓の作りが分からなくても拾えるよう、見えている入力欄の周り (6段上まで) も控える
    const inputs = [...document.querySelectorAll("input:not([type=checkbox]):not([type=hidden]), textarea, input[type=checkbox]")]
      .filter(visible).filter((el) => !el.closest("tr") && !el.closest("header"))
      .map((el) => { let b = el; for (let i = 0; i < 6 && b.parentElement; i++) b = b.parentElement; return b; })
      .filter((b, i, all) => all.indexOf(b) === i).map((b) => strip(b).slice(0, 20000));
    dialogs.push(...inputs.map((s) => "<!-- 入力欄の周り -->" + s));
    const offerBtns = [...document.querySelectorAll("button, [role=button], a, [role=menuitem]")].filter(visible)
      .filter((b) => /offer/i.test((b.getAttribute("aria-label") || "") + " " + txt(b)))
      .map((b) => b.outerHTML.slice(0, 800));
    const row = [...document.querySelectorAll("tr")].find((r) => /\d{12}/.test(txt(r)));
    const text = [`URL ${location.href}`, `時刻 ${new Date().toLocaleString()}`,
                  `開いている小窓 ${dialogs.length}`, "", "== offer の名前の付いた押せる物", ...offerBtns,
                  "", "== 小窓の中身", ...dialogs,
                  "", "== 一覧の1行目", row ? strip(row).slice(0, 20000) : "(無し)"].join("\r\n");
    chrome.runtime.sendMessage({ type: "dump", n: offerDumpN, text, name: "sellerhub_offer_dump" });
    log(`✅ 控えた (${offerDumpN}回目・${Math.round(text.length / 1000)}KB)。ダウンロードに sellerhub_offer_dump_${offerDumpN}.txt`);
  }

  // ---------------------------------------------------------------- オファーを送る (2026-10-05)
  // 送る一覧は神風 (tools/shelf_offer.py) が作る。拡張は1件ずつ:
  //   神風に「広告を外して」→ 行の Send offers → Percent off に % / 自動オファーを外す / カウンター可 /
  //   メッセージ → Send offers → 神風に「送った」(台帳に期限96時間)。
  //   小窓の作りは 2026-10-05 8:02 の控え (sellerhub_offer_dump) で確かめた物だけを使う。
  const OFFER_MSG = "Thank you for watching this item! Here is a special price just for you. " +
    "This offer is valid for a limited time.";

  function api(method, path, body) {
    return new Promise((res) => {
      try {
        chrome.runtime.sendMessage({ type: "api", method, path, body }, (r) => res(r || { ok: false, error: "返事なし" }));
      } catch (e) { res({ ok: false, error: String(e) }); }
    });
  }

  function liveOfferDialog() {
    return [...document.querySelectorAll("[data-testid=sio-modal-root]")]
      .find((m) => !m.hasAttribute("hidden") && visible(m) && /counteroffer/i.test(txt(m))) || null;
  }

  function setValue(el, v) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, String(v));
    for (const t of ["input", "change", "blur"]) el.dispatchEvent(new Event(t, { bubbles: true }));
  }

  async function fillOffer(item) {
    const d = await waitFor(() => {
      const m = liveOfferDialog();
      const inp = m && m.querySelector("[data-testid=discount-value-input] input:not([disabled])");
      return inp ? m : null;
    }, 20000);
    if (!d) return "小窓が開かない";
    const body = txt(d);
    if (!/1 item selected/i.test(body) || !/Eligible \(1\)/.test(body)) return "小窓の対象が1件ではない";
    const head = (item.title || "").slice(0, 25);
    if (head && !body.includes(head)) return "小窓の出品が違う";
    const typeBtn = d.querySelector("[data-testid=discount-type-select-button] button");
    if (!typeBtn || !/Percent off/i.test(txt(typeBtn))) {
      if (typeBtn) typeBtn.click();
      await sleep(400);
      const opt = d.querySelector("[data-testid=discount-type-PERCENTAGE_OFF]");
      if (!opt) return "割引の種類 (Percent off) を選べない";
      opt.click();
      await sleep(400);
    }
    setValue(d.querySelector("[data-testid=discount-value-input] input"), item.pct);
    const auto = d.querySelector("[data-testid=automated-offer-section] input[type=checkbox]");
    if (auto && auto.checked) auto.click();                    // eBay の自動オファーは使わない
    const counter = d.querySelector("[data-testid=counter-offer-section] input[type=checkbox]");
    if (counter && !counter.checked) counter.click();          // カウンターは受ける
    const msg = d.querySelector("[data-testid=offer-message-input] textarea");
    if (msg) setValue(msg, OFFER_MSG);
    await sleep(800);
    if (auto && auto.checked) return "自動オファーのチェックが外れない";
    if (!counter || !counter.checked) return "カウンターのチェックが入らない";
    const pv = d.querySelector("[data-testid=discount-value-input] input").value;
    if (String(pv) !== String(item.pct)) return `割引率が入らない (${pv})`;
    return d;
  }

  function cancelDialog() {
    const d = liveOfferDialog();
    const c = d && d.querySelector("[data-testid=cancel-button]");
    if (c) c.click();
  }

  async function sendOffers(mode) {
    // mode: "try" = 1件を小窓に入れるまで (送らない) / "one" = 1件送る / "all" = 全部送る
    const w = await api("GET", "/api/offers/waiting");
    const items = (w && w.items) || [];
    if (!items.length) { log("送る一覧が空です (神風の「💌 オファーの送る一覧を作る」を先に)"); return; }
    if (!/offers=sendNewOffers/.test(location.search)) {
      log("「Send offers - eligible」の一覧に移って、そのまま続けます");
      sessionStorage.setItem("shg_offer_mode", mode);          // ★3.2: 移った後に自動で続ける
      location.href = "https://www.ebay.com/sh/lst/active?offers=sendNewOffers&source=filterbar&action=search";
      return;
    }
    for (let i = 0; i < 40 && !document.querySelector("tr[data-id]"); i++) await sleep(500);
    let sent = 0, skipped = 0;
    for (const item of items) {
      const row = document.querySelector(`tr[data-id="${item.item_id}"]`);
      if (!row) { log(`✗ ${item.item_id} 一覧に無い (もう送れない出品)`); skipped++; continue; }
      const btn = [...row.querySelectorAll("button.primary-action__button")].find((b) => /Send offers/i.test(txt(b)));
      if (!btn) { log(`✗ ${item.item_id} 行に Send offers が無い`); skipped++; continue; }
      if (mode !== "try") {
        const p = await api("POST", "/api/offers/prepare", { item_id: item.item_id });
        if (!p || !p.ok) { log(`✗ ${item.item_id} 広告を外せず送らない (${(p && p.error) || ""})`); skipped++; continue; }
      }
      btn.click();
      const d = await fillOffer(item);
      if (typeof d === "string") { log(`✗ ${item.item_id} ${d} → 閉じます`); cancelDialog(); skipped++; await sleep(1500); continue; }
      if (mode === "try") {
        log(`✅ 試し: ${item.item_id} を ${item.pct}%引き・自動オファー無し・カウンター可 で入れました。送らずに止めます (小窓を見て Cancel で閉じてください)`);
        return;
      }
      const submit = await waitFor(() => {
        const b = d.querySelector("[data-testid=submit-button]");
        return b && !b.disabled ? b : null;
      }, 10000);
      if (!submit) { log(`✗ ${item.item_id} Send offers が押せない → 閉じます`); cancelDialog(); skipped++; await sleep(1500); continue; }
      submit.click();
      const closed = await waitFor(() => (liveOfferDialog() ? null : true), 20000);
      if (!closed) { log(`⚠ ${item.item_id} 送った後に小窓が閉じない → 送れたか画面で確かめてください (台帳には入れません)`); return; }
      const m = await api("POST", "/api/offers/sent", { item_id: item.item_id, pct: item.pct });
      log(`💌 送った: ${item.item_id} ${item.pct}%引き (下限 $${item.floor})${m && m.ok ? "" : " ⚠台帳に入らず"}`);
      sent++;
      await sleep(2500);
      if (mode === "one") break;
    }
    log(`終わり: 送った ${sent}件 / 送れなかった ${skipped}件`);
  }

  // 「Your listings」の欄の右の ↓ (Download)。名前 (aria-label / title / 文字 / 絵の名前) に download が入る物を探す。
  //   1つに決まらなければ押さない (間違った物を押さない)
  function trafficButton() {
    // ★2026-10-04 画面の控えで確かめた: ↓ は aria-label「Download active listings traffic report」の icon-btn。
    //   名前で1つに決める (前は「download」を含む物を探していて、品質レポートのボタンを押していた)
    const hits = [...document.querySelectorAll("button[aria-label]")].filter(visible)
      .filter((b) => /^Download active listings traffic report$/i.test(b.getAttribute("aria-label").trim()));
    return hits.length === 1 ? hits[0] : (hits.length ? hits : null);
  }

  async function grabTraffic() {
    let b = null;
    for (let i = 0; i < 30 && !(b = trafficButton()); i++) await sleep(500);
    if (!b) { log("❌ トラフィックの ↓ (Download) が見つかりません。画面の作りを控えるボタンを押して HQ に知らせてください"); return; }
    if (Array.isArray(b)) { log(`❌ ↓ の候補が ${b.length}個あって決められません (押していません)`); return; }
    b.click();
    log("✅ トラフィックレポート: 押しました (前の90日との比較つき)");
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
    log("✅ 品質レポートまで押しました。続けてトラフィックレポートを取ります");
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
  // 欄を押すと選択肢の小窓が出る。選択肢は **文字で探して押し、欄の表示が
  // 狙いどおりになったか必ず確かめる**。違えば作らずに止める (間違った物を作らない)。
  const visible = (el) => !!(el && (el.offsetParent || el.getClientRects().length));
  const dialog = () => [...document.querySelectorAll(".se-dialog[role=dialog]")]
    .find((d) => !d.hidden && d.getAttribute("aria-hidden") !== "true" && visible(d.querySelector(".lightbox-dialog__window")));
  const cardValue = (cls) => txt((dialog() || document.querySelector(".se-dialog") || document)
    .querySelector(`.${cls} .se-field-card__content-description`));

  async function waitFor(fn, ms = 8000) {
    for (let t = 0; t < ms; t += 250) { const v = fn(); if (v) return v; await sleep(250); }
    return null;
  }

  // 欄を押すと、入力画面の **外に** 選択肢の小窓 (.flyout-pane) が出る。中身はラジオボタンと
  // label.field__label、上に「Done」(.btn-done-link)。(2026-09-26 保存した画面で確認)
  const pane = () => [...document.querySelectorAll(".flyout-pane")]
    .find((p) => !p.hidden && p.getAttribute("aria-hidden") !== "true" && visible(p.querySelector(".flyout-pane__window")));

  function clickOption(label) {
    const p = pane();
    if (!p) return false;
    const want = label.toLowerCase();
    const lb = [...p.querySelectorAll("label.field__label, label")].find((l) => txt(l).toLowerCase() === want);
    if (!lb) return false;
    const input = lb.htmlFor ? document.getElementById(lb.htmlFor) : null;
    (input || lb).click();
    return true;
  }

  async function choose(cls, label) {
    if (cardValue(cls).toLowerCase() === label.toLowerCase()) return true;
    const btn = (dialog() || document).querySelector(`.${cls} button.se-field-card__body`);
    if (!btn) return false;
    btn.click();
    if (!(await waitFor(pane, 5000))) return false;
    if (!(await waitFor(() => clickOption(label), 5000))) {
      const p = pane();
      log(`   (選択肢: ${p ? [...p.querySelectorAll("label")].map(txt).join(" / ") : "なし"})`);
      const done0 = p && p.querySelector(".btn-done-link");
      if (done0) done0.click();
      return false;
    }
    await sleep(500);
    const p = pane();
    const done = p && p.querySelector(".btn-done-link");
    if (done) done.click();
    return !!(await waitFor(() => cardValue(cls).toLowerCase() === label.toLowerCase(), 4000));
  }

  const MAKE = [
    { source: "Listings", type: "All active listings", label: "出品中" },
    { source: "Listings", type: "Inactive Listings", label: "売れ残り" },
    { source: "Orders", type: "All orders", label: "注文", days90: true },
    { source: "Advertising", strategy: "Promoted Listings - General", type: "Listing", label: "広告", days90: true },
  ];

  async function makeOne(w) {
    const open = [...document.querySelectorAll("button")].find((b) => txt(b) === "Download report");
    if (!open) { log("❌ 「Download report」ボタンが見つかりません"); return false; }
    open.click();
    if (!(await waitFor(dialog))) { log(`❌ ${w.label}: 入力画面が開きません`); return false; }
    let ok = await choose("sourceSlider", w.source);
    // ★広告は Source を変えた後に Campaign strategy / Type の欄が遅れて出る (表示が空のまま選ぼうとして止まった)
    if (ok) await waitFor(() => cardValue("typeSlider"), 8000);
    if (ok && w.strategy) ok = await choose("campaignTypeSlider", w.strategy);
    if (ok) ok = await choose("typeSlider", w.type);
    // 期間: 注文と広告は90日 (広告は短いとファネルが止まる: PROMOTED_MIN_DAYS=85)
    const range = cardValue("dateRangeSlider");
    const rangeOk = !w.days90 || /90/.test(range) || (await choose("dateRangeSlider", "Last 90 Days"));
    const got = `${cardValue("sourceSlider")} / ${cardValue("typeSlider")}` + (range ? ` / ${cardValue("dateRangeSlider")}` : "");
    if (!ok || !rangeOk) {
      log(`❌ ${w.label}: 選べませんでした (今の表示: ${got})。作らずに閉じます`);
      const cancel = [...(dialog() || document).querySelectorAll(".lightbox-dialog__footer button")].find((b) => txt(b) === "Cancel");
      if (cancel) cancel.click();
      return false;
    }
    const dl = [...(dialog() || document).querySelectorAll(".lightbox-dialog__footer button")]
      .find((b) => txt(b) === "Download" && !b.disabled);
    if (!dl) { log(`❌ ${w.label}: Download が押せる状態になりません (${got})`); return false; }
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

  async function makeAll(onlyMissing) {
    let n = 0, skip = 0;
    for (const w of MAKE) {
      // 作成中 / 20時間以内の完成品がある種類は作らない (夜中に何度も作り直さない)
      const r = newest(rows(), w);
      if (onlyMissing && r && ageH(r) < FRESH_HOURS && r.status !== "Failed") { skip++; continue; }
      if (await makeOne(w)) n++;
      await sleep(2000);
    }
    log(`作成: ${n}本を頼みました` + (skip ? ` (新しい物がある ${skip}本は作らず)` : ""));
    return n;
  }

  // ── 自動 (出品くん Console が #shg-auto 付きで開く) ─────────────
  const STAGE = "shg_auto_stage", T0 = "shg_auto_t0";
  const MAX_WAIT_MIN = 40;

  function allFresh() {
    const all = rows();
    return MAKE.every((w) => { const r = newest(all, w, "Completed"); return r && ageH(r) < FRESH_HOURS; });
  }

  function finish(ok) {
    sessionStorage.removeItem(STAGE);
    log(ok ? "🎉 自動: 完了" : "⚠️ 自動: 途中で止まりました (上の行を見てください)");
    try { chrome.runtime.sendMessage({ type: "done", ok }); } catch (e) { /* noop */ }
  }

  async function autoDownloads() {
    if (location.hash === "#shg-auto" && !sessionStorage.getItem(STAGE)) {
      sessionStorage.setItem(STAGE, "make");
      sessionStorage.setItem(T0, String(Date.now()));
      try { chrome.runtime.sendMessage({ type: "start" }); } catch (e) { /* noop */ }
      history.replaceState(null, "", location.pathname + location.search);
    }
    const stage = sessionStorage.getItem(STAGE);
    if (!stage || stage === "lqr") return false;
    panel();
    for (let i = 0; i < 40 && !rows().length; i++) await sleep(500);   // 一覧が出るまで待つ
    if (stage === "make") {
      log("自動: レポートを作ります");
      await makeAll(true);
      sessionStorage.setItem(STAGE, "wait");
    }
    if (allFresh()) {
      await grabDownloads();
      sessionStorage.setItem(STAGE, "lqr");
      await sleep(3000);
      location.href = "https://www.ebay.com/sh/performance";
      return true;
    }
    const waited = (Date.now() - Number(sessionStorage.getItem(T0) || Date.now())) / 60000;
    if (waited > MAX_WAIT_MIN) {
      const all = rows();
      log("❌ " + MAX_WAIT_MIN + "分待っても完成しない: " + MAKE.filter((w) => {
        const r = newest(all, w, "Completed"); return !(r && ageH(r) < FRESH_HOURS);
      }).map((w) => w.label).join("・"));
      finish(false);
      return true;
    }
    log(`完成待ち (${Math.round(waited)}分経過)… 1分後に開き直します`);
    await sleep(60000);
    location.reload();
    return true;
  }

  if (location.pathname.startsWith("/sh/reports/downloads")) {
    autoDownloads().then((running) => {
      if (running) return;
      startButton("① 新しく作る (4本)", () => makeAll(false));
      startButton("② ファネル用レポートをまとめて取る", async () => {
        if (await grabDownloads()) {
          sessionStorage.setItem(FLAG, "1");
          log("→ 品質レポートの画面へ移ります…");
          await sleep(3000);
          location.href = "https://www.ebay.com/sh/performance";
        }
      });
      startButton("③ 自動 (作成→取得) を今すぐ", () => { location.hash = "shg-auto"; location.reload(); });
    });
  }
  // ★2026-10-05 (3.3): 出品中一覧でのオファー送り (3.1〜3.2) はやめた (ユーザー判断: こちらからオファーを送らない)。
  //   sendOffers 等の関数は残すが、どのページからも呼ばない (manifest からも出品中一覧を外した)
  if (location.pathname.startsWith("/sh/performance/traffic")) {
    // ★2026-10-04 トラフィックレポート (前の90日との比較つき) も毎日落とす (棚② の「埋もれた」判定)。
    //   ユーザー「小窓でないよ。右の↓をおすだけ」: 「Your listings」の欄の右の ↓ (Download) を押す
    if (sessionStorage.getItem(STAGE) === "traffic") {
      panel();
      log("自動 (続き): トラフィックレポート");
      grabTraffic().then(async () => { await sleep(20000); finish(true); });
    } else if (sessionStorage.getItem(FLAG_TRAFFIC) === "1") {
      sessionStorage.removeItem(FLAG_TRAFFIC);
      panel();
      log("Seller Hub レポート取り (続き): トラフィックレポート");
      grabTraffic().then(() => log("✅ 6つとも押しました。夜のバッチがファネルの置き場へ移します"));
    } else {
      startButton("トラフィックレポートだけ取る", grabTraffic);
      startButton("画面の作りを控える (HQ 用)", dumpPage);
    }
  } else if (location.pathname.startsWith("/sh/performance")) {
    if (sessionStorage.getItem(STAGE) === "lqr") {
      panel();
      log("自動 (続き): 品質レポート");
      // ★2026-10-04: 品質レポートの後にトラフィックレポートも取る
      grabLqr().then(async () => {
        await sleep(30000);
        sessionStorage.setItem(STAGE, "traffic");
        location.href = "https://www.ebay.com/sh/performance/traffic";
      });
    } else if (sessionStorage.getItem(FLAG) === "1") {
      sessionStorage.removeItem(FLAG);
      panel();
      log("Seller Hub レポート取り (続き)");
      grabLqr().then(async () => {
        await sleep(30000);
        sessionStorage.setItem(FLAG_TRAFFIC, "1");
        location.href = "https://www.ebay.com/sh/performance/traffic";
      });
    } else {
      startButton("品質レポートだけ取る", grabLqr);
    }
  }
})();
