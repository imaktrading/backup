// SpeedPAK (Orange Connex) の追跡番号ごとの送料を神風に渡す (2026-10-09)。
//
// ★ユーザー「追跡番号が EE から始まるのは Cpass なのね。そこから送料を取ってほしい」→「Gmail じゃないよ」。
//   SpeedPAK セラーポータル (ebay-jp.orangeconnex.com) の「各注文番号の料金明細」に、
//   追跡番号 (EE… / EX…) と ご請求金額・実支払額 が1件ずつ並ぶ。
//
// 流れ: 注文の取り込み (order_purchase_sync) が送料の空いた行を見つけると、ポータルを #imak-ship 付きで Edge に開く →
//   ここが「各注文番号の料金明細」の一覧 (もっと見る) に移り、ページを送りながら表を読んで神風に渡す → タブを閉じる。
(() => {
  "use strict";
  const FLAG = "imakShipAt";
  const STAGE = "imak_ship_stage";
  const TRACK = /^E[A-Z]\d{10,}[A-Z0-9]*$/;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  const yen = (s) => { const v = parseInt(String(s || "").replace(/[^\d-]/g, ""), 10); return isNaN(v) ? null : v; };
  const api = (path, body) => new Promise((res) => {
    try { chrome.runtime.sendMessage({ type: "api", method: "POST", path, body }, (r) => res(r || {})); }
    catch (e) { res({ ok: false }); }
  });

  // 表の行 → {追跡番号: 実支払額}。列の並び: 作成時間 / 追跡番号 / ご請求金額 / 実支払額 / 割引 / 還元 / 輸送業者名 …
  function readRows() {
    const out = {};
    for (const tr of document.querySelectorAll("tr")) {
      const cells = [...tr.querySelectorAll("td")].map(txt);
      const i = cells.findIndex((c) => TRACK.test(c));
      if (i < 0) continue;
      const paid = yen(cells[i + 2]), billed = yen(cells[i + 1]);
      const v = paid != null ? paid : billed;
      if (v != null) out[cells[i]] = { yen: v, billed, at: cells[i - 1] || "", carrier: cells[i + 5] || "" };
    }
    return out;
  }

  function nextButton() {
    const b = document.querySelector(".ant-pagination-next:not(.ant-pagination-disabled) button, " +
      ".ant-pagination-next:not(.ant-pagination-disabled), .el-pagination .btn-next:not([disabled]), " +
      "button[aria-label='Next']:not([disabled]), li.next:not(.disabled) a");
    return b && !b.closest(".ant-pagination-disabled") ? b : null;
  }

  async function run() {
    let at = 0;
    for (let i = 0; i < 10 && !at; i++) {
      ({ [FLAG]: at = 0 } = await chrome.storage.local.get(FLAG));
      if (!at) await sleep(300);
    }
    if (!at || Date.now() - at > 15 * 60 * 1000) return;
    // 一覧が出るまで待つ
    for (let i = 0; i < 40 && !Object.keys(readRows()).length; i++) await sleep(500);
    // ホームなら「各注文番号の料金明細」の「もっと見る」へ (無ければホームの5件だけでも渡す)
    if (!sessionStorage.getItem(STAGE)) {
      const head = [...document.querySelectorAll("*")].find((e) => e.children.length < 3 && /各注文番号の料金明細/.test(txt(e)));
      let more = null;
      if (head) {
        let box = head;
        for (let k = 0; k < 6 && box && !more; k++) {
          box = box.parentElement;
          more = box && [...box.querySelectorAll("a, span, button")].find((e) => /もっと見る/.test(txt(e)));
        }
      }
      if (more) {
        sessionStorage.setItem(STAGE, "list");
        more.click();
        await sleep(4000);
        if (sessionStorage.getItem(STAGE) === "list" && location.pathname.includes("homePage")) {
          // 同じページの中で切り替わる作り (SPA) — そのまま続ける
        } else {
          return;                                              // ページが移った → 移った先で続きが走る
        }
      }
    }
    for (let i = 0; i < 40 && !Object.keys(readRows()).length; i++) await sleep(500);
    const all = {};
    for (let page = 0; page < 30; page++) {
      Object.assign(all, readRows());
      const nb = nextButton();
      if (!nb) break;
      const before = JSON.stringify(readRows());
      nb.click();
      for (let i = 0; i < 20 && JSON.stringify(readRows()) === before; i++) await sleep(500);
    }
    sessionStorage.removeItem(STAGE);
    await chrome.storage.local.remove(FLAG);
    const r = await api("/api/cpass/fees", { fees: all, url: location.href });
    if (r && r.ok) chrome.runtime.sendMessage({ type: "close" });
  }

  run();
})();
