/* 出品くん Console — 画面の組み立て (2026-09-16 段階2)。
   見本 https://claude.ai/artifact/17znRRHtq61RzUeroRxU41 の形:
   ページ (今日 / 新規出品 / 在庫メンテ / 分析・棚 / 定期) + まとまりごとの別枠 +
   補URL・再仕入れは 商材 × 段階 の格子。件数・状態は /api/jobs (control_panel と同じ集計)。 */
(function () {
  "use strict";

  // 商材 × 段階 の格子。ここに無い badge は「置き場が無いボタン」に出る (取りこぼし防止)
  var MATRIX = {
    hoju: {
      title: "補URL", target: "出品中 (在庫あり)", purpose: "予備の仕入元を足す・安い仕入元に入れ替える",
      cols: ["① 当日分", "② 夜に探す", "③ 補充 (補が3本以下)", "③ 入れ替え (補4〜5本)"],
      rows: [["PSA", ["hoju_search_now", "hoju_search", "hoju_confirm", "hoju_swap"]],
             ["UT", ["ut_search_now", "ut_search", "ut_confirm", "ut_swap_confirm"]],
             ["一番くじ", [null, "kuji_search", "kuji_confirm", null]]]
    },
    restock: {
      title: "再仕入れ", target: "売り切れ (在庫0)", purpose: "また買える仕入元を見つけて在庫を戻す",
      cols: ["① 探す", "② 目視・CSV", "③ 確認・数量を戻す"],
      rows: [["PSA", ["psa_gate", "restock_build", "restock_wb"]],
             ["UT", ["ut_restock_search", "ut_restock_confirm", "ut_restore"]],
             ["一番くじ", ["kuji_supply", "kuji_refresh", null]]],
      side: { head: "売れた分 (仕入元は生きている)", kind: "sold_restock", note: "全商材まとめて · 夜間でも1晩10件まで戻す" }
    }
  };
  var SHELF_KINDS = ["cull_end", "shelf_evict"];
  var SEED_KINDS = ["ut_identify", "newcand", "newcand_high"];
  var INFO = {   // 画面だけの短い説明 (control_panel の tip は長いので見出し用に短く)
    ut_identify: "メルカリの新品 UT をカタログに当てる",
    newcand: "補URL で「違う」とした候補を種に戻す",
    newcand_high: "証明番号を打って出品行にする",
    cull_end: "仕入元が死んでいて、一度も需要が無い出品",
    shelf_evict: "落とす1 = ウォッチ0・出品200日超"
  };
  var ROWS = {          // ラベルの一部 → どのページのどの表に出すか
    scout: ["G-SHOCK 未出品モデル発見", "G-SHOCK 未出品モデル", "モンベル公式アウトレット", "Mercari スカウト"],
    check: ["CSV監査くん"],
    ana: ["ファネル分析", "効果測定", "需要・新規強化"],
    fix: ["価格見直し", "タイトル改修"],
    shelf: ["取下再出品", "再仕入れ一覧"]
  };
  var STATE_LABEL = { todo: "要対応", night: "夜間で自動", hold: "止めている", done: "残りなし", error: "数えられない", unknown: "未集計" };

  var jobs = {}, jobList = [], buttons = [], running = null, logAfter = 0, toastTimer, drawerHidden = false, schLoaded = false;

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function money(v) {
    if (v == null) return "—";
    return Math.abs(v) >= 1e6 ? "$" + (v / 1e6).toFixed(2) + "M" : "$" + Math.round(v).toLocaleString("en-US");
  }
  function say(m) { var t = $("toast"); t.textContent = m; t.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove("show"); }, 3200); }
  function getJSON(u) { return fetch(u, { cache: "no-store" }).then(function (r) { return r.json(); }); }
  function post(u, b) {
    return fetch(u, { method: "POST", headers: { "Content-Type": "application/json", "X-Console": "1" }, body: JSON.stringify(b || {}) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); });
  }
  function job(kind) { return jobs[kind] || null; }
  function chip(j) { return '<span class="chip ' + esc(j.state) + '">' + esc(j.state === "hold" ? "止めている " + j.hold : (STATE_LABEL[j.state] || j.state)) + "</span>"; }
  function num(j) { return j.n == null ? "—" : Number(j.n).toLocaleString("ja-JP"); }
  function verb(j) { return /目視|確認|補充|入れ替え/.test(j.label) ? "目視" : /CSV/.test(j.label) ? "CSV" : /戻す/.test(j.label) ? "戻す" : "実行"; }
  function btn(j, hot, text) {
    if (!j.runnable) return '<span class="else">今の出品くんで</span>';
    var busy = running && running.running;
    return '<button class="run' + (hot ? " hot" : "") + '" type="button"' +
      (j.kind ? ' data-kind="' + esc(j.kind) + '"' : "") +
      (j.i != null ? ' data-i="' + j.i + '"' : "") + (busy ? " disabled" : "") + ">" +
      esc(text || verb(j)) + "</button>";
  }
  // 枠ごとボタンにする (2026-09-16 ユーザー「実行ボタンが小さい / 枠がそのままボタンみたいなのがいい」)
  function openTag(j, cls, style, title) {
    var busy = running && running.running;
    if (!j.runnable) return '<div class="' + cls + ' off"' + style + title + ">";
    return '<button type="button" class="' + cls + '"' + style + title +
      (j.kind ? ' data-kind="' + esc(j.kind) + '"' : "") +
      (j.i != null ? ' data-i="' + j.i + '"' : "") + (busy ? " disabled" : "") + ">";
  }
  function closeTag(j) { return j.runnable ? "</button>" : "</div>"; }
  function goMark(j, text) {
    return j.runnable ? '<span class="go">' + esc(text || verb(j)) + " →</span>"
                      : '<span class="else">今の出品くんで</span>';
  }

  function sum(list, f) { return list.reduce(function (a, x) { return a + (f(x) || 0); }, 0); }
  function todoOf(list) { return list.filter(function (j) { return j.state === "todo"; }); }

  // ---------------------------------------------------------------- 在庫メンテ
  function matrix(id, m) {
    var kinds = [];
    m.rows.forEach(function (r) { r[1].forEach(function (k) { if (k) kinds.push(k); }); });
    if (m.side) kinds.push(m.side.kind);
    var list = kinds.map(job).filter(Boolean);
    var todo = todoOf(list);
    var head = '<div class="gh"><h3>' + esc(m.title) + '</h3><span class="target">' + esc(m.target) + '</span>' +
      '<span class="purpose">' + esc(m.purpose) + '</span><span class="tot">要対応 <b>' + todo.length +
      "</b> · 残件 " + sum(list, function (j) { return j.n; }).toLocaleString("ja-JP") + "</span></div>";

    var cols = m.cols.map(function (c, i) {
      return "<th>" + esc(c) + (i < m.cols.length - 1 ? '<span class="arrow">→</span>' : "") + "</th>";
    }).join("");
    if (m.side) cols += "<th>" + esc(m.side.head) + "</th>";

    var body = m.rows.map(function (r, ri) {
      var tds = r[1].map(function (k) {
        var j = k && job(k);
        if (!j) return '<td class="pad"><div class="cell na">この段は無し</div></td>';
        var hot = j.state === "todo";
        return '<td class="pad' + (hot ? " hot" : "") + '">' + openTag(j, "cell", "", ' title="' + esc(j.tip) + '"') +
          '<span class="n ' + (hot ? "todo" : j.n ? "" : "zero") + '">' + num(j) + "</span>" +
          '<span class="meta">' + chip(j) + "</span>" +
          '<span class="act">' + goMark(j) + "</span>" + closeTag(j) + "</td>";
      }).join("");
      if (m.side && ri === 0) {
        var s = job(m.side.kind);
        var shot = s && s.state === "todo";
        tds += '<td class="pad' + (shot ? " hot" : "") + '" rowspan="' + m.rows.length + '">' +
          (s ? openTag(s, "cell", "", "") +
               '<span class="n ' + (shot ? "todo" : "zero") + '">' + num(s) + "</span>" +
               '<span class="meta">' + chip(s) + "</span>" +
               '<span class="act">' + goMark(s) + "</span>" + closeTag(s) : "") +
          '<div class="note" style="margin-top:6px">' + esc(m.side.note) + "</div></td>";
      }
      return '<tr><td class="item">' + esc(r[0]) + "</td>" + tds + "</tr>";
    }).join("");

    $(id).innerHTML = head + '<div class="matrix"><table class="mx"><thead><tr><th></th>' + cols +
      "</tr></thead><tbody>" + body + "</tbody></table></div>";
    return { todo: todo.length, total: sum(list, function (j) { return j.n; }), hold: sum(list, function (j) { return j.hold; }) };
  }

  function liCard(j) {
    var hot = j.state === "todo";
    return openTag(j, "li" + (hot ? " hot" : ""), "", ' title="' + esc(j.tip) + '"') +
      '<span class="t">' + esc(j.label) + "</span>" +
      '<span class="note">' + esc(INFO[j.kind] || j.note || "") + "</span>" +
      '<span class="row"><span class="n ' + (hot ? "todo" : j.n ? "" : "zero") + '">' + num(j) + "</span>" +
      chip(j) + goMark(j) + "</span>" + closeTag(j);
  }

  function rowsFor(names, extra) {
    // 同じ名前で始まるボタンは全部出す (取下再出品①②③ のように枝番があるため)。既に置いた物は飛ばす
    var html = (names || []).map(function (name) {
      return buttons.filter(function (x) { return !x.used && x.label.indexOf(name) >= 0; }).map(function (b) {
        b.used = true;
        return openTag(b, "rw", "", "") + '<span class="t">' + esc(b.label) + '</span><span class="d">' +
          esc((b.tip || "").split("。")[0]) + "</span>" + goMark(b, "実行") + closeTag(b);
      }).join("");
    }).join("");
    return html + (extra || "");
  }

  function paintMaint() {
    var h = matrix("g-hoju", MATRIX.hoju), r = matrix("g-restock", MATRIX.restock);
    var sl = SHELF_KINDS.map(job).filter(Boolean);
    $("g-shelf").innerHTML = '<div class="gh"><h3>取下げ・棚</h3><span class="target">仕入元が死んだ / 長く売れない</span>' +
      '<span class="purpose">出品を落として棚 (出品枠の金額) を空ける</span><span class="tot">要対応 <b>' + todoOf(sl).length +
      "</b> · 残件 " + sum(sl, function (j) { return j.n; }).toLocaleString("ja-JP") + "</span></div>" +
      '<div class="list">' + sl.map(liCard).join("") + "</div>" +
      '<div class="rows" style="border-top:1px solid var(--line)">' + rowsFor(ROWS.shelf) + "</div>";
    $("fix-rows").innerHTML = rowsFor(ROWS.fix);

    var todo = h.todo + r.todo + todoOf(sl).length;
    var total = h.total + r.total + sum(sl, function (j) { return j.n; });
    var hold = h.hold + r.hold;
    $("kp-m-todo").textContent = todo;
    $("kp-m-hold").textContent = hold || "0";
    $("kp-m-total").textContent = total.toLocaleString("ja-JP");
    $("tab-maint").innerHTML = "要対応 <b>" + todo + "</b> · 止めている " + hold;
    $("maint-bar").innerHTML =
      pill("g-hoju", "補URL", "--g-hoju", h) + pill("g-restock", "再仕入れ", "--g-restock", r) +
      pill("g-shelf", "取下げ・棚", "--g-shelf", { todo: todoOf(sl).length, total: sum(sl, function (j) { return j.n; }) }) +
      '<a class="pill" href="#g-fix" style="--gc:var(--g-fix)">在庫あり・直す <b>—</b><span>件数なし</span></a>';
    return { todo: todo, hold: hold };
  }
  function pill(id, name, v, s) {
    return '<a class="pill" href="#' + id + '" style="--gc:var(' + v + ')">' + esc(name) + " <b>" + s.todo +
      "</b><span>残件 " + (s.total || 0).toLocaleString("ja-JP") + "</span></a>";
  }

  // ---------------------------------------------------------------- 新規出品
  function paintNew() {
    var sl = SEED_KINDS.map(job).filter(Boolean);
    $("seed-list").innerHTML = sl.length ? sl.map(liCard).join("") : '<div class="empty">読込中…</div>';
    $("seed-tot").innerHTML = "要対応 <b>" + todoOf(sl).length + "</b> · 残件 " +
      sum(sl, function (j) { return j.n; }).toLocaleString("ja-JP");
    $("kp-seed").textContent = sum(sl, function (j) { return j.n; }).toLocaleString("ja-JP");
    $("scout-rows").innerHTML = rowsFor(ROWS.scout);
    $("check-rows").innerHTML = rowsFor(ROWS.check);     // 生成に含まれる。単体で回したい時だけ押す
    $("tab-new").innerHTML = "要対応 <b>" + todoOf(sl).length + "</b> · 商材 " +
      Object.keys(byCategory()).length;

    // 商材 × 動作 を1枠1ボタンに (2026-09-16 ユーザー「作るボタンが枠ごとボタンじゃない」)
    var cats = byCategory();
    $("prods").innerHTML = Object.keys(cats).map(function (c) {
      return cats[c].map(function (b) {
        var auto = b.type === "auto";
        return openTag(b, "task", ' style="--gc:var(' + (auto ? "--g-restock" : "--g-seed") + ');--pc:var(--p-new)"',
                       ' title="' + esc(b.tip || "") + '"') +
          '<span class="tag"><span class="pg">' + esc(b.label) + "</span>" +
          '<span class="gp">' + (auto ? "目視 → 生成 → 予約出品" : "CSV を作る") + "</span></span>" +
          '<span class="nm">' + esc(c) + "</span>" +
          '<span class="row"><span class="note">' + (auto ? "続けて出品まで" : "作って入稿は手で") + "</span>" +
          goMark(b, auto ? "自動" : "作る") + "</span>" + closeTag(b);
      }).join("");
    }).join("") || '<div class="empty">読込中…</div>';
  }
  function byCategory() {
    var out = {};
    buttons.forEach(function (b) {
      if (b.type !== "new" && b.type !== "auto") return;
      b.used = true;
      (out[b.category || "その他"] = out[b.category || "その他"] || []).push(b);
    });
    return out;
  }

  // ---------------------------------------------------------------- 今日
  // ②→③ のように順番があるものは、**今やる段だけ**出す (終わったら次の段が出る)。
  // 2026-09-16 ユーザー:「②をやったあとで③みたいな順番が影響するのは、②だけ表示して終わったら③」
  function chainOf(j) {
    var item = (/^(PSA|UT|くじ|一番くじ|G-SHOCK)/.exec(j.label) || [, "全商材"])[1];
    return item + "/" + j.group;                      // 例: PSA/hoju
  }
  function rankOf(j) {
    var n = "①②③④⑤".indexOf(j.step || "") + 1;
    if (!n) return 9;                                  // 段の無い作業は順番待ちにしない
    return n + (/入れ替え/.test(j.label) ? 0.5 : 0);    // 入れ替えは補充のあと
  }
  function firstStepOnly(list) {
    var best = {};
    list.forEach(function (j) {
      var k = chainOf(j), r = rankOf(j);
      if (best[k] == null || r < best[k]) best[k] = r;
    });
    var now = list.filter(function (j) { return rankOf(j) === best[chainOf(j)] || rankOf(j) === 9; });
    return { now: now, waiting: list.length - now.length };
  }

  function paintToday() {
    var todo = todoOf(jobList);
    var elsewhere = todo.filter(function (j) { return !j.runnable; }).length;
    $("kp-todo").textContent = todo.length;
    $("kp-total").textContent = sum(todo, function (j) { return j.n; }).toLocaleString("ja-JP");
    $("kp-else").textContent = elsewhere;

    var lanes = [["maint", "在庫メンテ", "--p-maint", ["hoju", "restock", "shelf"]],
                 ["new", "新規出品", "--p-new", ["seed"]]];
    var waiting = 0;
    var html = lanes.map(function (L) {
      var picked = firstStepOnly(todo.filter(function (j) { return L[3].indexOf(j.group) >= 0; }));
      waiting += picked.waiting;
      var list = picked.now.sort(function (a, b) { return (b.n || 0) - (a.n || 0); });
      if (!list.length) return "";
      return '<div class="lane" style="--pc:var(' + L[2] + ')"><h2>' + esc(L[1]) + " <small>" + list.length + "</small></h2>" +
        '<div class="tasks">' + list.map(function (j) {
          return openTag(j, "task", ' style="--gc:var(--g-' + esc(j.group) + ');--pc:var(' + L[2] + ')"', ' title="' + esc(j.tip) + '"') +
            '<span class="tag"><span class="pg">' + esc(groupName(j.group)) + '</span><span class="gp">' + esc(tagOf(j)) + "</span></span>" +
            '<span class="nm">' + esc(shortName(j.label)) + "</span>" +
            '<span class="row"><span class="n">' + num(j) + "<small>件</small></span>" + goMark(j) + "</span>" + closeTag(j);
        }).join("") + "</div></div>";
    }).join("");
    $("today-lanes").innerHTML = html || '<div class="card"><div class="empty">押さないと減らない残件はありません</div></div>';
    $("today-wait").textContent = waiting
      ? "順番待ち " + waiting + "件 — 上の段が終わると出ます (全体は「在庫メンテ」の表)" : "";
    $("kp-todo").textContent = todo.length - waiting;
    $("tab-today").innerHTML = "いま押す <b>" + (todo.length - waiting) + "</b> · 残件 " +
      sum(todo, function (j) { return j.n; }).toLocaleString("ja-JP");
  }
  function groupName(g) { return { hoju: "補URL", restock: "再仕入れ", shelf: "取下げ・棚", seed: "見つける" }[g] || g; }
  function tagOf(j) {
    var m = /^(PSA|UT|くじ|一番くじ|G-SHOCK)/.exec(j.label);
    return (m ? m[1] : "全商材") + (j.step ? " " + j.step : "");
  }
  function shortName(label) {
    return label.replace(/^(PSA|UT|くじ|一番くじ)\s*/, "").replace(/(補URL|再仕入れ)\s*[①②③④⑤]\s*/, "").trim() || label;
  }

  // ---------------------------------------------------------------- 置き場が無いボタン
  function paintLeftovers() {
    var placed = {};
    Object.keys(MATRIX).forEach(function (k) {
      MATRIX[k].rows.forEach(function (r) { r[1].forEach(function (x) { if (x) placed[x] = 1; }); });
      if (MATRIX[k].side) placed[MATRIX[k].side.kind] = 1;
    });
    SHELF_KINDS.concat(SEED_KINDS).forEach(function (k) { placed[k] = 1; });
    var rest = jobList.filter(function (j) { return !placed[j.kind]; });
    var extra = buttons.filter(function (b) { return !b.used && !b.badge; });
    $("g-other").hidden = !rest.length && !extra.length;
    $("other-rows").innerHTML = rest.map(function (j) {
      return openTag(j, "rw", "", "") + '<span class="t">' + esc(j.label) + '</span><span class="d">' +
        esc(j.tip.split("。")[0]) + "</span>" + goMark(j) + closeTag(j);
    }).join("") + extra.map(function (b) {
      return openTag(b, "rw", "", "") + '<span class="t">' + esc(b.label) + '</span><span class="d">' +
        esc((b.tip || "").split("。")[0]) + "</span>" + goMark(b, "実行") + closeTag(b);
    }).join("");
  }

  // ---------------------------------------------------------------- 取り込み
  function paintJobs(d) {
    jobList = d.jobs || [];
    jobs = {};
    jobList.forEach(function (j) { jobs[j.kind] = j; });
    var at = d.counts_at ? d.counts_at.replace("T", " ").slice(5, 16) : "まだ数えていません";
    $("shop-at").textContent = (d.counting ? "数え直し中… " : "") + at + " の件数" + (d.counts_error ? " (失敗)" : "");
    $("btn-refresh").disabled = !!d.counting;
    $("btn-refresh").textContent = d.counting ? "数え直し中…" : "残件を数え直す";
    if (!jobList.length) return;
    buttons.forEach(function (b) { b.used = false; });
    paintToday();
    paintMaint();
    paintNew();
    $("ana-rows").innerHTML = rowsFor(ROWS.ana);
    paintLeftovers();
  }

  function paintHome(d) {
    var h = d.home;
    if (!h) return;
    var s = h.stats || {}, m = h.month || {}, shop = [];
    if (s.total_active != null) {
      shop.push("出品中 <b>" + s.total_active + "</b>");
      shop.push("評価 <b>" + s.feedback_score + "</b> (" + s.feedback_percentage + "%)");
    }
    if (!h.shelf_unread && m.usd != null) shop.push("今月追加 <b>" + money(m.usd) + "</b>");
    var ver = $("shop-ver") ? $("shop-ver").textContent : "";
    $("shop").innerHTML = '<span id="shop-at">' + esc($("shop-at").textContent) + "</span>" +
      shop.map(function (x) { return "<span>" + x + "</span>"; }).join("") +
      '<span id="shop-ver" class="ver">' + esc(ver) + "</span>";

    var noMoney = h.shelf_unread || h.price_missing;
    $("kp-month").textContent = noMoney ? "—" : money(m.usd);
    $("kp-month-n").textContent = noMoney ? (h.price_missing ? "価格なし" : "読込中") : (m.count || 0) + "件";
    $("kp-shelf").textContent = noMoney ? "—" : money(m.shelf_usd);
    $("kp-budget").textContent = money(m.shelf_budget);

    if (h.price_missing) {
      $("shelf-sub").textContent = "金額が出せません";
      $("shelf-bars").innerHTML = '<div class="empty">ファネル (funnel_output/funnel_*.csv) が無いので、出品価格が分かりません。ファネル分析を1回走らせてください</div>';
    } else if (h.shelf_unread) {
      $("shelf-sub").textContent = "読み直し待ち";
      $("shelf-bars").innerHTML = '<div class="empty">統合シートを読めませんでした。1分後に読み直します</div>';
    } else {
      var ps = h.price_source || {};
      $("shelf-sub").textContent = "棚 " + money(m.shelf_usd) + " / 予算 " + money(m.shelf_budget) +
        (ps.path ? " · 価格は " + String(ps.path).replace(/^.*funnel_/, "ファネル ").replace(/\.csv$/, "") : "");
      var bars = (h.shelf || []).filter(function (r) { return r.budget || r.usd; }).map(function (r) {
        var cls = "none", pct = 100, amt = money(r.usd);
        if (r.budget) {
          var gap = r.budget - r.usd;
          pct = Math.max(1, Math.min(100, r.usd / r.budget * 100));
          if (gap < 0) { cls = "over"; amt = "+" + money(-gap); }
          else if (r.usd / r.budget < 0.9) { cls = "under"; amt = "−" + money(gap); }
          else { cls = ""; amt = "予算どおり"; }
        }
        var np = r.no_price ? " · 価格不明 " + r.no_price + "件 (ファネル未反映)" : "";
        return '<div class="sb" title="' + esc(r.cat) + " 現在 " + money(r.usd) + (r.budget ? " / 予算 " + money(r.budget) : " / 予算なし") + " · " + r.count + "件" + np + '"><span>' + esc(r.cat) +
          '</span><div class="track"><div class="fill ' + cls + '" style="width:' + pct.toFixed(1) + '%"></div></div><span class="amt ' + cls + '">' + amt + (r.no_price ? '<small style="color:var(--ink-3)"> (不明' + r.no_price + ')</small>' : "") + "</span></div>";
      });
      if (bars.length) $("shelf-bars").innerHTML = bars.join("");
    }

    var n = h.nightly || {}, alerts = [];
    var hm = function (t) { var mm = /(\d{1,2}):(\d{2}):\d{2}/.exec(t || ""); return mm ? ("0" + mm[1]).slice(-2) + ":" + mm[2] : "?"; };
    var line;
    if (n.done) line = '<span><span class="dot"></span>夜間バッチ ' + esc(n.date || "") + " " + hm(n.start) + " → " + hm(n.end) + " 完走</span>";
    else if (n.error) { line = '<span><span class="dot bad"></span>夜間バッチ ' + esc(n.error) + "</span>"; alerts.push(["crit", "夜間バッチ", n.error]); }
    else if (n.date) { line = '<span><span class="dot bad"></span>夜間バッチ ' + esc(n.date) + " 途中で停止 (最後の段: " + esc(n.last_step || "?") + ")</span>"; alerts.push(["crit", "夜間バッチ", n.date + " は途中で止まっています"]); }
    else line = '<span><span class="dot bad"></span>夜間バッチ 記録なし</span>';
    $("night").innerHTML = line;
    $("kp-night").textContent = n.done ? "完走" : n.date ? "途中で停止" : "—";
    // 夜間の話は「定期」タブに置く (2026-09-16 ユーザー「今日やること に夜間バッチはいらない」)
    $("night-alerts").innerHTML = alerts.map(function (a) { return '<div class="alert ' + a[0] + '" role="status"><b>' + esc(a[1]) + "</b><span>" + esc(a[2]) + "</span></div>"; }).join("");
    $("alerts").innerHTML = (h.errors || []).map(function (e) {
      return '<div class="alert" role="status"><b>読込</b><span>' + esc(e) + "</span></div>";
    }).join("");
  }

  function paintTasks(d) {
    var rows = d.tasks || [];
    $("sch-at").textContent = rows.length ? rows.length + "件" : "";
    // Windows の結果コード: 0=正常 / 267009=実行中 / 267011=まだ一度も動いていない / 1073807364=途中で止められた
    var CODE = { 0: ["done", "正常"], 267009: ["night", "実行中"], 267011: ["night", "未実行"],
                 1073807364: ["hold", "途中で止まった"], 267014: ["hold", "止めた"] };
    $("sch-rows").innerHTML = rows.length ? rows.map(function (t) {
      var c = CODE[t.result] || ["error", "前回 失敗 (" + t.result + ")"];
      return '<div class="rw"><span class="t">' + esc(t.name) + "</span>" +
        '<span class="d">前回 ' + esc(t.last || "—") + " · 次回 " + esc(t.next || "—") + "</span>" +
        '<span class="chip ' + c[0] + '">' + esc(c[1]) + "</span></div>";
    }).join("") : '<div class="empty">' + (d.loading ? "読込中…" : "取得できませんでした") + "</div>";
  }

  // ---------------------------------------------------------------- ログ (下から出る)
  function pollLog() {
    getJSON("/api/log?after=" + logAfter).then(function (d) {
      var box = $("log"), stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
      (d.lines || []).forEach(function (l) {
        logAfter = l[0];
        var div = document.createElement("div"), t = l[1];
        if (/^✓|✅/.test(t)) div.className = "ok";
        else if (/^✗|❌|Traceback|Error/.test(t)) div.className = "err";
        div.textContent = t;
        box.appendChild(div);
      });
      while (box.childNodes.length > 2000) box.removeChild(box.firstChild);
      if (stick) box.scrollTop = box.scrollHeight;
      var was = running && running.running;
      running = d.job;
      if (running) {
        if (was && !running.running) { say(running.rc === 0 ? "終わりました — 件数を数え直しています" : "失敗しました — ログを確認してください"); drawerHidden = false; }
        if (!drawerHidden) $("drawer").hidden = false;
        $("live").className = "live" + (running.running ? "" : " off");
        $("drawer-stop").hidden = !running.running;
        $("job-label").textContent = (running.running ? "実行中: " : running.rc === 0 ? "終わりました: " : "失敗: ") + running.label;
        $("job-meta").textContent = running.started + "〜" + (running.running ? "" : " (returncode=" + running.rc + ")");
      }
      if (was !== (running && running.running)) refreshJobs();
    }).catch(function () { /* サーバー停止中は次の周期で拾う */ })
      .then(function () { setTimeout(pollLog, running && running.running ? 1200 : 4000); });
  }

  function paintVersion(d) {
    var left = (d.total || 0) - (d.ready || 0);
    $("kp-ver").textContent = "v" + d.version;
    $("kp-ready").textContent = d.ready + " / " + d.total;
    $("kp-left").textContent = left;
    $("ver-commit").textContent = d.released + (d.commit ? " · " + d.commit : "");
    if ($("shop-ver")) $("shop-ver").textContent = "v" + d.version + (d.commit ? " · " + d.commit : "");
    var why = {};
    (d.rows || []).forEach(function (r) { if (!r.ready) (why[r.why] = why[r.why] || []).push(r); });
    var names = Object.keys(why).sort(function (a, b) { return why[b].length - why[a].length; });
    $("ver-rows").innerHTML = names.map(function (w) {
      return '<div class="rw"><span class="t">' + esc(w) + " <span class=\"chip todo\">" + why[w].length + "本</span></span>" +
        '<span class="d">' + esc(why[w].map(function (r) {
          return r.category ? r.category + " " + r.label : r.label;      // 「新規」だけだと商材が分からない
        }).join(" · ")) + "</span>" +
        '<span class="else">旧パネルのまま</span></div>';
    }).join("") || '<div class="empty">全部このボタンから押せます (1.0)</div>';
    $("ver-log").textContent = d.changelog || "";
  }

  function paintWatcher(d) {
    var rows = d.rows || [];
    var run = rows.filter(function (r) { return r.running; })[0];
    $("watch").hidden = !rows.length;
    $("watch").className = "watch" + (run ? " on" : "");
    $("watch-line").textContent = "監視くん — " + (d.line || "");
    $("watch-sub").textContent = d.at ? "(" + d.at + " 時点)" : "";
    $("watch-rows").innerHTML = rows.length ? rows.map(function (r) {
      var now = r.running
        ? "巡回中 " + r.started + "〜" + (r.eta ? " · 終了めやす " + r.eta + " (あと約" + r.left_min + "分)" : "")
        : "止まっています";
      var nxt = r.next ? "次 " + r.next + (r.next_eta ? " 〜 " + r.next_eta : "") : "次の予定なし";
      var avg = r.avg_min ? "1回 約" + r.avg_min + "分 (" + r.runs + "回の平均)" : "所要はまだ記録中";
      return '<div class="rw"><span class="t">' + esc(r.label) + "</span>" +
        '<span class="d">' + esc(now + " · " + nxt) + "</span>" +
        '<span class="chip ' + (r.running ? "todo" : "done") + '">' + esc(avg) + "</span></div>";
    }).join("") : '<div class="empty">読込中…</div>';
  }
  function refreshWatcher() {
    return getJSON("/api/watcher").then(function (d) { paintWatcher(d); if (d.loading) setTimeout(refreshWatcher, 4000); })
      .catch(function () { setTimeout(refreshWatcher, 10000); });     // 繋がらない時もあきらめない
  }

  function refreshJobs() { return getJSON("/api/jobs").then(paintJobs); }   // 失敗は bootstrap 側で拾う
  function refreshHome() {
    return getJSON("/api/home").then(function (d) { paintHome(d); if (d.loading || !d.home) setTimeout(refreshHome, 3000); })
      .catch(function () { setTimeout(refreshHome, 5000); });
  }
  function refreshTasks() { return getJSON("/api/tasks").then(function (d) { paintTasks(d); if (d.loading) setTimeout(refreshTasks, 3000); }); }

  // ---------------------------------------------------------------- 操作
  function show(name) {
    document.querySelectorAll('[role="tab"]').forEach(function (t) { t.setAttribute("aria-selected", String(t.dataset.page === name)); });
    document.querySelectorAll(".page").forEach(function (p) { p.hidden = p.id !== "p-" + name; });
    if (name === "sch" && !schLoaded) { schLoaded = true; refreshTasks(); }
  }
  document.querySelectorAll('[role="tab"]').forEach(function (t) {
    t.addEventListener("click", function () { show(t.dataset.page); history.replaceState(null, "", "#" + t.dataset.page); });
  });
  // 入力欄・金額が要るボタンは、押す前に小窓で聞く (旧パネルのダイアログと同じ中身)
  function metaOf(b) {
    var i = b.dataset.i != null ? Number(b.dataset.i) : null;
    var byI = i != null ? buttons.filter(function (x) { return x.i === i; })[0] : null;
    return byI || jobs[b.dataset.kind] || {};
  }
  function ask(meta) {
    return new Promise(function (resolve) {
      var ps = meta.params || [];
      if (!ps.length && !meta.ask_amount) { resolve({}); return; }
      $("modal-title").textContent = meta.label || "入力";
      $("modal-note").textContent = meta.ask_amount
        ? "空けたい金額 ($) を入れてください。空欄のままなら「今日出品した金額と同じだけ」落とします。"
        : "空欄のままで良い欄は、そのままにしてください。";
      $("modal-fields").innerHTML = (meta.ask_amount
        ? '<label>金額 ($)<input name="__amount" inputmode="decimal" autocomplete="off"></label>' : "") +
        ps.map(function (p) {
          return "<label>" + esc(p.label || p.name) + '<input name="' + esc(p.name) + '" value="' + esc(p.default || "") + '" autocomplete="off"></label>';
        }).join("");
      $("modal").hidden = false;
      var input = $("modal-fields").querySelector("input");
      if (input) input.focus();
      function close(val) {
        $("modal").hidden = true;
        $("modal-form").onsubmit = null;
        $("modal-cancel").onclick = null;
        resolve(val);
      }
      $("modal-cancel").onclick = function () { close(null); };
      $("modal-form").onsubmit = function (ev) {
        ev.preventDefault();
        var out = { params: {} }, amt = null;
        Array.prototype.forEach.call($("modal-fields").querySelectorAll("input"), function (el) {
          if (el.name === "__amount") amt = el.value;
          else out.params[el.name] = el.value;
        });
        if (amt != null) out.amount = amt;
        close(out);
      };
    });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-kind],button[data-i]");
    if (!b) return;
    var meta = metaOf(b);
    ask(meta).then(function (extra) {
      if (!extra) { say("やめました"); return; }
      b.disabled = true;
      var body = { kind: b.dataset.kind || null, i: b.dataset.i != null ? Number(b.dataset.i) : null };
      if (extra.params) body.params = extra.params;
      if (extra.amount != null) body.amount = extra.amount;
      post("/api/run", body).then(function (r) {
        if (!r.ok) { say(r.j.error || "実行できませんでした"); b.disabled = false; return; }
        say("始めました");
        drawerHidden = false;
        $("drawer").hidden = false;
        setTimeout(refreshJobs, 300);
      });
    });
  });
  $("btn-refresh").addEventListener("click", function () {
    post("/api/refresh").then(function () {
      say("数え直しを始めました (1〜3分)");
      refreshJobs();
      var t = setInterval(function () {
        refreshJobs().then(function () { if (!$("btn-refresh").disabled) { clearInterval(t); refreshHome(); } });
      }, 5000);
    });
  });
  $("drawer-toggle").addEventListener("click", function () {
    var open = !$("log").hidden;
    $("log").hidden = open;
    this.textContent = open ? "ログを見る" : "閉じる";
    this.setAttribute("aria-expanded", String(!open));
  });
  $("drawer-hide").addEventListener("click", function () { drawerHidden = true; $("drawer").hidden = true; });
  // ★2026-09-16 ユーザー「ログ画面消えてない？」: 実行中と直後しか出していなかった。
  //   いつでも開けるようにする (走っていない時は直近のログが出る)
  $("btn-log").addEventListener("click", function () {
    drawerHidden = false;
    $("drawer").hidden = false;
    $("log").hidden = false;
    $("drawer-toggle").textContent = "閉じる";
    if (!running) {
      $("job-label").textContent = "直近のログ";
      $("job-meta").textContent = "";
      $("live").className = "live off";
      $("drawer-stop").hidden = true;
    }
    $("log").scrollTop = $("log").scrollHeight;
  });
  // ログをまるごとコピー (2026-09-16 ユーザー要望。貼って相談する時に使う)
  $("drawer-copy").addEventListener("click", function () {
    var head = ($("job-label").textContent || "") + " " + ($("job-meta").textContent || "");
    var text = head.trim() + String.fromCharCode(10) + $("log").innerText;
    var b = this;
    function done(ok) { b.textContent = ok ? "コピーしました" : "コピーできません"; setTimeout(function () { b.textContent = "ログをコピー"; }, 1800); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
      return;
    }
    var ta = document.createElement("textarea");          // 古い環境向けの控え
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { done(document.execCommand("copy")); } catch (e) { done(false); }
    document.body.removeChild(ta);
  });
  $("drawer-stop").addEventListener("click", function () {
    var b = this;
    b.disabled = true;
    post("/api/stop").then(function (r) {
      say(r.ok ? "止めています…" : (r.j.error || "止められませんでした"));
      b.disabled = false;
    });
  });

  var h = (location.hash || "").slice(1);
  if ($("p-" + h)) show(h);
  getJSON("/api/version").then(paintVersion);
  refreshWatcher();
  setInterval(refreshWatcher, 120000);        // 巡回の状況は2分ごと
  // ★2026-09-16 ユーザー「件数読み込み中で固まってる」: 最初の読み込みが1回きりで、
  //   サーバの入れ替え中などに失敗すると **そのまま止まっていた**。失敗したら数秒後にやり直す。
  function bootstrap() {
    return getJSON("/api/buttons").then(function (d) {
      buttons = d.buttons || [];
      return refreshJobs();
    }).then(refreshHome).catch(function () {
      $("shop-at").textContent = "サーバーに繋がりません — 3秒後にやり直します";
      setTimeout(bootstrap, 3000);
    });
  }
  bootstrap();
  setInterval(function () {                    // 定期の更新でも、取れていなければ組み直す
    if (!buttons.length || !jobList.length) { bootstrap(); return; }
    refreshJobs();
  }, 60000);
  pollLog();
})();
