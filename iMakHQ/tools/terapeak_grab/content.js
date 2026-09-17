// Terapeak 抜き出し — eBay Seller Hub > Research で表示中の一覧を取って CSV にする。
// 自動でページ送りはしない。人が捲って、その画面に出ているものを写すだけ。
(() => {
  "use strict";

  const ROWS_KEY = "tpg_rows_v1";

  const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  // セルは <div><div>値</div><div class="format">補足</div></div> の形
  const cellValue = (td) => txt(td ? td.querySelector("div > div") : null);
  const cellNote = (td) => txt(td ? td.querySelector(".format") : null);
  // 隠れているタブ (Sold を見ている時の Active) は中身が空なので拾わない
  const visible = (el) => !!(el && (el.offsetParent || el.getClientRects().length));
  const show = (sel) => [...document.querySelectorAll(sel)].filter(visible);

  // 出品が終わっている行はリンクが無く、題名が画像の alt にしか無い
  function titleOf(tr, a) {
    return txt(a) || (tr.querySelector("img[alt]") || {}).alt || "";
  }

  function context() {
    const u = new URL(location.href);
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return {
      取得日時: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`,
      検索語: u.searchParams.get("keywords") || "",
      期間: txt(document.querySelector(".results-header__left span")),
      条件: u.search.replace(/^\?/, ""),
    };
  }

  function parseSold(ctx) {
    return show("tr.research-table-row").map((tr) => {
      const a = tr.querySelector(".research-table-row__product-info a");
      const idEl = tr.querySelector("[data-item-id]");
      const id = idEl ? idEl.getAttribute("data-item-id") : "";
      const price = tr.querySelector(".research-table-row__avgSoldPrice");
      const ship = tr.querySelector(".research-table-row__avgShippingCost");
      return {
        種別: "Sold",
        ...ctx,
        itemId: id,
        タイトル: titleOf(tr, a),
        平均落札: cellValue(price),
        形式: cellNote(price),
        平均送料: cellValue(ship),
        送料無料率: cellNote(ship),
        売れた数: cellValue(tr.querySelector(".research-table-row__totalSoldCount")),
        売上合計: cellValue(tr.querySelector(".research-table-row__totalSalesValue")),
        入札: cellValue(tr.querySelector(".research-table-row__bids")),
        最終落札日: cellValue(tr.querySelector(".research-table-row__dateLastSold")),
        URL: a ? a.href.split("?")[0] : id ? `https://www.ebay.com/itm/${id}` : "",
      };
    });
  }

  function parseActive(ctx) {
    return show("tr.active-listing-row").map((tr) => {
      const a = tr.querySelector(".active-listing-row__product-info a");
      const idEl = tr.querySelector("[data-item-id]");
      const id = idEl ? idEl.getAttribute("data-item-id") : "";
      const price = tr.querySelector(".active-listing-row__listingPrice");
      return {
        種別: "Active",
        ...ctx,
        itemId: id,
        タイトル: titleOf(tr, a),
        出品価格: cellValue(price),
        形式: cellNote(price),
        入札: cellValue(tr.querySelector(".active-listing-row__bids")),
        ウォッチ: cellValue(tr.querySelector(".active-listing-row__watchers")),
        プロモ: cellValue(tr.querySelector(".active-listing-row__promotedListing")),
        開始日: cellValue(tr.querySelector(".active-listing-row__startedDate")),
        URL: a ? a.href.split("?")[0] : id ? `https://www.ebay.com/itm/${id}` : "",
      };
    });
  }


  // ---- 保存 (重複は itemId + 種別 + 検索語 で落とす) ----
  const load = (key) =>
    new Promise((res) => chrome.storage.local.get([key], (o) => res(o[key] || [])));
  const save = (key, val) =>
    new Promise((res) => chrome.storage.local.set({ [key]: val }, res));

  async function capture(silent) {
    const ctx = context();
    const rows = [...parseSold(ctx), ...parseActive(ctx)].filter((r) => r.itemId);
    if (!rows.length) {
      if (!silent) msg("この画面に一覧が見つかりません", true);
      return 0;
    }
    const kept = await load(ROWS_KEY);
    const seen = new Set(kept.map((r) => `${r.種別}|${r.検索語}|${r.itemId}`));
    let added = 0;
    for (const r of rows) {
      const k = `${r.種別}|${r.検索語}|${r.itemId}`;
      if (seen.has(k)) continue;
      seen.add(k);
      kept.push(r);
      added++;
    }
    await save(ROWS_KEY, kept);

    await refresh();
    if (added || !silent) {
      msg(added ? `${added}件 取りました` : "新しい行はありません (取得済み)", !added);
    }
    return added;
  }

  // ---- CSV ----
  function toCsv(rows) {
    const cols = [];
    for (const r of rows) for (const k of Object.keys(r)) if (!cols.includes(k)) cols.push(k);
    const esc = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
    return (
      "﻿" +
      [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\r\n")
    );
  }

  function download(name, text) {
    const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  function stamp() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
  }

  async function exportCsv() {
    const rows = await load(ROWS_KEY);
    if (!rows.length) return msg("まだ1件も取っていません", true);
    download(`terapeak_${stamp()}.csv`, toCsv(rows));
    msg(`${rows.length}件を CSV に出しました (ダウンロード)`);
  }

  async function copyClip() {
    const rows = await load(ROWS_KEY);
    if (!rows.length) return msg("まだ1件も取っていません", true);
    const cols = [];
    for (const r of rows) for (const k of Object.keys(r)) if (!cols.includes(k)) cols.push(k);
    const tsv = [
      cols.join("\t"),
      ...rows.map((r) => cols.map((c) => String(r[c] ?? "").replace(/[\t\r\n]/g, " ")).join("\t")),
    ].join("\r\n");
    try {
      await navigator.clipboard.writeText(tsv);
      msg(`${rows.length}件をコピーしました (そのまま貼れます)`);
    } catch (e) {
      msg("コピーできませんでした (CSVで出してください)", true);
    }
  }

  async function clearAll() {
    if (!confirm("溜めた行を全部消します。よろしいですか?")) return;
    await save(ROWS_KEY, []);
    await refresh();
    msg("消しました");
  }

  // ---- 画面 ----
  let panel, countEl, msgEl, autoBox;

  function msg(t, warn) {
    if (!msgEl) return;
    msgEl.textContent = t;
    msgEl.className = warn ? "warn" : "";
    clearTimeout(msg._t);
    msg._t = setTimeout(() => (msgEl.textContent = ""), 6000);
  }

  async function refresh() {
    const rows = await load(ROWS_KEY);
    const sold = rows.filter((r) => r.種別 === "Sold").length;
    countEl.innerHTML = `${rows.length}<small>件 溜まっています (Sold ${sold})</small>`;
  }

  function build() {
    panel = document.createElement("div");
    panel.id = "tpg-panel";
    panel.innerHTML = `
      <div id="tpg-head"><span>Terapeak 抜き出し</span><button id="tpg-fold" title="たたむ">–</button></div>
      <div class="tpg-body">
        <div id="tpg-count">0<small>件</small></div>
        <button class="tpg-btn" id="tpg-take">この画面を取る</button>
        <button class="tpg-btn sub" id="tpg-csv">CSVで出す</button>
        <button class="tpg-btn sub" id="tpg-clip">コピー (貼り付け用)</button>
        <label id="tpg-auto"><input type="checkbox" id="tpg-auto-cb"> ページを捲ったら自動で取る</label>
        <button class="tpg-btn danger" id="tpg-clear">全部消す</button>
        <div id="tpg-msg"></div>
      </div>`;
    document.body.appendChild(panel);
    countEl = panel.querySelector("#tpg-count");
    msgEl = panel.querySelector("#tpg-msg");
    autoBox = panel.querySelector("#tpg-auto-cb");

    panel.querySelector("#tpg-take").onclick = () => capture(false);
    panel.querySelector("#tpg-csv").onclick = exportCsv;
    panel.querySelector("#tpg-clip").onclick = copyClip;
    panel.querySelector("#tpg-clear").onclick = clearAll;
    panel.querySelector("#tpg-fold").onclick = () => panel.classList.toggle("tpg-min");

    // ページを捲って表が入れ替わったら取る (捲るのは人)
    let timer = null;
    new MutationObserver(() => {
      if (!autoBox.checked) return;
      clearTimeout(timer);
      timer = setTimeout(() => capture(true), 1200);
    }).observe(document.body, { childList: true, subtree: true });

    refresh();
  }

  if (document.body) build();
  else window.addEventListener("DOMContentLoaded", build);
})();
