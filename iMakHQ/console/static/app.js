(function () {
  "use strict";
  var GROUPS = [["hoju", "補URL"], ["restock", "再仕入れ"], ["shelf", "取下げ・棚"], ["seed", "種・目視特定"]];
  var STATE_LABEL = { todo: "要対応", night: "夜間で自動", hold: "止めている", done: "残りなし", error: "数えられない", unknown: "未集計" };
  var CLOCKS = [["US", "NY", "America/New_York"], ["GB", "LON", "Europe/London"], ["DE", "BER", "Europe/Berlin"], ["AU", "SYD", "Australia/Sydney"]];
  var logAfter = 0, jobs = [], running = null, toastTimer;

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function money(v) {
    if (v == null) return "—";
    var a = Math.abs(v);
    if (a >= 1e6) return "$" + (v / 1e6).toFixed(2) + "M";
    return "$" + Math.round(v).toLocaleString("en-US");
  }
  function say(msg) { var t = $("toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove("show"); }, 3200); }
  function getJSON(url) { return fetch(url, { cache: "no-store" }).then(function (r) { return r.json(); }); }
  function post(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Console": "1" }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); });
  }

  // ---- 時刻
  function paintClocks() {
    var now = new Date();
    $("today-date").textContent = new Intl.DateTimeFormat("ja-JP", { month: "long", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit" }).format(now) + " 時点";
    $("clocks").innerHTML = CLOCKS.map(function (c) {
      var hm = new Intl.DateTimeFormat("en-GB", { timeZone: c[2], hour: "2-digit", minute: "2-digit", hour12: false }).format(now);
      var h = parseInt(hm.slice(0, 2), 10);
      var awake = h >= 8 && h < 23;
      return '<div class="clk"><span class="cc">' + c[0] + '</span><span class="t">' + hm + "<small>" + c[1] + '</small></span><span class="st' + (awake ? " live" : "") + '">' + (awake ? "起きている時間" : "夜") + "</span></div>";
    }).join("");
  }

  // ---- 作業
  function paintJobs(data) {
    jobs = data.jobs || [];
    var at = data.counts_at ? data.counts_at.replace("T", " ").slice(5, 16) : "まだ数えていません";
    $("counts-foot").textContent = (data.counting ? "件数 数え直し中… " : "件数 ") + at + (data.counts_error ? " (失敗)" : "");
    $("btn-refresh").disabled = !!data.counting;
    $("btn-refresh").textContent = data.counting ? "数え直し中…" : "残件を数え直す";

    var todo = jobs.filter(function (j) { return j.state === "todo"; });
    var total = todo.reduce(function (a, j) { return a + (j.n || 0); }, 0);
    $("st-todo").textContent = total.toLocaleString("ja-JP");
    $("st-todo-n").textContent = todo.length + " 種類";
    $("nav-today").textContent = todo.length;

    GROUPS.forEach(function (g) {
      var n = jobs.filter(function (j) { return j.group === g[0] && j.state === "todo"; }).reduce(function (a, j) { return a + (j.n || 0); }, 0);
      var el = $("nav-" + g[0]);
      el.textContent = n || "0";
      el.classList.toggle("zero", !n);
    });

    var q = todo.slice().sort(function (a, b) { return (b.n || 0) - (a.n || 0); }).slice(0, 6);
    $("queue").innerHTML = q.length ? q.map(function (j) {
      return '<div class="task"><div class="cat">' + esc(GROUPS.filter(function (g) { return g[0] === j.group; })[0][1]) + (j.step ? " · " + j.step : "") + '</div>' +
        '<div class="name">' + esc(j.label) + "</div>" +
        '<div class="row"><div class="big">' + (j.n == null ? "—" : j.n) + "<small>件</small></div>" + runButton(j, true) + "</div>" +
        '<div class="why">' + esc(j.note || j.tip.split("。")[0]) + "</div></div>";
    }).join("") : '<div class="empty">押さないと減らない残件はありません</div>';

    var rows = ['<table class="jobs"><thead><tr><th>作業</th><th>状態</th><th style="text-align:right">残り</th><th></th></tr></thead><tbody>'];
    GROUPS.forEach(function (g) {
      var gj = jobs.filter(function (j) { return j.group === g[0]; });
      if (!gj.length) return;
      rows.push('<tr class="gh" id="g-' + g[0] + '"><td colspan="4">' + g[1] + "</td></tr>");
      gj.forEach(function (j) {
        var chip = j.state === "hold" ? "止めている " + j.hold : STATE_LABEL[j.state] || j.state;
        rows.push('<tr class="jr"><td><span class="jn">' + esc(j.label) + '</span><div class="jd">' + esc(j.state === "error" ? j.note : (j.note || "")) + "</div></td>" +
          '<td><span class="chip ' + esc(j.state) + '">' + esc(chip) + "</span></td>" +
          '<td class="num">' + (j.n == null ? "—" : j.n) + "</td>" +
          '<td class="go">' + runButton(j, j.state === "todo") + "</td></tr>");
      });
    });
    rows.push("</tbody></table>");
    $("jobs").innerHTML = rows.join("");
  }

  function runButton(j, hot) {
    if (!j.runnable) return '<span class="elsewhere">今の出品くんで</span>';
    var busy = running && running.running;
    return '<button class="run' + (hot ? " hot" : "") + '" type="button" data-kind="' + esc(j.kind) + '"' + (busy ? " disabled" : "") + ">実行</button>";
  }

  // ---- ホーム
  function paintHome(data) {
    var h = data.home;
    if (!h) return;
    var s = h.stats || {};
    if (s.total_active != null) {
      $("st-active").textContent = String(s.total_active);
      $("st-seller").textContent = s.seller || "";
      $("st-fb").textContent = String(s.feedback_score);
      $("st-fbp").textContent = s.feedback_percentage + "% 良い";
    }
    var m = h.month || {};
    if (h.shelf_unread) {
      $("st-month").textContent = "—";
      $("st-month-n").textContent = "統合シートを読込中";
      $("shelf-sub").textContent = "読み直し待ち";
      $("shelf-bars").innerHTML = '<div class="empty">統合シートを読めませんでした。1分後に読み直します</div>';
    } else if (m.usd != null) {
      $("st-month").textContent = money(m.usd);
      $("st-month-n").textContent = (m.count || 0) + "件";
      $("shelf-sub").textContent = "棚 " + money(m.shelf_usd) + " / 予算 " + money(m.shelf_budget);
    }
    var bars = (h.shelf || []).filter(function (r) { return r.budget || r.usd; }).map(function (r) {
      var cls = "none", pct = 100, amt = money(r.usd);
      if (r.budget) {
        var gap = r.budget - r.usd;
        pct = Math.max(1, Math.min(100, r.usd / r.budget * 100));
        if (gap < 0) { cls = "over"; amt = "+" + money(-gap); }
        else if (r.usd / r.budget < 0.9) { cls = "under"; amt = "−" + money(gap); }
        else { cls = ""; amt = "予算どおり"; }
      }
      return '<div class="bar" title="' + esc(r.cat) + " 現在 " + money(r.usd) + (r.budget ? " / 予算 " + money(r.budget) : " / 予算なし") + " · " + r.count + '件"><span>' + esc(r.cat) + '</span><div class="track"><div class="fill ' + cls + '" style="width:' + pct.toFixed(1) + '%"></div></div><span class="amt ' + cls + '">' + amt + "</span></div>";
    });
    if (bars.length) $("shelf-bars").innerHTML = bars.join("");

    var n = h.nightly || {}, foot = $("night-foot"), alerts = [];
    // 夜間ログの時刻は "2026/09/14 23:30:02.18" / "2026/09/15  4:56:48.90" の形。時:分だけ取る
    var hm = function (t) { var mm = /(\d{1,2}):(\d{2}):\d{2}/.exec(t || ""); return mm ? mm[1].padStart(2, "0") + ":" + mm[2] : "?"; };
    if (n.done) foot.innerHTML = '<span class="dot"></span>夜間 ' + esc(n.date || "") + " " + hm(n.start) + " → " + hm(n.end) + " 完走";
    else if (n.error) { foot.innerHTML = '<span class="dot bad"></span>夜間 ' + esc(n.error); alerts.push(["crit", "夜間バッチ", n.error]); }
    else if (n.date) { foot.innerHTML = '<span class="dot bad"></span>夜間 ' + esc(n.date) + " 途中で停止"; alerts.push(["crit", "夜間バッチ", n.date + " は途中で止まっています (最後の段: " + (n.last_step || "?") + ")"]); }
    (h.errors || []).forEach(function (e) { alerts.push(["", "読込", e]); });
    $("alerts").innerHTML = alerts.map(function (a) { return '<div class="alert ' + a[0] + '" role="status"><b>' + esc(a[1]) + "</b><span>" + esc(a[2]) + "</span></div>"; }).join("");
  }

  function paintCrew(c) {
    if (!c || !c.rows) return;
    $("crew").innerHTML = c.rows.length ? c.rows.map(function (r) {
      return '<div class="mate ' + esc(r.flag) + '"><span>' + esc(r.name) + "</span><span>" + esc(r.body) + "</span></div>";
    }).join("") : '<div class="empty">' + (c.loading ? "読込中…" : "集計できませんでした") + "</div>";
    $("crew-sub").textContent = c.route ? "宛先確認待ち " + c.route + "件" : "依頼の受け渡し";
  }

  // ---- ログ
  function pollLog() {
    getJSON("/api/log?after=" + logAfter).then(function (d) {
      var box = $("log"), stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
      (d.lines || []).forEach(function (l) {
        logAfter = l[0];
        var div = document.createElement("div"), t = l[1];
        if (/^✓|✅/.test(t)) div.className = "ok";
        else if (/^✗|❌|Traceback|Error/.test(t)) div.className = "err";
        else if (/^▶/.test(t)) div.className = "item";
        div.textContent = t;
        box.appendChild(div);
      });
      while (box.childNodes.length > 2500) box.removeChild(box.firstChild);
      if (stick) box.scrollTop = box.scrollHeight;
      var was = running && running.running;
      running = d.job;
      $("job-status").textContent = running ? (running.running ? "実行中: " + running.label + " (" + running.started + "〜)" : (running.rc === 0 ? "終わりました: " : "失敗: ") + running.label) : "待機中";
      if (was && running && !running.running) { say(running.rc === 0 ? "終わりました — 件数を数え直しています" : "失敗しました — ログを確認してください"); }
      if (was !== (running && running.running)) refreshJobs();
    }).catch(function () { $("job-status").textContent = "サーバーに繋がりません"; })
      .then(function () { setTimeout(pollLog, running && running.running ? 1200 : 4000); });
  }

  function refreshJobs() { return getJSON("/api/jobs").then(paintJobs); }
  function refreshHome() { return getJSON("/api/home").then(function (d) { paintHome(d); if (d.loading || !d.home) setTimeout(refreshHome, 3000); }); }
  function refreshCrew() { return getJSON("/api/crew").then(function (c) { paintCrew(c); if (c.loading) setTimeout(refreshCrew, 4000); }); }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-kind]");
    if (!b) return;
    b.disabled = true;
    post("/api/run", { kind: b.dataset.kind }).then(function (r) {
      if (!r.ok) { say(r.j.error || "実行できませんでした"); b.disabled = false; return; }
      say("始めました");
      logAfter = logAfter; setTimeout(refreshJobs, 300);
    });
  });
  $("btn-refresh").addEventListener("click", function () {
    post("/api/refresh").then(function () { say("数え直しを始めました (1〜3分)"); refreshJobs(); var t = setInterval(function () { refreshJobs().then(function () { if (!$("btn-refresh").disabled) { clearInterval(t); refreshHome(); refreshCrew(); } }); }, 5000); });
  });
  document.querySelectorAll(".nav a").forEach(function (a) {
    a.addEventListener("click", function () { document.querySelectorAll(".nav a").forEach(function (x) { x.classList.remove("on"); }); a.classList.add("on"); });
  });

  paintClocks(); setInterval(paintClocks, 30000);
  refreshHome().then(refreshJobs);
  refreshCrew();
  setInterval(refreshJobs, 60000);
  pollLog();
})();
