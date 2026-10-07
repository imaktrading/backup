/* 神風「メッセージ」タブ (2026-10-08)。見本 https://claude.ai/artifact/Kw21VoqCCJHnpSaTHkymo9 の形。
   裏で取った一覧 (GET /api/messages) を読むだけ。送る時は確認を1回挟む。 */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var D = null, sel = null, filt = "all", drafts = {};
  var STAGE = { paid: "支払い済み", shipped: "発送済み", arrived: "到着", ask: "買う前の質問" };
  var STEPS = ["paid", "shipped", "arrived"];

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function post(u, b) {
    return fetch(u, { method: "POST", headers: { "Content-Type": "application/json", "X-Console": "1" }, body: JSON.stringify(b || {}) })
      .then(function (r) { return r.json(); });
  }
  function when(s) { return s ? s.replace("T", " ").slice(5, 16) : ""; }
  function flag(c) { return c.country ? (c.country_name || c.country) : ""; }

  function load() {
    return fetch("/api/messages", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
      D = d; paintBadge(); paint();
      if (d.busy) setTimeout(load, 3000);
    }).catch(function () { $("msg-rows").innerHTML = '<div class="empty">読めませんでした。少し待って開き直してください</div>'; });
  }
  function paintBadge() {
    var n = (D.convs || []).filter(function (c) { return c.needs_reply || c.todo; }).length;
    var b = $("tab-msg"); if (b) { b.textContent = n ? String(n) : ""; b.hidden = !n; }
  }
  function visible() {
    return (D.convs || []).filter(function (c) {
      if (filt === "reply") return c.needs_reply;
      if (filt === "todo") return !!c.todo;
      if (filt === "ask") return c.kind === "ask";
      return true;
    });
  }
  function paint() {
    if (!D) return;
    var cs = D.convs || [];
    var nReply = cs.filter(function (c) { return c.needs_reply; }).length;
    var nTodo = cs.filter(function (c) { return c.todo; }).length;
    var nRep = cs.filter(function (c) { return c.repeat && c.kind === "order"; }).length;
    var nDdu = cs.filter(function (c) { return c.kind === "order" && c.country && c.country !== "US" && !(Number(c.tax) > 0); }).length;
    $("msg-sum").innerHTML =
      '<div class="ms' + (nReply ? " hot" : "") + '"><b>' + nReply + '</b><span>返事待ち</span></div>' +
      '<div class="ms"><b>' + nTodo + '</b><span>定型文まだ</span></div>' +
      '<div class="ms"><b>' + nRep + '</b><span>リピーターの注文</span></div>' +
      '<div class="ms"><b>' + nDdu + '</b><span>受け取り時に税がかかる注文</span></div>';
    $("msg-at").textContent = D.busy ? "取り直し中…" : (D.at ? "更新 " + when(D.at) : "まだ取っていません");
    var vs = visible();
    if (!sel || !vs.some(function (c) { return c.id === sel; })) sel = vs.length ? vs[0].id : null;
    $("msg-rows").innerHTML = vs.length ? vs.map(function (c) {
      var chips = '<span class="mc mute">' + (STAGE[c.stage] || c.stage) + "</span>";
      if (c.repeat) chips += '<span class="mc info">リピーター</span>';
      if (c.needs_reply) chips += '<span class="mc crit">返事待ち' + (c.ask ? "・" + esc((D.labels || {})[c.ask] || "") : "") + "</span>";
      if (c.todo) chips += '<span class="mc warn">' + esc((D.labels || {})[c.todo] || c.todo) + "の文まだ</span>";
      return '<button type="button" class="mrow' + (c.id === sel ? " on" : "") + '" data-id="' + esc(c.id) + '">' +
        '<span class="mwho">' + esc(c.buyer) + '</span><span class="mflag">' + esc(flag(c)) + "</span>" +
        '<span class="mitem">' + esc(c.title) + "</span>" +
        '<span class="mchips">' + chips + (c.total ? '<span class="mamt">' + esc(c.total) + " " + esc(c.currency) + "</span>" : "") + "</span></button>";
    }).join("") : '<div class="empty">この条件の注文はありません</div>';
    Array.prototype.forEach.call(document.querySelectorAll(".mrow"), function (b) {
      b.onclick = function () { sel = b.dataset.id; paint(); };
    });
    paintDetail();
  }
  function cur() { return (D.convs || []).filter(function (c) { return c.id === sel; })[0]; }

  function render(key, c) {
    var t = (D.templates || {})[key] || "";
    var url = c.track_url || "";
    var v = {
      customs: c.customs || "",
      customs_block: c.customs ? "\n" + c.customs + "\n" : "",
      carrier: c.carrier || "", tracking: c.tracking || "",
      track_url_line: url ? "Track your parcel: " + url + "\n" : "",
      tracking_sentence: c.tracking ? "Tracking number: " + c.tracking + " (" + (c.carrier || "carrier") + ")." + (url ? " " + url : "") : "",
      buyer: c.buyer || ""
    };
    Object.keys(v).forEach(function (k) { t = t.split("{" + k + "}").join(v[k]); });
    return t;
  }
  function recommend(c) {
    if (c.needs_reply && c.ask) return c.ask;
    if (c.todo) return c.todo;
    if (c.needs_reply) return "";
    return c.stage === "paid" ? (c.repeat ? "repeat" : "paid") : c.stage === "shipped" ? "shipped" : c.stage === "arrived" ? "arrived" : "";
  }
  function paintDetail() {
    var c = cur(), el = $("msg-detail");
    if (!c) { el.innerHTML = '<div class="card"><div class="empty">左の一覧から選んでください</div></div>'; return; }
    var steps = c.kind === "order" ? '<div class="msteps">' + STEPS.map(function (s, i) {
      var idx = STEPS.indexOf(c.stage);
      var cls = i < idx ? "done" : i === idx ? "now" : "";
      var sent = (c.sent || []).indexOf(s) >= 0 ? '<small>文 送った</small>' : (i <= idx ? '<small>文 まだ</small>' : "<small></small>");
      return '<div class="mst ' + cls + '">' + STAGE[s] + sent + "</div>";
    }).join("") + "</div>" : "";
    var kv = function (k, v) { return v ? '<div class="mkv"><span>' + k + "</span><b>" + v + "</b></div>" : ""; };
    var head = '<div class="card mcard"><div class="mtitle">' + esc(c.title) + "</div>" +
      '<div class="mkvs">' + kv("バイヤー", esc(c.buyer) + (c.repeat ? ' <span class="mc info">リピーター</span>' : "")) +
      kv("国", esc(flag(c))) + kv("支払額", c.total ? esc(c.total + " " + c.currency) : "") +
      kv("eBay が取った税", c.kind === "order" ? esc((c.tax || "0") + " " + (c.currency || "")) : "") +
      kv("注文番号", esc(c.kind === "order" ? c.id : "")) +
      kv("追跡", c.tracking ? (c.track_url ? '<a href="' + esc(c.track_url) + '" target="_blank" rel="noopener">' + esc(c.tracking) + "</a>" : esc(c.tracking)) + " (" + esc(c.carrier) + ")" : "") +
      "</div>" + steps +
      (c.customs ? '<div class="mtax"><b>関税</b><span>' + esc(c.customs) + "</span></div>" : "") + "</div>";
    var th = (c.thread || []).length ? (c.thread || []).map(function (m) {
      return '<div class="mmsg ' + (m.me ? "me" : "them") + '">' + esc(m.text || "(本文なし)") + '<span class="mwhen">' + esc(when(m.when)) + "</span></div>";
    }).join("") : '<div class="empty">まだやり取りはありません</div>';
    var rec = recommend(c);
    var keys = c.kind === "order" ? ["paid", "repeat", "shipped", "arrived"] : [];
    keys = keys.concat(Object.keys(D.templates || {}).filter(function (k) { return k.indexOf("ask_") === 0; }));
    var tpl = keys.map(function (k) { return '<button type="button" class="mt' + (k === rec ? " on" : "") + '" data-k="' + k + '">' + esc((D.labels || {})[k] || k) + "</button>"; }).join("");
    el.innerHTML = head +
      '<div class="card mcard"><div class="mh">やり取り</div><div class="mthread">' + th + "</div></div>" +
      '<div class="card mcard"><div class="mh">返信</div><div class="mtpls">' + tpl +
      '<button type="button" class="mt ai" id="msg-ai">AI に下書きさせる (約3円)</button></div>' +
      '<textarea id="msg-body" aria-label="返信の文"></textarea>' +
      '<div class="mbar"><button type="button" class="run hot" id="msg-send">eBay に送る</button>' +
      (c.kind === "order" && rec && ["paid", "repeat", "shipped", "arrived"].indexOf(rec) >= 0 ? '<button type="button" class="run" id="msg-mark">eBay の画面で送ったので、送った印だけ付ける</button>' : "") +
      '<span class="mnote" id="msg-note">' + esc(D.last || "") + "</span></div><div id="msg-cf"></div></div>";
    var body = $("msg-body"), kind = rec;
    body.value = drafts[c.id] != null ? drafts[c.id] : (rec ? render(rec, c) : "");
    body.oninput = function () { drafts[c.id] = body.value; };
    Array.prototype.forEach.call(el.querySelectorAll(".mt[data-k]"), function (b) {
      b.onclick = function () {
        kind = b.dataset.k; body.value = render(kind, c); drafts[c.id] = body.value;
        Array.prototype.forEach.call(el.querySelectorAll(".mt"), function (x) { x.classList.toggle("on", x === b); });
      };
    });
    $("msg-ai").onclick = function () {
      var b = this; b.disabled = true; b.textContent = "AI が書いています…";
      post("/api/messages/draft", { id: c.id }).then(function (r) {
        b.disabled = false; b.textContent = "AI に下書きさせる (約3円)";
        if (!r.ok) { $("msg-note").textContent = "⚠️ " + (r.error || "下書きできませんでした"); return; }
        kind = ""; body.value = r.text; drafts[c.id] = r.text;
        $("msg-note").textContent = "AI の下書き (約" + r.yen + "円)。確かめて直してから送ってください";
      });
    };
    $("msg-send").onclick = function () {
      $("msg-cf").innerHTML = '<div class="mconfirm"><span><b>' + esc(c.buyer) + "</b> に送ります。よろしいですか？</span>" +
        '<button type="button" class="run hot" id="msg-ok">送る</button><button type="button" class="run" id="msg-ng">やめる</button></div>';
      $("msg-ng").onclick = function () { $("msg-cf").innerHTML = ""; };
      $("msg-ok").onclick = function () {
        this.disabled = true;
        post("/api/messages/send", { id: c.id, body: body.value, kind: kind }).then(function (r) {
          $("msg-cf").innerHTML = '<div class="mconfirm' + (r.ok ? "" : " bad") + '">' + (r.ok ? "送りました" : "⚠️ 送れませんでした: " + esc(r.error)) + "</div>";
          if (r.ok) { delete drafts[c.id]; post("/api/messages/refresh").then(function () { setTimeout(load, 4000); }); }
        });
      };
    };
    var mk = $("msg-mark");
    if (mk) mk.onclick = function () {
      post("/api/messages/mark", { id: c.id, kind: rec }).then(function (r) {
        $("msg-note").textContent = r.ok ? "送った印を付けました" : "⚠️ " + (r.error || "");
        if (r.ok) { c.sent = (c.sent || []).concat([rec === "repeat" ? "paid" : rec]); c.todo = ""; paint(); }
      });
    };
  }

  $("msg-fil").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-f]"); if (!b) return;
    filt = b.dataset.f;
    Array.prototype.forEach.call(this.querySelectorAll("button"), function (x) { x.classList.toggle("on", x === b); });
    paint();
  });
  $("msg-refresh").onclick = function () {
    post("/api/messages/refresh").then(function () { $("msg-at").textContent = "取り直し中…"; setTimeout(load, 3000); });
  };
  window.MSGTAB = { load: load };
  load();     // タブの件数 (返事待ち + 定型文まだ) を最初から出す。中身はファイルを読むだけ
})();
