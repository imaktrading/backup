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
      cols: ["① 仕入元を決める", "② 目視・CSV", "③ 確認・数量を戻す"],
      rows: [["PSA", ["psa_gate", null, null]],     // ②③ は ① から続けて走る (2026-10-04)
             ["UT", ["ut_restock_search", "ut_restock_confirm", "ut_restore"]],
             ["一番くじ", ["kuji_supply", "kuji_refresh", null]]],
      side: { head: "売れた分 (仕入元は生きている)", kind: "sold_restock", note: "全商材まとめて · 毎晩自動で戻す (1晩10件まで)・押すボタンは無し" }
    }
  };
  var SHELF_KINDS = ["cull_end", "shelf_evict"];
  var SEED_KINDS = ["ut_identify", "newcand", "newcand_high"];
  var INFO = {   // 画面だけの短い説明 (control_panel の tip は長いので見出し用に短く)
    ut_identify: "メルカリの新品 UT をカタログに当てる",
    newcand: "補URL で「違う」とした候補を種に戻す",
    newcand_high: "証明番号を打って出品行にする",
    cull_end: "仕入元が死んでいて、一度も需要が無い出品",
    shelf_evict: "PSA は 10/5 確定ルール (90日がケツ・市場の門)"
  };
  var ROWS = {          // ラベルの一部 → どのページのどの表に出すか
    scout: ["G-SHOCK 未出品モデル発見", "G-SHOCK 未出品モデル", "モンベル公式アウトレット", "Mercari スカウト"],
    check: ["CSV監査くん"],
    ana: ["よく売れているカード", "カタログを見る", "ファネル分析", "効果測定", "需要・新規強化"],
    fix: ["価格見直し", "タイトル改修"],
    // ★2026-09-19 ユーザー「出品くんコンソールにオファーがないね」。
    //   旧パネルでは上段の青ボタンで、この画面のどこにも出ていなかった。
    offer: ["オファー対応", "ミラーに広告・オファー", "オファーの PSA の安い仕入元"],
    order: ["注文の取り込み", "仕入れ先を探す"],
    shelf: ["取下再出品", "再仕入れ一覧"]
  };
  var STATE_LABEL = { todo: "要対応", night: "夜間で自動", hold: "止めている", done: "残りなし", error: "数えられない", unknown: "未集計" };

  var HIDDEN_KINDS = ["restock_build", "restock_wb",   // PSA 再仕入れ ②③ (① から続けて走る・2026-10-04)
                      "sold_restock"];                  // 売れた分を補充 (目視なし・毎晩自動。ユーザー「ボタン化する意味ある？」10/4)
  var jobs = {}, jobList = [], buttons = [], running = null, logAfter = 0, toastTimer, drawerHidden = true, schLoaded = false;
  // 今日やることの「状態の1行」と「期限のある物」(2026-09-29)。各所が材料を入れ、renderStrip が描く
  var STRIP = { counts: null, night: null, watch: null, integrity: null, errors: [], offer: null, order: null }, autoRecounted = false;
  var SALES_SHEET = ["https:", "", "docs.google.com", "spreadsheets", "d",   // 販売実績シート (// を文字列に書かない)
                     "1MufEUweIJcLv-NwT3KZsEJ_k_yl1rKryaqBZjUH7c2U", "edit#gid=1814510799"].join("/");

  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  // ★2026-10-02: KAGOYA で動くボタンに印 (ユーザー要望「移行したマークつけれない？」)
  function kg(x) { return x && x.kagoya ? '<span class="kg" title="押すと KAGOYA で動きます (画面はこの PC で開きます)">KAGOYA</span>' : ""; }
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
  // ★2026-10-03: 「🔁 売れた分を補充」は目視の無いボタン (在庫を1に戻すだけ) なのに、「補充」で「目視」と出ていた
  function verb(j) { return /売れた分/.test(j.label) ? "戻す" : /目視|確認|補充|入れ替え/.test(j.label) ? "目視" : /CSV/.test(j.label) ? "CSV" : /戻す/.test(j.label) ? "戻す" : "実行"; }
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
        return '<td class="pad' + (hot ? " hot" : "") + '">' + openTag(j, "cell", "", ' title="' + esc(tipOf(j)) + '"') +
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

  function tipOf(j) {
    // ★2026-09-28 ユーザー「ボタンが広がるから、ヒントテキスト内にして」:
    //   棚② の 空く額 はボタンに書かず、マウスを乗せた時の説明の先頭に出す
    return (j.kind === "shelf_evict" && j.note ? j.note + "\n\n" : "") + (j.tip || "");
  }

  function liCard(j) {
    var hot = j.state === "todo";
    return openTag(j, "li" + (hot ? " hot" : ""), "", ' title="' + esc(tipOf(j)) + '"') +
      '<span class="t">' + esc(j.label) + kg(j) + "</span>" +
      '<span class="note">' + esc(INFO[j.kind] || j.note || "") + "</span>" +
      '<span class="row"><span class="n ' + (hot ? "todo" : j.n ? "" : "zero") + '">' + num(j) + "</span>" +
      chip(j) + goMark(j) + "</span>" + closeTag(j);
  }

  function rowsFor(names, extra) {
    // 同じ名前で始まるボタンは全部出す (取下再出品①②③ のように枝番があるため)。既に置いた物は飛ばす
    var html = (names || []).map(function (name) {
      return buttons.filter(function (x) { return !x.used && x.label.indexOf(name) >= 0; }).map(function (b) {
        b.used = true;
        return openTag(b, "rw", "", "") + '<span class="t">' + esc(b.label) + kg(b) + '</span><span class="d">' +
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
    // ★2026-09-19: オファーの件数を段の見出しに出す (来ているのに出ていなかった)。
    var oj = job("offer_calc");
    // ★2026-09-29: オファーと注文は「今日やること」の状態の1行 + 1件以上の時だけ大きな枠 (renderStrip)。
    //   ボタン一式はここ (在庫メンテの「オファー・注文」) に置く
    STRIP.offer = oj;
    STRIP.order = job("order_sync");
    $("offer-rows").innerHTML = rowsFor(ROWS.offer);
    $("order-rows").innerHTML = rowsFor(ROWS.order);
    renderStrip();
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
          '<span class="tag"><span class="pg">' + esc(b.label) + kg(b) + "</span>" +
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
    // ★2026-09-19 ユーザー「今日やることに PSA入れ替え③ が出てきてない / 実際押して作業している」。
    //   「補充」(補URLが足りない出品に足す) と「入れ替え」(もっと安い仕入元に替える) は
    //   **別の行に対する別の作業**で、順番の関係が無い。同じ ③ として1本の順番に入れていたため、
    //   補充が0件になるまで入れ替えが順番待ちに隠れていた (実測: 補充88件 / 入れ替え17件)。
    // ★2026-09-20 ユーザー「新規PSA自動を走らせた後、今日やることから PSA③ が消える」。
    //   「① 当日分」は **今日出した行**に候補を探すボタン、「③ 補充」は **夜に溜めた別の行**を
    //   目視して書くボタンで、やはり順番の関係が無い。新規自動を走らせると当日分が 0→17 に
    //   なり、その瞬間 ③ (補充 65件) が順番待ちに隠れていた (実測 2026-09-20)。
    return item + "/" + j.group +
      (/入れ替え/.test(j.label) ? "/swap" : /当日分/.test(j.label) ? "/now" : "");
  }
  function rankOf(j) {
    // ★2026-09-16 ユーザー「棚②は今日やることに追加しないの？」で発覚:
    //   段が空の時 indexOf("") は **0** を返すので、段の無い作業まで「①」扱いになり、
    //   同じまとまりの ②③ を順番待ちに押し下げていた (取下げ=段なし が 棚② を隠していた)。
    var s = j.step || "";
    if (!s) return 9;                                  // 段の無い作業は順番待ちにしない
    var n = "①②③④⑤".indexOf(s) + 1;
    if (!n) return 9;
    return n;                                          // 入れ替えは別の流れ (chainOf で分ける)
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

    // ★2026-09-19 ユーザー「オファーの件、重要だからTOP画面に出してほしい」。
    //   オファーは期限が短い (実例: 受信から丸1日) ので、一番上の枠に入れる。
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
          return openTag(j, "task", ' style="--gc:var(--g-' + esc(j.group) + ');--pc:var(' + L[2] + ')"', ' title="' + esc(tipOf(j)) + '"') +
            '<span class="tag"><span class="pg it" data-it="' + esc(itemOf(j)) + '">' + esc(itemOf(j)) + '</span><span class="gp">' + esc(tagOf(j)) + "</span></span>" +
            '<span class="nm">' + esc(shortName(j.label)) + kg(j) + "</span>" +
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
  function groupName(g) { return { hoju: "補URL", restock: "再仕入れ", shelf: "取下げ・棚", seed: "見つける", offer: "オファー" }[g] || g; }
  // ★2026-09-19 ユーザー「PSA関係なのか、くじ関係なのか、UT関係なのかがいまいち分かりにくい」。
  //   商材を **カードの1番目**に出す。まとまり (補URL 等) はその次。
  function itemOf(j) {
    var m = /^(PSA|UT|くじ|一番くじ|G-SHOCK)/.exec(j.label);
    return m ? (m[1] === "一番くじ" ? "くじ" : m[1]) : "全商材";
  }
  function tagOf(j) {
    return groupName(j.group) + (j.step ? " " + j.step : "");
  }
  function shortName(label) {
    return label.replace(/^(PSA|UT|くじ|一番くじ)\s*/, "").replace(/(補URL|再仕入れ)\s*[①②③④⑤]\s*/, "").trim() || label;
  }

  // ---------------------------------------------------------------- 今日: 状態の1行 + 期限のある物
  function stChip(c) {
    return c ? '<span class="st ' + (c[0] || "") + '"><i></i>' + c[1] + (c[2] ? " " + c[2] : "") + "</span>" : "";
  }
  function jobBtn(j, text) {                       // 小さなボタン (押すと普通の作業と同じく走る)
    return j && j.runnable ? '<button type="button" data-kind="' + esc(j.kind) + '"' + (j.i != null ? ' data-i="' + j.i + '"' : "") +
      (running && running.running ? " disabled" : "") + ">" + esc(text) + "</button>" : "";
  }
  function renderStrip() {
    if (!$("today-strip")) return;
    var oj = STRIP.offer, dj = STRIP.order, chips = [STRIP.counts, STRIP.night, STRIP.watch, STRIP.integrity, STRIP.defender];
    if (oj) chips.push(oj.state === "error" ? ["warn", "オファー 数えられない", ""]
                       : [oj.n ? "warn" : "", "オファー <b>" + (oj.n || 0) + "件</b>", ""]);
    // ★2026-09-29 ユーザー「これに仕入れ待ち件数を表示を追加したら」: [取り込む] はここに1つだけ (常に)
    if (dj) chips.push([dj.n ? "warn" : "", "注文 仕入れ待ち <b>" + (dj.n == null ? "—" : dj.n) + "件</b>" +
                        (dj.note ? " · " + esc(dj.note).replace("最後の取り込み ", "最後の取り込み <b>") + "</b>" : " · 未取り込み"),
                        jobBtn(dj, "取り込む") + ' <a class="stlink" href="' + SALES_SHEET + '" target="_blank" rel="noopener">シート</a>']);
    // ★2026-10-05 ユーザー「新規出品出来るカード枚数を…注文仕入れ待ち0件みたいに表示できる？」
    var pn = STRIP.psaNew;
    if (pn) chips.push(pn.n == null ? ["warn", "新規に出せる PSA 数えられない", ""]
                       : ["", "新規に出せる PSA <b>" + pn.n + "枚</b>", ""]);
    $("today-strip").innerHTML = chips.concat(STRIP.errors || []).map(stChip).join("");
    var big = [];
    // 左注文・右オファーの2枠 (2026-10-04 ユーザー「注文は左にして」= .ord を先頭に並べる)。どちらかに件数があれば両方並べる (0件の側は「ありません」)
    var two = (oj && oj.n) || (dj && dj.n);
    if (two && !(oj && oj.n)) {
      big.push('<div class="u calm"><span class="k">オファー</span><span class="t"><b>0</b>件</span>' +
        '<span class="d">来ていません</span><span class="ugo"></span></div>');
    }
    if (oj && oj.n) {
      // ★2026-10-05 ユーザー「オファー判定の時も、売れたPSAの仕入先を探すがあると助かる」
      var opb = buttons.filter(function (b) { return b.label.indexOf("オファーの PSA の安い仕入元") >= 0; })[0];
      big.push('<div class="u"><span class="k">オファー (返事の期限は受信から約1日)</span>' +
        '<span class="t"><b>' + num(oj) + "</b>件 来ています</span>" +
        '<span class="d">国・出品価格・仕入値つきの一覧をブラウザで開きます。PSA は今より安い仕入元も探せます</span>' +
        '<span class="ugo">' + (oj.runnable ? jobBtn(oj, "オファー対応").replace("<button", '<button class="run hot"') : "") +
        (opb ? " " + jobBtn(opb, "安い仕入元を探す") : "") + "</span></div>");
    }
    // ★2026-10-04 ユーザー「今日やることのオファーのようにして。右に注文、左にオファーの２枠で」:
    //   9/29 にやめた仕入れ待ちの大きな枠を、売れた PSA の仕入れ先を探すボタン付きで戻す
    if (two && !(dj && dj.n)) {
      big.push('<div class="u calm ord"><span class="k">注文 仕入れ待ち</span><span class="t"><b>0</b>件</span>' +
        '<span class="d">仕入れ待ちはありません' + (dj && dj.note ? " (" + esc(dj.note) + ")" : "") + '</span><span class="ugo"></span></div>');
    }
    if (dj && dj.n) {
      var ps = buttons.filter(function (b) { return b.label.indexOf("仕入れ先を探す") >= 0; })[0];
      big.push('<div class="u ord"><span class="k">注文 仕入れ待ち' + (dj.ship_by ? " (一番近い発送期限 " + esc(dj.ship_by) + ")" : "") + "</span>" +
        '<span class="t"><b>' + num(dj) + "</b>件 仕入れ待ち" + (dj.psa ? " <small>うち PSA " + dj.psa + "件</small>" : "") + "</span>" +
        (dj.warn ? '<span class="d" style="color:var(--crit,#e66)">⚠ ' + esc(dj.warn) +
                   " — 仕入れ済みでも結び付きません" + (dj.warn.indexOf("メルカリ") >= 0
                     ? "。デスクトップの「メルカリ購入履歴_ログインし直す」→ 取り込む" : "") + "</span>" : "") +
        '<span class="d">' + (dj.psa ? "売れた PSA の仕入れ先を、仕入元・補URL・メルカリ・スニダンから安い順に開きます"
                                     : "PSA の仕入れ待ちはありません (" + esc(dj.note || "") + ")") + "</span>" +
        '<span class="ugo">' + (dj.psa && ps ? jobBtn(ps, "仕入れ先を探す").replace("<button", '<button class="run hot"') : "") + "</span></div>");
    }
    $("today-urgent").innerHTML = big.join("");
  }

  // ★2026-09-29: 毎朝のデータの見張り (カタログ DB の壊れ・1ビット化け)。化けていたら赤く出す
  function refreshIntegrity() {
    return getJSON("/api/integrity").then(function (d) {
      if (d.ok === null || d.ok === undefined) { STRIP.integrity = ["info", "データの見張り まだ動いていません", ""]; }
      else if (d.ok) { STRIP.integrity = ["", "データ 化けなし <b>" + esc((d.at || "").slice(5, 16).replace("T", " ")) + "</b>", ""]; }
      else {
        STRIP.integrity = ["crit", "データが化けています: " + (d.flips ? d.flips + "か所" : "") +
          (d.qc && d.qc !== "ok" ? " DB 破損" : "") + (d.error ? " (見張りの失敗)" : "") +
          (d.request ? " → <b>カタログに復元を依頼済み</b>" : ""), ""];
      }
      renderStrip();
    }).catch(function () {});
  }
  refreshIntegrity();
  setInterval(refreshIntegrity, 600000);

  // ★2026-10-04 ユーザー「ここにボタン付けてくれない？ON/OFFで。わすれちゃうから」:
  //   Windows Defender の検査の対象外 (C:\dev)。押すと Windows の確認 (管理者) が出る → 「はい」
  function refreshDefender() {
    return getJSON("/api/defender").then(function (d) {
      var on = d.on === true, unknown = d.on === null || d.on === undefined;
      STRIP.defender = [on ? "warn" : "", "Defender 対象外 (C:\\dev) <b>" + (unknown ? "不明" : on ? "ON" : "OFF") + "</b>",
        // ★同日 ユーザー「ONとOFFがいるのでは？」: 2つ並べ、今の状態の方を塗る (押しても同じ状態なら何も変わらない)
        ["on", "off"].map(function (m) {
          var cur = !unknown && (m === "on") === on;
          return '<button type="button" class="stlink" data-defender="' + m + '"' +
            (cur ? ' style="background:var(--warn,#e0a030);color:#000;font-weight:700"' : "") + ">" + m.toUpperCase() + "</button>";
        }).join(" ")];
      renderStrip();
    }).catch(function () {});
  }
  refreshDefender();
  setInterval(refreshDefender, 600000);
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("button[data-defender]");
    if (!b) return;
    b.disabled = true;
    b.textContent = "Windows の確認で「はい」…";
    post("/api/defender", { on: b.dataset.defender === "on" }).then(function () {
      setTimeout(refreshDefender, 8000);
      setTimeout(refreshDefender, 20000);
    });
  });

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
      return openTag(j, "rw", "", "") + '<span class="t">' + esc(j.label) + kg(j) + '</span><span class="d">' +
        esc(j.tip.split("。")[0]) + "</span>" + goMark(j) + closeTag(j);
    }).join("") + extra.map(function (b) {
      return openTag(b, "rw", "", "") + '<span class="t">' + esc(b.label) + kg(b) + '</span><span class="d">' +
        esc((b.tip || "").split("。")[0]) + "</span>" + goMark(b, "実行") + closeTag(b);
    }).join("");
  }

  // ---------------------------------------------------------------- 取り込み
  function paintJobs(d) {
    // ★2026-10-04 ユーザー「②③もボタン分けて、私が押す必要ないもんね」: PSA 再仕入れ ① が ②③ まで続けて走るので
    //   ②③ はこの画面に出さない (旧パネルには残る。やり直しは ① を押し直せば ③ まで走る)
    jobList = (d.jobs || []).filter(function (j) { return HIDDEN_KINDS.indexOf(j.kind) < 0; });
    jobs = {};
    jobList.forEach(function (j) { jobs[j.kind] = j; });
    STRIP.psaNew = d.psa_new && Object.keys(d.psa_new).length ? d.psa_new : null;   // ★2026-10-05 新規に出せる PSA
    var at = d.counts_at ? d.counts_at.replace("T", " ").slice(5, 16) : "まだ数えていません";
    $("shop-at").textContent = (d.counting ? "数え直し中… " : "") + at + " の件数" + (d.counts_error ? " (失敗)" : "");
    // ★2026-09-25: 数え直しが240秒で打ち切られ、昨日の件数 (入れ替え 11件・実際は 0件) が出たままだった。
    //   上の小さな「(失敗)」では気づけないので、失敗した時と 3時間より古い時は赤い知らせを出す。
    var ageH = d.counts_at ? (Date.now() - new Date(d.counts_at).getTime()) / 3600000 : 0;
    var cw = "";
    if (!d.counting && d.counts_error) cw = "件数を数え直せませんでした (" + esc(String(d.counts_error).slice(0, 80)) + ")。表示は " + at + " の古い件数です";
    else if (!d.counting && ageH > 3) cw = "表示の件数は " + at + " のものです (" + Math.floor(ageH) + "時間前)。「残件を数え直す」を押してください";
    // ★2026-09-29 ユーザー「件数が古いと表示されても、何をしたらいいのかわからない」:
    //   古い・失敗した時は **開いた時に1回だけ自動で数え直す**。それでも古い時だけボタンを出す
    if (cw && !autoRecounted && !d.counting) {
      autoRecounted = true;
      post("/api/refresh").then(function () { setTimeout(refreshJobs, 4000); });
      STRIP.counts = ["info", "件数を数え直しています…", ""];
    } else if (d.counting) {
      STRIP.counts = ["info", "件数を数え直しています…", ""];
    } else if (cw) {
      STRIP.counts = ["warn", "件数 <b>" + esc(at) + "</b> 時点 (数え直せませんでした)",
                      '<button type="button" data-act="refresh">もう一度</button>'];
    } else {
      STRIP.counts = ["", "件数 <b>" + esc(at) + "</b> 時点", ""];
    }
    renderStrip();
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
      shop.push("出品中 <b>" + Number(s.total_active).toLocaleString("ja-JP") + "</b>" +
                (s.active_is_us ? " <small>US</small>" : ""));
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
    // ★夜が止まった時は「知らせ」を今日やることに出す (作業カードにはしない)。
    //   押すのは自分の仕事ではないが、動くべき物が動かなかったのは分かるようにする。
    var notes = [];
    if (!n.done) {
      var nightN = jobList.filter(function (j) { return j.state === "night"; })
        .reduce(function (a, j) { return a + (j.n || 0); }, 0);
      notes.push(["crit", "夜間バッチ",
                  (n.error ? n.error
                   : (esc(n.date || "") + " " + hm(n.start) + " に走り出して 途中で止まりました"
                      + (n.last_step ? " (最後の段: " + esc(n.last_step) + ")" : "")))
                  + " — 今夜また走ります" + (nightN ? " (夜が担当する残り " + nightN + "件)" : "")]);
    }
    (h.errors || []).forEach(function (e) { notes.push(["", "読込", e]); });
    // ★2026-09-29 ユーザー「夜間バッチ 途中で止まったと言われても」: 自分がやることの有無まで書く
    STRIP.night = n.done ? ["", "夜の処理 完走 <b>" + hm(n.end) + "</b>", ""]
      : ["info", "夜の処理: " + (n.last_step ? esc(n.last_step) + " の途中で止まった" : "途中で止まった") +
         " → <b>残りは今夜やります</b> (何もしなくてよい)", ""];
    STRIP.errors = (h.errors || []).map(function (e) { return ["warn", "読込: " + esc(e), ""]; });
    renderStrip();
  }

  // ★2026-10-06 ユーザー「あるべき姿に修正して」: あるべき姿の台帳と実物 (この PC・KAGOYA・夜の束・LAPTOP) の
  //   突き合わせ結果を出す。止めてあって正常な物 (移設・廃止) は畳み、異常は担当名つきで上に並べる
  var WHERE = { home: "この PC", kagoya: "KAGOYA", job_queue: "夜の束", laptop: "LAPTOP" };
  var AST = { ok: ["done", "正常"], never: ["done", "初回待ち"], running: ["night", "実行中"], overlap: ["hold", "見送り"],
              missing: ["error", "見つからない"], disabled: ["error", "止まっている"], failed: ["error", "失敗"],
              stale: ["error", "動いていない"], ask: ["hold", "担当に確認中"], unknown: ["hold", "確かめられない"],
              unknown_task: ["hold", "台帳に無い"] };
  function paintAudit(a) {
    var rows = (a.rows || []).slice().sort(function (x, y) {
      var bx = (AST[x.status] || ["error"])[0] === "done" ? 1 : 0, by = (AST[y.status] || ["error"])[0] === "done" ? 1 : 0;
      return bx - by;
    });
    var bad = rows.filter(function (r) { return (AST[r.status] || ["error"])[0] !== "done" && r.status !== "running"; }).length;
    $("sch-at").textContent = (bad ? "要確認 " + bad + "件 / " : "全部 正常 / ") + rows.length + "件 (点検 " + String(a.at || "").slice(5, 16).replace("T", " ") + ")";
    var html = rows.map(function (r) {
      var c = AST[r.status] || ["error", r.status];
      return '<div class="rw"><span class="t">' + esc(r.name) + ' <small>' + esc(WHERE[r.where] || r.where) + " · " + esc(r.owner) + "</small></span>" +
        '<span class="d">' + esc(r.why || "") + "</span>" +
        '<span class="chip ' + c[0] + '">' + esc(c[1]) + "</span></div>";
    }).join("");
    var ret = a.retired || [];
    if (ret.length) {
      html += '<details class="rw"><summary>止めてあって正常 (移設・廃止) ' + ret.length + "本</summary>" +
        ret.map(function (r) { return '<div class="d">' + esc(r.name) + " — " + esc(r.why) + "</div>"; }).join("") + "</details>";
    }
    $("sch-rows").innerHTML = html;
  }
  function paintTasks(d) {
    if (d.audit && d.audit.rows) { paintAudit(d.audit); return; }
    var rows = d.tasks || [];
    $("sch-at").textContent = rows.length ? rows.length + "件" : "";
    // Windows の結果コード: 0=正常 / 267009=実行中 / 267011=まだ一度も動いていない / 1073807364=途中で止められた
    var CODE = { 0: ["done", "正常"], 267009: ["night", "実行中"], 267011: ["night", "未実行"],
                 1073807364: ["hold", "途中で止まった"], 267014: ["hold", "止めた"] };
    $("sch-rows").innerHTML = rows.length ? rows.map(function (t) {
      var c = t.disabled ? ["hold", "停止中"] : (CODE[t.result] || ["error", "前回 失敗 (" + t.result + ")"]);
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
        // ★2026-09-19 ユーザー「起動時にログが表示されるんだけど、閉じて欲しい」。
        //   前回の走行の記録が残っているだけで開いていた。**今 走っている時だけ**開く。
        //   見たい時は右上の「ログを見る」で開く。
        if (running.running) drawerHidden = false;
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
    // ★2026-09-29: 今日やることでは状態の1行に小さく (巡回表は「定期」タブ)
    STRIP.watch = rows.length || d.line ? [run ? "warn" : "", "監視くん " + esc((d.line || "").replace(/^監視くん\s*[—-]\s*/, "")), ""] : null;
    renderStrip();
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
    if (name === "agents") refreshAgents();
    if (name === "msg" && window.MSGTAB) window.MSGTAB.load();
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
  $("today-strip").addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("button[data-act=refresh]") : null;
    if (b) $("btn-refresh").click();
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
  // ★2026-09-18 ユーザー要望: ログをコピーすると走行が3本ぶん入ってしまう。
  //   欲しいのは **直前の1本だけ**。走行の始まりは「▶ 」で始まる行なので、
  //   最後の「▶ 」より前を消す / コピーもそこから下だけにする。
  function lastRunStart() {
    var kids = $("log").childNodes;
    for (var i = kids.length - 1; i >= 0; i--) {
      if (/^▶/.test(kids[i].textContent || "")) return i;
    }
    return -1;
  }
  function lastRunText() {
    var kids = $("log").childNodes, from = lastRunStart();
    if (from < 0) return $("log").innerText;
    var out = [];
    for (var i = from; i < kids.length; i++) out.push(kids[i].textContent || "");
    return out.join(String.fromCharCode(10));
  }
  $("drawer-clear").addEventListener("click", function () {
    var b = this;
    var from = lastRunStart();
    if (from > 0) {                       // 前の走行が残っている → その分だけ消す
      for (var i = 0; i < from; i++) $("log").removeChild($("log").firstChild);
      b.textContent = "前の分を消しました";
      setTimeout(function () { b.textContent = "🗑 ログを消す"; }, 1200);
      return;
    }
    $("log").innerHTML = "";              // 1本しか無い → 全部消す
    // 見出し(「失敗: … (returncode=1)」)も一緒に消す。これが残ると
    // 「消えていない」に見える (2026-09-18 ユーザー指摘)。走っていない時だけ。
    if (!(running && running.running)) {
      $("job-label").textContent = "";
      $("job-meta").textContent = "";
    }
    b.textContent = "消しました";
    setTimeout(function () { b.textContent = "🗑 ログを消す"; }, 1200);
  });
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
    var text = head.trim() + String.fromCharCode(10) + lastRunText();  // 直前の1本だけ (2026-09-18)
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
      buttons = (d.buttons || []).filter(function (b) { return HIDDEN_KINDS.indexOf(b.badge) < 0; });
      return refreshJobs();
    }).then(refreshHome).catch(function () {
      $("shop-at").textContent = "サーバーに繋がりません — 3秒後にやり直します";
      setTimeout(bootstrap, 3000);
    });
  }

  // ---------------------------------------------------------------- 担当 (2026-09-29)
  // 中身は tools/agent_board.py。行を押すと claude.ai/code のその会話が開く (見るだけでは意味がない)。
  var AG_LAB = { busy: "作業中", ask: "返事待ち", idle: "待機中" };
  function agDur(iso) {
    if (!iso) return "";
    var m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    return m < 60 ? m + "分" : Math.floor(m / 60) + "時間" + (m % 60 ? (m % 60) + "分" : "");
  }
  function agSpark(v) {
    v = (v && v.length > 1) ? v : [0, 0];
    var w = 120, h = 30, p = 3, mx = Math.max.apply(null, v.concat([1])), st = (w - 2 * p) / (v.length - 1);
    var pts = v.map(function (y, i) { return [p + i * st, h - p - (y / mx) * (h - 2 * p)]; });
    var line = pts.map(function (q, i) { return (i ? "L" : "M") + q[0].toFixed(1) + " " + q[1].toFixed(1); }).join(" ");
    var e = pts[pts.length - 1];
    return '<svg class="agsp" viewBox="0 0 ' + w + " " + h + '" aria-hidden="true">' +
      '<line x1="' + p + '" y1="' + (h - p) + '" x2="' + (w - p) + '" y2="' + (h - p) + '" stroke="var(--line)" stroke-width="1"/>' +
      '<path d="' + line + " L " + e[0].toFixed(1) + " " + (h - p) + " L " + p + " " + (h - p) + ' Z" fill="var(--ai)" fill-opacity=".12"/>' +
      '<path d="' + line + '" fill="none" stroke="var(--ai)" stroke-width="1.5" stroke-linejoin="round"/>' +
      '<circle cx="' + e[0] + '" cy="' + e[1] + '" r="2.6" fill="var(--ai)"/></svg>';
  }
  function agRow(a, stale, canLaunch, host) {
    if (a.state === "off") {                   // 閉じている担当 (デスクトップ「Claude」のショートカット / KAGOYA の .bat)
      return '<div class="ag off"><span class="agbar"></span>' +
        '<span class="agtop"><span class="agnm">' + esc(a.name) + '</span><span class="agst"><span class="agdt"></span>閉じている</span>' +
        '<span class="agwh">' + esc(a.where || "") + "</span></span>" +
        '<span class="agnow">' + (canLaunch ? "起動すると、この担当の前回の会話の続きから開きます" : "この PC からは起動できません") + "</span>" +
        '<span class="agside">' + (canLaunch ? '<button type="button" class="run aglaunch" data-key="' + esc(a.key) + '" data-host="' + esc(host || "") + '">起動</button>' : "") +
        "</span></div>";
    }
    var st = stale ? "idle" : a.state;
    var lead = st === "busy" ? "作業して " : st === "ask" ? "待たせて " : "止まって ";
    var tag = a.url ? "a" : "div";
    var href = a.url ? ' href="' + esc(a.url) + '" target="_blank" rel="noopener"' : "";
    return "<" + tag + ' class="ag ' + st + '"' + href + '><span class="agbar"></span>' +
      '<span class="agtop"><span class="agnm">' + esc(a.name) + '</span><span class="agst"><span class="agdt"></span>' +
      (stale ? "不明" : AG_LAB[a.state] || a.state) + '</span><span class="agwh">' + esc(a.where || "") + "</span></span>" +
      '<span class="agnow">' + esc(a.now || "—") + "</span>" +
      '<span class="agmeta"><span>' + lead + agDur(a.since) + "</span><span>起動 " + agDur(a.started) + "前</span>" +
      (a.url ? '<span class="agopen">開いて打つ →</span>' : "<span>会話の住所が取れません</span>") + "</span>" +
      '<span class="agside"><span class="aglab">直近60分</span>' + agSpark(a.act) + "</span></" + tag + ">";
  }
  function paintAgents(d) {
    var n = { busy: 0, ask: 0, idle: 0, off: 0 };
    (d.machines || []).forEach(function (m) { (m.rows || []).forEach(function (a) { if (!m.stale && n[a.state] != null) n[a.state]++; }); });
    $("tab-agents").textContent = n.ask ? String(n.ask) : "";
    $("tab-agents").className = "agdot" + (n.ask ? " on" : "");
    if (d.loading) { $("ag-fresh").textContent = "読込中…"; return; }
    $("ag-tally").innerHTML = ["busy", "ask", "idle", "off"].map(function (k) {
      return '<div class="agt ' + k + '"><b>' + n[k] + "</b><span>" + (AG_LAB[k] || "閉じている") + "</span></div>";
    }).join("");
    $("ag-fresh").innerHTML = "<i></i>更新 " + esc(d.at || "") + (d.error ? " · 読めません: " + esc(d.error) : "");
    $("ag-lanes").innerHTML = (d.machines || []).map(function (m) {
      var note = m.error ? "読めません: " + m.error : m.stale ?
        (m.at ? "最後の書込 " + m.at.slice(11, 16) + " — 15分以上 届いていません" : "まだ一度も届いていません") : m.via;
      var rows = (m.rows || []).length ? m.rows.map(function (a) { return agRow(a, m.stale, m.label === "この PC" || !!m.launch, m.label === "この PC" ? "" : m.host); }).join("") :
        '<div class="empty">開いている窓はありません</div>';
      return '<section class="aglane"><header><h2>' + esc(m.label) + '<span class="aghost">' + esc(m.host) + "</span></h2>" +
        '<span class="agvia' + (m.stale ? " warn" : "") + '">' + esc(note) + "</span></header><div>" + rows + "</div></section>";
    }).join("");
  }
  $("ag-lanes").addEventListener("click", function (ev) {
    var b = ev.target.closest ? ev.target.closest(".aglaunch") : null;
    if (!b) return;
    ev.preventDefault();
    b.disabled = true;
    b.textContent = "起動中…";
    post("/api/agents/launch", { key: b.dataset.key, host: b.dataset.host || "" }).then(function (r) {
      var d = r.j || {};
      say(d.message || (d.ok ? "起動しました" : "起動できませんでした"));
      setTimeout(refreshAgents, 8000);               // 窓が開いて一覧に出るまで少し待つ
    });
  });
  function refreshAgents() {
    return getJSON("/api/agents").then(function (d) { paintAgents(d); if (d.loading) setTimeout(refreshAgents, 2000); })
      .catch(function () {});
  }
  setInterval(function () { if (!$("p-agents").hidden) refreshAgents(); }, 25000);
  setInterval(function () { if ($("p-agents").hidden) refreshAgents(); }, 120000);   // タブの橙の数だけ
  refreshAgents();
  // ---------------------------------------------------------------- リサーチ
  // 条件 (カテゴリ・形式・セラー国・並び) は tools/market_ledger.py が唯一の口。
  // ここで持つのは「どれを選んだか」だけ。
  var rsPreset = null, rsDays = null;

  function rsChips(box, items, get, set) {
    $(box).innerHTML = items.map(function (it) {
      var cls = get() === it.v ? "chip on" : "chip";
      return '<button type="button" class="' + cls + '" data-v="' + esc(it.v) + '">' +
             esc(it.t) + "</button>";
    }).join("");
    [].forEach.call($(box).querySelectorAll("button"), function (b) {
      b.onclick = function () {
        set(b.dataset.v);
        rsChips(box, items, get, set);
      };
    });
  }

  function rsOut(text) {
    var o = $("rs-out");
    o.hidden = !text;
    o.textContent = text || "";
  }

  function rsBusy(on, what) {
    ["rs-open", "rs-ingest", "rs-report"].forEach(function (id) { $(id).disabled = on; });
    if (on) $("rs-note").textContent = what + "…";
  }

  function initResearch() {
    getJSON("/api/research").then(function (d) {
      if (d.error) { $("rs-note").textContent = "使えません: " + d.error; return; }
      rsPreset = rsPreset || d.presets[0];
      rsDays = rsDays || String(d.default_days);
      rsChips("rs-presets", d.presets.map(function (p) { return { v: p, t: p }; }),
              function () { return rsPreset; }, function (v) { rsPreset = v; });
      rsChips("rs-ranges", Object.keys(d.ranges).map(function (k) {
        return { v: String(d.ranges[k]), t: k };
      }), function () { return rsDays; }, function (v) { rsDays = v; });
      $("rs-note").textContent = "台帳 " + Number(d.rows).toLocaleString("ja-JP") + "行";
    }).catch(function () { $("rs-note").textContent = "台帳を読めません"; });

    $("rs-open").onclick = function () {
      var tabs = [];
      if ($("rs-sold").checked) tabs.push("SOLD");
      if ($("rs-active").checked) tabs.push("ACTIVE");
      if (!tabs.length) { rsOut("売れた / 出ている のどちらかを選んでください"); return; }
      rsBusy(true, "開いています");
      post("/api/research/open", { preset: rsPreset, tabs: tabs, days: Number(rsDays) })
        .then(function (r) {
          var d = r.j || {};
          rsBusy(false);
          if (d.error) { rsOut("開けませんでした: " + d.error); return; }
          $("rs-note").textContent = "開きました (" + tabs.join(" / ") + ")";
          rsOut("ブラウザで「まとめて取る」を押してください。終わったら CSV で出して「取り込む」。");
        });
    };
    ["ingest", "report"].forEach(function (cmd) {
      $("rs-" + cmd).onclick = function () {
        rsBusy(true, cmd === "ingest" ? "取り込み中" : "集計中");
        post("/api/research/run", { cmd: cmd }).then(function (r) {
          var d = r.j || {};
          rsBusy(false);
          rsOut(d.text || d.error || "(何も返りませんでした)");
          if (d.rows != null) $("rs-note").textContent = "台帳 " + Number(d.rows).toLocaleString("ja-JP") + "行";
        });
      };
    });
  }
  initResearch();

  bootstrap();
  setInterval(function () {                    // 定期の更新でも、取れていなければ組み直す
    if (!buttons.length || !jobList.length) { bootstrap(); return; }
    refreshJobs();
  }, 60000);
  pollLog();
})();
