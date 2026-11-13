/* Dashboard UAS — tanpa library eksternal.
 * Sumber data: window.__DASHBOARD_DATA__ (HTML offline) atau /api/dashboard.
 * Semua angka dirender dari payload; tidak ada angka hasil hardcode.
 */
(function () {
  "use strict";

  var D = null;
  var charts = [];

  // ---------- util ----------
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function isNum(v) { return typeof v === "number" && isFinite(v); }
  function num(v, d) {
    if (!isNum(v)) return "—";
    d = d == null ? 2 : d;
    return v.toLocaleString("id-ID", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function idr(v) {
    if (!isNum(v)) return "—";
    return "Rp" + Math.round(v).toLocaleString("id-ID");
  }
  function pct(v, d) { // v sudah dalam persen
    if (!isNum(v)) return "—";
    d = d == null ? 2 : d;
    return (v > 0 ? "+" : "") + v.toLocaleString("id-ID", { minimumFractionDigits: d, maximumFractionDigits: d }) + "%";
  }
  function pctPlain(v, d) {
    if (!isNum(v)) return "—";
    d = d == null ? 2 : d;
    return v.toLocaleString("id-ID", { minimumFractionDigits: d, maximumFractionDigits: d }) + "%";
  }
  function cls(v) { return !isNum(v) || v === 0 ? "" : (v > 0 ? "pos" : "neg"); }
  function dt(ts, withTime) {
    if (ts == null) return "—";
    var d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
    if (isNaN(d.getTime())) return "—";
    var opt = { timeZone: "Asia/Jakarta", year: "numeric", month: "short", day: "2-digit" };
    if (withTime) { opt.hour = "2-digit"; opt.minute = "2-digit"; }
    return d.toLocaleString("id-ID", opt);
  }
  function dtUtc(ts, withTime) {
    if (ts == null) return "—";
    var d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
    if (isNaN(d.getTime())) return "—";
    var opt = { timeZone: "UTC", year: "numeric", month: "short", day: "2-digit" };
    if (withTime) { opt.hour = "2-digit"; opt.minute = "2-digit"; }
    return d.toLocaleString("id-ID", opt) + " UTC";
  }
  function dur(seconds) {
    if (!isNum(seconds) || seconds < 0) return "—";
    var d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return d + " hari " + h + " jam";
    if (h > 0) return h + " jam " + m + " menit";
    return m + " menit";
  }
  function statline(label, value, klass) {
    return '<div class="statline"><span>' + esc(label) + '</span><span class="' + (klass || "") + '">' + value + '</span></div>';
  }
  function kv(label, value) {
    return "<dt>" + esc(label) + "</dt><dd>" + value + "</dd>";
  }
  function note(kind, title, body) {
    var ico = { bad: "!", warn: "!", ok: "✓", info: "i" }[kind] || "i";
    return '<div class="note ' + kind + '"><div class="ico">' + ico + '</div><div><b>' + esc(title) + "</b><br>" + body + "</div></div>";
  }

  // ---------- chart ----------
  function makeChart(canvas, series, opts) {
    opts = opts || {};
    var st = { canvas: canvas, series: series, opts: opts, hover: null };
    charts.push(st);
    bindHover(st);
    drawChart(st);
    return st;
  }

  function drawChart(st) {
    var canvas = st.canvas, series = st.series, opts = st.opts;
    if (!canvas || !canvas.isConnected) return;
    var rect = canvas.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) return;
    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);

    var W = rect.width, H = rect.height;
    var pad = { l: 56, r: 16, t: 14, b: 28 };
    var pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    var xs = [], ys = [];
    series.forEach(function (s) {
      s.pts.forEach(function (p) {
        if (isNum(p[0]) && isNum(p[1])) { xs.push(p[0]); ys.push(p[1]); }
      });
    });
    if (!xs.length) return;
    var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs);
    var ymin = Math.min.apply(null, ys), ymax = Math.max.apply(null, ys);
    if (opts.zeroBase) { ymin = Math.min(0, ymin); ymax = Math.max(0, ymax); }
    if (ymin === ymax) { ymin -= 1; ymax += 1; }
    var span = ymax - ymin;
    ymin -= span * (opts.yPad == null ? 0.08 : opts.yPad);
    ymax += span * (opts.yPad == null ? 0.08 : opts.yPad);
    if (opts.forceZeroMax) ymax = 0;
    if (xmin === xmax) xmax = xmin + 1;

    function X(t) { return pad.l + (t - xmin) / (xmax - xmin) * pw; }
    function Y(v) { return pad.t + (ymax - v) / (ymax - ymin) * ph; }

    // grid
    ctx.font = "11px ui-monospace, Menlo, monospace";
    ctx.textBaseline = "middle";
    ctx.strokeStyle = "rgba(30,45,74,.75)";
    ctx.lineWidth = 1;
    ctx.fillStyle = "#8296b3";
    ctx.textAlign = "right";
    for (var i = 0; i <= 4; i++) {
      var v = ymin + (ymax - ymin) * i / 4;
      var y = Y(v);
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
      var lab = opts.yFmt ? opts.yFmt(v) : num(v, 0);
      ctx.fillText(lab, pad.l - 8, y);
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (var j = 0; j <= 5; j++) {
      var t = xmin + (xmax - xmin) * j / 5;
      var x = X(t);
      ctx.strokeStyle = "rgba(30,45,74,.45)";
      ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + ph); ctx.stroke();
      ctx.fillStyle = "#8296b3";
      var lbl = opts.xFmt ? opts.xFmt(t) : dt(t);
      ctx.fillText(lbl, Math.max(24, Math.min(W - 24, x)), pad.t + ph + 8);
    }

    // series
    series.forEach(function (s) {
      if (!s.pts.length) return;
      ctx.save();
      ctx.strokeStyle = s.color;
      ctx.lineWidth = s.width || 1.7;
      ctx.beginPath();
      var started = false;
      s.pts.forEach(function (p) {
        if (!isNum(p[0]) || !isNum(p[1])) return;
        var x = X(p[0]), y = Y(p[1]);
        if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
      });
      if (s.dash) ctx.setLineDash([5, 4]);
      if (s.fill) {
        var first = s.pts[0], last = s.pts[s.pts.length - 1];
        ctx.lineTo(X(last[0]), Y(opts.zeroBase ? 0 : ymin));
        ctx.lineTo(X(first[0]), Y(opts.zeroBase ? 0 : ymin));
        ctx.closePath();
        ctx.globalAlpha = 0.16;
        ctx.fillStyle = s.color;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.beginPath();
        s.pts.forEach(function (p, k) {
          var xx = X(p[0]), yy = Y(p[1]);
          if (k === 0) ctx.moveTo(xx, yy); else ctx.lineTo(xx, yy);
        });
      }
      ctx.stroke();
      ctx.restore();
    });

    // hover
    if (st.hover != null && st.hover >= xmin && st.hover <= xmax) {
      var hx = X(st.hover);
      ctx.strokeStyle = "rgba(148,163,184,.55)";
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(hx, pad.t); ctx.lineTo(hx, pad.t + ph); ctx.stroke();
      ctx.setLineDash([]);
      series.forEach(function (s) {
        var best = null, bd = Infinity;
        s.pts.forEach(function (p) {
          var dd = Math.abs(p[0] - st.hover);
          if (dd < bd) { bd = dd; best = p; }
        });
        if (best) {
          ctx.beginPath();
          ctx.arc(X(best[0]), Y(best[1]), 3.6, 0, Math.PI * 2);
          ctx.fillStyle = s.color;
          ctx.fill();
          ctx.strokeStyle = "#0b1220";
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      });
    }
    st._geom = { pad: pad, W: W, H: H, xmin: xmin, xmax: xmax, X: X, Y: Y };
  }

  function bindHover(st) {
    var canvas = st.canvas, tip = $("tooltip");
    var raf = null;
    canvas.addEventListener("mousemove", function (e) {
      var g = st._geom;
      if (!g) return;
      var r = canvas.getBoundingClientRect();
      var mx = e.clientX - r.left;
      if (mx < g.pad.l || mx > g.W - g.pad.r) { leave(); return; }
      var t = g.xmin + (mx - g.pad.l) / (g.W - g.pad.l - g.pad.r) * (g.xmax - g.xmin);
      st.hover = t;
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(function () {
        drawChart(st);
        var rows = st.series.map(function (s) {
          var best = null, bd = Infinity;
          s.pts.forEach(function (p) { var dd = Math.abs(p[0] - t); if (dd < bd) { bd = dd; best = p; } });
          if (!best) return "";
          var val = st.opts.tipFmt ? st.opts.tipFmt(best[1]) : num(best[1], 2);
          return '<div class="row"><span><i style="background:' + s.color + '"></i>' + esc(s.name) + "</span><span>" + val + "</span></div>";
        }).join("");
        tip.innerHTML = '<div class="t">' + esc(st.opts.xTip ? st.opts.xTip(t) : dt(t, true)) + "</div>" + rows;
        tip.style.display = "block";
        var tw = tip.offsetWidth, th = tip.offsetHeight;
        var left = e.clientX + 14, top = e.clientY + 14;
        if (left + tw > window.innerWidth - 8) left = e.clientX - tw - 14;
        if (top + th > window.innerHeight - 8) top = e.clientY - th - 14;
        tip.style.left = left + "px";
        tip.style.top = top + "px";
      });
    });
    canvas.addEventListener("mouseleave", leave);
    function leave() {
      st.hover = null;
      if (tip) tip.style.display = "none";
      drawChart(st);
    }
  }

  function normalize(points) {
    var arr = points.filter(function (p) { return isNum(p.t) && isNum(p.equity); });
    if (!arr.length) return [];
    var base = arr[0].equity;
    if (!base) return [];
    return arr.map(function (p) { return [p.t, p.equity / base * 100]; });
  }
  function drawdownSeries(points) {
    var peak = -Infinity;
    return points.filter(function (p) { return isNum(p.t) && isNum(p.equity); }).map(function (p) {
      peak = Math.max(peak, p.equity);
      return [p.t, (p.equity / peak - 1) * 100];
    });
  }

  // ---------- render ----------
  function render() {
    var meta = D.meta || {}, bt = D.backtest || {}, fwd = D.forward || {}, st = D.status || {};
    var m = bt.metrics || {}, bm = (bt.benchmark || {}).metrics || {}, oos = (bt.oos || {}).metrics || {};
    var ps = D.project_status || {};
    var freeze = meta.freeze;
    var freezeLate = freeze && new Date(freeze).getTime() > new Date("2026-11-04T12:00:00+07:00").getTime();
    var fwdDays = fwd.duration_days || 0;

    // hero chips
    var chips = [];
    chips.push('<span class="chip"><span class="dot ' + (meta.freeze ? "warn" : "bad") + '"></span>Freeze: <b>' + (freeze ? dt(freeze) : "belum") + "</b></span>");
    chips.push('<span class="chip"><span class="dot ' + (fwd.start ? "ok" : "bad") + '"></span>Forward: <b>' + (fwd.start ? num(fwdDays, 1) + " hari" : "belum mulai") + "</b></span>");
    chips.push('<span class="chip"><span class="dot ' + (st.kill_switch ? "bad" : "ok") + '"></span>Kill switch: <b>' + (st.kill_switch ? "AKTIF" : "off") + "</b></span>");
    chips.push('<span class="chip"><span class="dot ok"></span>Storage: <b>' + esc(meta.storage || "—") + "</b></span>");
    if (ps.vercel_deployed) chips.push('<span class="chip"><span class="dot ok"></span>Vercel: <b>live</b></span>');
    else chips.push('<span class="chip"><span class="dot warn"></span>Vercel: <b>belum deploy</b></span>');
    $("heroChips").innerHTML = chips.join("");

    $("heroMeta").innerHTML = [
      "<span>Mahasiswa <b>Anindya Rahma Luthfia</b></span>",
      "<span>NIM <b>25110200036</b></span>",
      "<span>Timeframe <b>4 jam</b></span>",
      "<span>Universe <b>" + esc((meta.universe || []).join(", ")) + "</b></span>",
      "<span>Data <b>Indodax public API</b></span>",
      "<span>Diperbarui <b>" + esc(dt(meta.generated_at, true)) + "</b></span>"
    ].join("");

    // KPI
    var kpis = [
      { label: "CAGR backtest", value: pct(m.cagr_pct), foot: num(m.years, 2) + " tahun, 4 jam", cls: cls(m.cagr_pct) },
      { label: "Total return", value: pct(m.total_return_pct), foot: "Rp100 jt → " + idr(m.final_equity), cls: cls(m.total_return_pct) },
      { label: "Max drawdown", value: pctPlain(m.max_drawdown_pct), foot: "Puncak-ke-palung", cls: m.max_drawdown_pct < -20 ? "neg" : "warn" },
      { label: "Profit factor", value: num(m.profit_factor), foot: m.trades + " trade · win " + num(m.win_rate_pct, 1) + "%", cls: m.profit_factor > 1 ? "pos" : "neg" }
    ];
    $("kpis").innerHTML = kpis.map(function (k) {
      return '<div class="card kpi ' + k.cls + '"><div class="label">' + esc(k.label) + '</div><div class="value">' + k.value + '</div><div class="foot">' + esc(k.foot) + "</div></div>";
    }).join("");

    // honesty notes
    var notes = [];
    if (isNum(oos.cagr_pct) && oos.cagr_pct < 0) {
      notes.push(note("bad", "OOS negatif — jangan diklaim validasi berhasil",
        "Pada 30% data terakhir (OOS), CAGR <b>" + pct(oos.cagr_pct) + "</b> dan MDD <b>" + pctPlain(oos.max_drawdown_pct) + "</b>. Parameter hanya dipilih dari in-sample; OOS dipakai sekali dan hasilnya negatif. Ini keterbatasan strategi, bukan bukti keberhasilan."));
    }
    if (freezeLate) {
      notes.push(note("warn", "Freeze terlambat",
        "Deadline tugas <b>4 Nov 2026 12:00 WIB</b>. Freeze aktual <b>" + esc(dt(freeze, true)) + "</b>. Tidak ada commit yang dimundurkan tanggalnya; konsekuensinya dijelaskan di laporan dan docs/FREEZE.md."));
    } else if (!freeze) {
      notes.push(note("bad", "Freeze belum ditetapkan", "Konfigurasi belum memuat timestamp freeze. Isi setelah kode dan test selesai."));
    }
    if (fwd.start && fwdDays < 10) {
      notes.push(note("warn", "Forward test belum 10 hari",
        "Baru <b>" + num(fwdDays, 2) + " hari</b> sejak " + esc(dt(fwd.start, true)) + ". Durasi sebenarnya dilaporkan apa adanya; tidak ada log yang dibuat ulang."));
    }
    if (isNum(m.cagr_pct) && isNum(bm.cagr_pct)) {
      notes.push(note("info", "Dibanding beli-dan-tahan BTC",
        "CAGR strategi <b>" + pct(m.cagr_pct) + "</b> vs BTC <b>" + pct(bm.cagr_pct) + "</b>; MDD strategi <b>" + pctPlain(m.max_drawdown_pct) + "</b> vs BTC <b>" + pctPlain(bm.max_drawdown_pct) + "</b>. " + (m.cagr_pct < bm.cagr_pct ? "Strategi <b>kalah return</b> dari BTC, tetapi drawdownnya lebih kecil. Ini harus ditulis apa adanya." : "Strategi unggul return pada periode ini, tetapi tetap dievaluasi pada OOS yang negatif.")));
    }
    if (isNum(m.cost_share_of_gross_profit)) {
      notes.push(note("info", "Biaya bukan angka kosong",
        "Fee + spread + slippage = <b>" + idr(m.total_cost_idr) + "</b>, setara <b>" + pctPlain(m.cost_share_of_gross_profit * 100) + "</b> dari gross profit. Ketiganya dihitung terpisah dan mengurangi PnL."));
    }
    $("honestyNotes").innerHTML = notes.join("");

    // status
    $("statusList").innerHTML = [
      statline("Tick terakhir", esc(st.last_tick ? dt(st.last_tick, true) : "belum pernah")),
      statline("Jumlah tick", num(st.ticks_total, 0)),
      statline("Forward mulai", esc(fwd.start ? dt(fwd.start, true) : "belum")),
      statline("Durasi forward", fwd.start ? num(fwdDays, 2) + " hari" : "—"),
      statline("Posisi terbuka", num((fwd.open_positions || []).length, 0)),
      statline("Kill switch", st.kill_switch ? '<span class="neg">AKTIF</span>' : "off"),
      statline("Daily loss block", st.daily_loss_blocked ? '<span class="neg">AKTIF</span>' : "tidak"),
      statline("Total error", num(st.errors_total, 0), st.errors_total > 0 ? "neg" : "pos"),
      statline("Storage", esc(meta.storage || "—"))
    ].join("");

    // summary stats
    var fwdM = fwd.metrics || {};
    $("summaryStats").innerHTML = [
      statline("Return backtest", '<span class="' + cls(m.total_return_pct) + '">' + pct(m.total_return_pct) + "</span>"),
      statline("CAGR / MDD", pct(m.cagr_pct) + " / " + pctPlain(m.max_drawdown_pct)),
      statline("Trade / win rate", num(m.trades, 0) + " / " + num(m.win_rate_pct, 1) + "%"),
      statline("IS CAGR", pct(((bt.is || {}).metrics || {}).cagr_pct)),
      statline("OOS CAGR", '<span class="neg">' + pct(oos.cagr_pct) + "</span>"),
      statline("Benchmark BTC CAGR", pct(bm.cagr_pct)),
      statline("Return forward", fwd.start ? pct(fwdM.total_return_pct) : "belum ada"),
      statline("Trade forward", fwd.start ? num(fwdM.trades, 0) : "—")
    ].join("");

    // summary chart
    var daily = (bt.daily_equity || []).map(function (p) { return { t: p.t, equity: p.equity }; });
    var bench = ((bt.benchmark || {}).equity || []).map(function (p) { return { t: p.t, equity: p.equity }; });
    var s1 = normalize(daily), s2 = normalize(bench);
    if (s1.length) {
      makeChart($("summaryChart"), [
        { name: "Strategi", color: "#38bdf8", pts: s1, fill: true },
        { name: "BTC", color: "#f59e0b", pts: s2, dash: true }
      ], { yFmt: function (v) { return num(v, 0); }, tipFmt: function (v) { return num(v, 1); } });
      $("summaryLegend").innerHTML = '<span><i style="background:#38bdf8"></i>Strategi</span><span><i style="background:#f59e0b"></i>BTC beli-dan-tahan</span><span>Skala: 100 = modal awal</span>';
    } else {
      $("summaryChartWrap").innerHTML = '<div class="empty">Data backtest belum tersedia.<br>Jalankan <code>python3 scripts/backtest.py --final</code>.</div>';
    }

    // backtest charts
    if (s1.length) {
      makeChart($("btEquity"), [
        { name: "Strategi", color: "#38bdf8", pts: s1, fill: true },
        { name: "BTC", color: "#f59e0b", pts: s2, dash: true }
      ], { yFmt: function (v) { return num(v, 0); }, tipFmt: function (v) { return num(v, 1); } });
      $("btEquityLegend").innerHTML = '<span><i style="background:#38bdf8"></i>Strategi</span><span><i style="background:#f59e0b"></i>BTC</span>';
      var dd = drawdownSeries(daily);
      makeChart($("btDrawdown"), [{ name: "Drawdown", color: "#f43f5e", pts: dd, fill: true }],
        { zeroBase: true, forceZeroMax: true, yFmt: function (v) { return num(v, 1) + "%"; }, tipFmt: function (v) { return num(v, 2) + "%"; } });
      $("btDdLegend").innerHTML = '<span><i style="background:#f43f5e"></i>Drawdown dari puncak</span>';
    } else {
      $("btEquityWrap").innerHTML = '<div class="empty">Belum ada data.</div>';
      $("btDdWrap").innerHTML = '<div class="empty">Belum ada data.</div>';
    }

    // split table
    var rows = [["Full", bt.meta && bt.meta.period_start, bt.meta && bt.meta.period_end, m],
                ["In-sample 70%", (bt.is || {}).start, (bt.is || {}).end, (bt.is || {}).metrics || {}],
                ["Out-of-sample 30%", (bt.oos || {}).start, (bt.oos || {}).end, oos]];
    $("splitTable").innerHTML = "<thead><tr><th>Periode</th><th>Mulai</th><th>Selesai</th><th>CAGR</th><th>Return</th><th>MDD</th><th>Trade</th></tr></thead><tbody>" +
      rows.map(function (r) {
        return "<tr><td>" + esc(r[0]) + "</td><td>" + esc(r[1] ? dt(r[1]) : "—") + "</td><td>" + esc(r[2] ? dt(r[2]) : "—") +
          '</td><td class="mono ' + cls(r[3].cagr_pct) + '">' + pct(r[3].cagr_pct) + '</td><td class="mono ' + cls(r[3].total_return_pct) + '">' + pct(r[3].total_return_pct) +
          '</td><td class="mono neg">' + pctPlain(r[3].max_drawdown_pct) + '</td><td class="mono">' + num(r[3].trades, 0) + "</td></tr>";
      }).join("") + "</tbody>";
    $("oosNote").innerHTML = note("bad", "Cara membaca",
      "Parameter dipilih memakai in-sample saja. OOS <b>tidak</b> dipakai untuk memilih, sehingga angka OOS " + pct(oos.cagr_pct) + " adalah uji jujur dan hasilnya negatif. Jangan menyembunyikan baris ini.");

    // stress
    var stressRows = [
      ["Baseline", m],
      ["Fee taker 2x", ((bt.stress || {}).fee_2x || {}).metrics || {}],
      ["Spread + slippage 2x", ((bt.stress || {}).cost_2x || {}).metrics || {}],
      ["Eksekusi delay 1 bar", ((bt.stress || {}).delay_1_bar || {}).metrics || {}]
    ];
    $("stressTable").innerHTML = "<thead><tr><th>Skenario</th><th>CAGR</th><th>Return</th><th>MDD</th><th>Trade</th></tr></thead><tbody>" +
      stressRows.map(function (r) {
        return "<tr><td>" + esc(r[0]) + '</td><td class="mono ' + cls(r[1].cagr_pct) + '">' + pct(r[1].cagr_pct) +
          '</td><td class="mono ' + cls(r[1].total_return_pct) + '">' + pct(r[1].total_return_pct) +
          '</td><td class="mono neg">' + pctPlain(r[1].max_drawdown_pct) + '</td><td class="mono">' + num(r[1].trades, 0) + "</td></tr>";
      }).join("") + "</tbody>";

    // metrics table
    var metricRows = [
      ["Total return", pct(m.total_return_pct), cls(m.total_return_pct)],
      ["CAGR", pct(m.cagr_pct), cls(m.cagr_pct)],
      ["Max drawdown", pctPlain(m.max_drawdown_pct), "neg"],
      ["Profit factor", num(m.profit_factor), m.profit_factor > 1 ? "pos" : "neg"],
      ["Win rate", num(m.win_rate_pct, 1) + "% (" + m.wins + "/" + m.trades + ")", ""],
      ["Jumlah trade", num(m.trades, 0), ""],
      ["Rata-rata win", idr(m.avg_win_idr), "pos"],
      ["Rata-rata loss", idr(m.avg_loss_idr), "neg"],
      ["Rata-rata win %", pct(m.avg_win_pct), "pos"],
      ["Rata-rata loss %", pct(m.avg_loss_pct), "neg"],
      ["Gross profit", idr(m.gross_profit_idr), "pos"],
      ["Gross loss", idr(m.gross_loss_idr), "neg"],
      ["Net PnL", idr(m.net_pnl_idr), cls(m.net_pnl_idr)],
      ["Fee", idr(m.fee_idr), "neg"],
      ["Spread", idr(m.spread_cost_idr), "neg"],
      ["Slippage", idr(m.slippage_cost_idr), "neg"],
      ["Total biaya", idr(m.total_cost_idr), "neg"],
      ["Biaya / gross profit", pctPlain(m.cost_share_of_gross_profit * 100), "neg"],
      ["Final equity", idr(m.final_equity), ""],
      ["Modal awal", idr(m.initial_capital), ""],
      ["Periode", num(m.years, 2) + " tahun", ""]
    ];
    $("btMetrics").innerHTML = "<thead><tr><th>Metrik</th><th>Nilai</th></tr></thead><tbody>" +
      metricRows.map(function (r) { return "<tr><td>" + esc(r[0]) + '</td><td class="mono ' + r[2] + '">' + r[1] + "</td></tr>"; }).join("") + "</tbody>";

    // yearly
    var yearly = bt.yearly || {};
    var ykeys = Object.keys(yearly).sort();
    $("yearlyTable").innerHTML = "<thead><tr><th>Tahun</th><th>Equity akhir</th><th>Return</th></tr></thead><tbody>" +
      (ykeys.length ? ykeys.map(function (y) {
        var v = yearly[y];
        return "<tr><td>" + esc(y) + '</td><td class="mono">' + idr(v.equity) + '</td><td class="mono ' + cls(v.return * 100) + '">' + pct(v.return * 100) + "</td></tr>";
      }).join("") : '<tr><td colspan="3" class="mut">Belum ada data.</td></tr>') + "</tbody>";

    // monthly
    var monthly = (bt.monthly || []).slice().sort(function (a, b) { return b.month.localeCompare(a.month); });
    $("monthlyTable").innerHTML = "<thead><tr><th>Bulan</th><th>Equity</th><th>Return</th></tr></thead><tbody>" +
      (monthly.length ? monthly.map(function (v) {
        return "<tr><td>" + esc(v.month) + '</td><td class="mono">' + idr(v.equity) + '</td><td class="mono ' + cls(v.return * 100) + '">' + pct(v.return * 100) + "</td></tr>";
      }).join("") : '<tr><td colspan="3" class="mut">Belum ada data.</td></tr>') + "</tbody>";

    // trades
    var trades = (bt.trades || []).slice().reverse();
    $("tradesHint").innerHTML = esc(trades.length + " trade tertutup. Kolom biaya memisahkan fee, spread, dan slippage. Diurutkan dari yang terbaru.");
    $("tradesTable").innerHTML = "<thead><tr><th>Pair</th><th>Masuk</th><th>Keluar</th><th>Qty</th><th>Entry fill</th><th>Exit fill</th><th>Net PnL</th><th>Net %</th><th>Fee</th><th>Spread</th><th>Slippage</th><th>Bar</th><th>Alasan</th></tr></thead><tbody>" +
      (trades.length ? trades.map(function (t) {
        return "<tr><td>" + esc(t.pair) + "</td><td>" + esc(dt(t.entry_time)) + "</td><td>" + esc(dt(t.exit_time)) +
          '</td><td class="mono">' + num(t.qty, 4) + '</td><td class="mono">' + num(t.entry_fill, 0) + '</td><td class="mono">' + num(t.exit_fill, 0) +
          '</td><td class="mono ' + cls(t.net_pnl) + '">' + idr(t.net_pnl) + '</td><td class="mono ' + cls(t.net_pct) + '">' + pct(t.net_pct) +
          '</td><td class="mono neg">' + idr(t.fee_total) + '</td><td class="mono neg">' + idr(t.spread_cost) + '</td><td class="mono neg">' + idr(t.slippage_cost) +
          '</td><td class="mono">' + num(t.holding_bars, 0) + '</td><td>' + esc(t.exit_reason) + "</td></tr>";
      }).join("") : '<tr><td colspan="13" class="mut">Belum ada trade.</td></tr>') + "</tbody>";

    // sensitivity
    var sens = bt.sensitivity || [];
    $("sensitivityTable").innerHTML = "<thead><tr><th>Parameter</th><th>Perubahan</th><th>Nilai</th><th>CAGR</th><th>MDD</th><th>Calmar</th><th>Trade</th><th>PF</th></tr></thead><tbody>" +
      (sens.length ? sens.map(function (s) {
        return "<tr><td>" + esc(s.param) + "</td><td>" + esc((s.mult > 1 ? "+" : "") + Math.round((s.mult - 1) * 100) + "%") +
          '</td><td class="mono">' + num(s.value, s.param === "atr_mult" ? 1 : 0) + '</td><td class="mono ' + cls(s.cagr) + '">' + pct((s.cagr || 0) * 100) +
          '</td><td class="mono neg">' + pctPlain((s.mdd || 0) * 100) + '</td><td class="mono">' + num(s.calmar) +
          '</td><td class="mono">' + num(s.trades, 0) + '</td><td class="mono">' + num(s.pf) + "</td></tr>";
      }).join("") : '<tr><td colspan="8" class="mut">Belum ada data.</td></tr>') + "</tbody>";

    // forward
    var fm = fwd.metrics || {};
    if (fwd.start) {
      if (fwdDays < 10) {
        $("fwdBanner").innerHTML = note("warn", "Forward test berjalan, belum memenuhi target 10 hari",
          "Mulai <b>" + esc(dt(fwd.start, true)) + "</b>, durasi <b>" + num(fwdDays, 2) + " hari</b>. Yang dilaporkan hanya tick yang benar-benar terjadi. Tidak ada replay masa lalu yang diklaim sebagai forward test.");
      } else {
        $("fwdBanner").innerHTML = note("ok", "Forward test ≥ 10 hari", "Mulai " + esc(dt(fwd.start, true)) + ", durasi " + num(fwdDays, 2) + " hari.");
      }
    } else {
      $("fwdBanner").innerHTML = note("info", "Forward test belum dimulai", "Jalankan tick pertama dengan <code>python3 scripts/run_tick.py</code> atau melalui scheduler. Timestamp mulai akan tercatat otomatis dan tidak bisa dimundurkan.");
    }
    var fk = [
      { label: "Return forward", value: pct(fm.total_return_pct), foot: "Modal Rp100 jt", cls: cls(fm.total_return_pct) },
      { label: "Ekuitas", value: idr(fm.final_equity), foot: "Cash " + idr((fwd.state || {}).cash), cls: "" },
      { label: "Trade", value: num(fm.trades, 0), foot: "Win " + num(fm.win_rate_pct, 1) + "%", cls: "" },
      { label: "Durasi", value: num(fwdDays, 2) + " hari", foot: "Target 10 hari", cls: fwdDays >= 10 ? "pos" : "warn" }
    ];
    $("fwdKpis").innerHTML = fk.map(function (k) {
      return '<div class="card kpi ' + k.cls + '"><div class="label">' + esc(k.label) + '</div><div class="value sm">' + k.value + '</div><div class="foot">' + esc(k.foot) + "</div></div>";
    }).join("");

    // Kecocokan backtest vs forward pada jendela yang sama (rubrik 25%).
    var fvb = D.forward_vs_backtest || {};
    var fs = fvb.summary || {};
    if (fvb.window && fs.expected_pair_candles) {
      var btW = (fvb.backtest_window || {}).metrics || {};
      var fwW = fvb.forward_window || {};
      var fwM = fwd.metrics || {};
      var pairRows = Object.keys(fvb.per_pair || {}).map(function (p) {
        var x = fvb.per_pair[p] || {};
        var mrate = x.signal_match_rate;
        return "<tr><td>" + esc(p) + '</td><td class="mono">' + num(x.expected, 0) +
          '</td><td class="mono">' + num(x.processed, 0) +
          '</td><td class="mono pos">' + num(x.signal_match, 0) +
          '</td><td class="mono ' + (x.signal_mismatch ? "neg" : "") + '">' + num(x.signal_mismatch, 0) +
          '</td><td class="mono warn">' + num(x.missing, 0) +
          '</td><td class="mono">' + (isNum(mrate) ? pctPlain(mrate * 100, 1) : "—") + "</td></tr>";
      }).join("");
      var coverage = fs.coverage_rate;
      var matchRate = fs.signal_match_rate;
      $("fwdCompare").innerHTML =
        '<div class="grid g4" style="margin-bottom:14px">' +
        '<div class="card kpi"><div class="label">Jendela</div><div class="value sm">' +
        esc(dt(fvb.window.first_candle, true)) + '<br>→ ' + esc(dt(fvb.window.last_candle, true)) +
        '</div><div class="foot">' + num(fvb.window.candles_per_pair, 0) + " candle/pair</div></div>" +
        '<div class="card kpi ' + (isNum(matchRate) && matchRate >= 1 ? "pos" : "warn") + '"><div class="label">Sinyal cocok</div><div class="value sm">' +
        (isNum(matchRate) ? pctPlain(matchRate * 100, 1) : "—") +
        '</div><div class="foot">' + num(fs.signal_match, 0) + "/" + num(fs.signal_checked, 0) + " candle diperiksa</div></div>" +
        '<div class="card kpi ' + (isNum(coverage) && coverage >= 0.95 ? "pos" : "warn") + '"><div class="label">Cakupan candle</div><div class="value sm">' +
        (isNum(coverage) ? pctPlain(coverage * 100, 1) : "—") +
        '</div><div class="foot">' + num(fs.processed_pair_candles, 0) + "/" + num(fs.expected_pair_candles, 0) + " pair-candle</div></div>" +
        '<div class="card kpi"><div class="label">Return jendela</div><div class="value sm">BT ' + pct(btW.total_return_pct) +
        '<br>FWD ' + pct(fwM.total_return_pct) + '</div><div class="foot">Trade BT ' + num((fvb.backtest_window || {}).trades ? (fvb.backtest_window.trades || []).length : 0, 0) +
        " · FWD " + num(fwW.trade_count, 0) + "</div></div>" +
        "</div>" +
        '<div class="tbl-scroll" style="max-height:none"><table><thead><tr><th>Pair</th><th>Candle diharapkan</th><th>Diproses</th><th>Cocok</th><th>Mismatch</th><th>Missing</th><th>Match rate</th></tr></thead><tbody>' +
        pairRows + "</tbody></table></div>" +
        '<p class="hint" style="margin-top:10px">' + esc(fvb.definition || "") +
        " Candle yang tidak diproses dihitung <b>missing</b>, bukan mismatch, sehingga match rate tidak menutupi gap jadwal. " +
        "Backtest jendela: return " + pct(btW.total_return_pct) + ", " + num(((fvb.backtest_window || {}).trades || []).length, 0) +
        " trade; forward: return " + pct(fwM.total_return_pct) + ", " + num(fwW.trade_count, 0) + " trade.</p>";
    } else {
      $("fwdCompare").innerHTML = note("info", "Perbandingan belum tersedia",
        "Jalankan <code>python3 scripts/forward_vs_backtest.py</code> setelah forward test berjalan untuk mengisi bagian ini. Skrip memakai candle yang sama dan fungsi sinyal yang sama.");
    }

    var fe = normalize((fwd.equity || []));
    if (fe.length > 1) {
      makeChart($("fwdChart"), [{ name: "Forward", color: "#22c55e", pts: fe, fill: true }],
        { yFmt: function (v) { return num(v, 1); }, tipFmt: function (v) { return num(v, 3); } });
      $("fwdLegend").innerHTML = '<span><i style="background:#22c55e"></i>Ekuitas / modal awal × 100</span>';
    } else {
      $("fwdChartWrap").innerHTML = '<div class="empty">Belum ada cukup titik ekuitas.<br>Forward test dimulai saat tick sukses pertama.</div>';
    }

    $("fwdStatus").innerHTML = [
      statline("Mulai", esc(fwd.start ? dt(fwd.start, true) : "belum")),
      statline("Selesai / data terakhir", esc(dt(fwd.end, true))),
      statline("Durasi", fwd.start ? num(fwdDays, 2) + " hari" : "—"),
      statline("Tick", num((fwd.state || {}).tick_count, 0)),
      statline("Equity", idr((fwd.state || {}).equity)),
      statline("Cash", idr((fwd.state || {}).cash)),
      statline("Posisi", num((fwd.open_positions || []).length, 0)),
      statline("Daily loss block", (fwd.state || {}).daily_loss_blocked ? '<span class="neg">AKTIF</span>' : "tidak"),
      statline("Kill switch", fwd.kill_switch ? '<span class="neg">AKTIF</span>' : "off")
    ].join("");

    var pos = fwd.open_positions || [];
    $("positionsTable").innerHTML = "<thead><tr><th>Pair</th><th>Qty</th><th>Entry</th><th>Harga kini</th><th>Nilai</th><th>Unrealized</th><th>Stop</th></tr></thead><tbody>" +
      (pos.length ? pos.map(function (p) {
        return "<tr><td>" + esc(p.pair) + '</td><td class="mono">' + num(p.qty, 4) + "</td><td>" + esc(dt(p.entry_time)) +
          '</td><td class="mono">' + num(p.last_price, 0) + '</td><td class="mono">' + idr(p.value) +
          '</td><td class="mono ' + cls(p.unrealized_pnl) + '">' + idr(p.unrealized_pnl) + " (" + pct(p.unrealized_pct) +
          ')</td><td class="mono">' + num(p.stop, 0) + "</td></tr>";
      }).join("") : '<tr><td colspan="7" class="mut">Tidak ada posisi terbuka. Bot hanya masuk jika sinyal terpenuhi.</td></tr>') + "</tbody>";

    var ft = (fwd.trades || []).slice().reverse();
    $("fwdTradesTable").innerHTML = "<thead><tr><th>Pair</th><th>Masuk</th><th>Keluar</th><th>Net PnL</th><th>Net %</th><th>Biaya</th><th>Alasan</th></tr></thead><tbody>" +
      (ft.length ? ft.map(function (t) {
        return "<tr><td>" + esc(t.pair) + "</td><td>" + esc(dt(t.entry_time)) + "</td><td>" + esc(dt(t.exit_time)) +
          '</td><td class="mono ' + cls(t.net_pnl) + '">' + idr(t.net_pnl) + '</td><td class="mono ' + cls(t.net_pct) + '">' + pct(t.net_pct) +
          '</td><td class="mono neg">' + idr(t.fee_total) + '</td><td>' + esc(t.exit_reason) + "</td></tr>";
      }).join("") : '<tr><td colspan="7" class="mut">Belum ada trade forward.</td></tr>') + "</tbody>";

    var dec = (fwd.decisions || []).slice().reverse();
    $("decisionsTable").innerHTML = "<thead><tr><th>Waktu</th><th>Pair</th><th>Aksi</th><th>Alasan</th><th>Candle</th><th>Spread</th></tr></thead><tbody>" +
      (dec.length ? dec.map(function (d) {
        var b = d.action === "buy" ? "buy" : d.action === "sell" ? "sell" : (d.action || "").indexOf("kill") === 0 ? "warn" : "skip";
        return "<tr><td>" + esc(dt(d.processed_at || d.at, true)) + "</td><td>" + esc(d.pair || "—") +
          '</td><td><span class="badge ' + b + '">' + esc(d.action || "—") + '</span></td><td class="small">' + esc(d.reason || "") +
          "</td><td>" + esc(d.candle_time ? dt(d.candle_time, true) : "—") +
          '</td><td class="mono">' + (isNum(d.spread_pct) ? pctPlain(d.spread_pct * 100, 3) : "—") + "</td></tr>";
      }).join("") : '<tr><td colspan="6" class="mut">Belum ada keputusan.</td></tr>') + "</tbody>";

    var orders = (fwd.orders || []).slice().reverse();
    $("ordersTable").innerHTML = "<thead><tr><th>Waktu</th><th>Pair</th><th>Sisi</th><th>Qty</th><th>Bid</th><th>Ask</th><th>Fill</th><th>Fee</th><th>Deviasi</th><th>Level</th></tr></thead><tbody>" +
      (orders.length ? orders.map(function (o) {
        return "<tr><td>" + esc(dt(o.at, true)) + "</td><td>" + esc(o.pair) + '</td><td><span class="badge ' + (o.side === "buy" ? "buy" : "sell") + '">' + esc(o.side) +
          '</span></td><td class="mono">' + num(o.qty, 4) + '</td><td class="mono">' + num(o.best_bid, 0) + '</td><td class="mono">' + num(o.best_ask, 0) +
          '</td><td class="mono">' + num(o.fill_price, 0) + '</td><td class="mono neg">' + idr(o.fee) +
          '</td><td class="mono ' + cls(-(o.deviation_vs_signal_pct || 0)) + '">' + pct(o.deviation_vs_signal_pct) +
          '</td><td class="mono">' + num(o.levels_used, 0) + (o.complete ? "" : " (parsial)") + "</td></tr>";
      }).join("") : '<tr><td colspan="10" class="mut">Belum ada order. Order hanya dibuat jika sinyal dan order book memenuhi syarat.</td></tr>') + "</tbody>";

    var up = fwd.uptime || {};
    $("uptimeCard").innerHTML = [
      statline("Candle diharapkan", num(up.expected, 0)),
      statline("Tepat waktu", num(up.on_time, 0)),
      statline("Uptime", isNum(up.uptime) ? pctPlain(up.uptime * 100, 1) : "—", isNum(up.uptime) && up.uptime >= 0.9 ? "pos" : "warn"),
      statline("Candle terlihat", num(up.processed_candles, 0)),
      '<p class="hint" style="margin-top:10px">' + esc(up.definition || "") + "</p>"
    ].join("");

    var klog = (fwd.kill_log || []).slice().reverse();
    $("killCard").innerHTML = [
      statline("Status", fwd.kill_switch ? '<span class="neg">AKTIF — entry diblokir</span>' : '<span class="pos">off</span>'),
      statline("Perubahan terakhir", esc(klog.length ? dt(klog[0].at, true) : "belum ada")),
      klog.length ? '<div class="hint" style="margin-top:10px">' + klog.slice(0, 4).map(function (k) {
        return esc(dt(k.at, true)) + " · " + esc(k.actor || "") + " · " + (k.on ? "ON" : "OFF") + (k.note ? " · " + esc(k.note) : "");
      }).join("<br>") + "</div>" : '<p class="hint" style="margin-top:10px">Belum ada perubahan manual.</p>'
    ].join("");

    var errs = (fwd.errors || []).slice().reverse();
    $("errorsCard").innerHTML = errs.length ? '<div class="hint">' + errs.slice(0, 6).map(function (e) {
      return "<b>" + esc(dt(e.at, true)) + "</b> · " + esc(e.context || "") + (e.pair ? " · " + esc(e.pair) : "") + "<br>" + esc(e.error || "") + "<br>";
    }).join("") + "</div>" : '<div class="note ok"><div class="ico">✓</div><div><b>Tidak ada error tercatat</b><br>Log error kosong pada saat laporan dibuat.</div></div>';

    // costs
    var fees = meta.fees || {};
    var minOrder = meta.min_order_idr;
    var roundtrip = (fees.buy_pct || 0) + (fees.sell_pct || 0);
    $("feeCards").innerHTML = [
      { label: "Fee beli (taker)", value: pctPlain((fees.buy_pct || 0) * 100, 4), foot: "all-in, IDR Market PRO", cls: "warn" },
      { label: "Fee jual (taker)", value: pctPlain((fees.sell_pct || 0) * 100, 4), foot: "termasuk pajak + CFX", cls: "warn" },
      { label: "Minimum order", value: idr(minOrder), foot: "ketentuan Pro, bukan API " + idr(10000), cls: "" }
    ].map(function (k) {
      return '<div class="card kpi ' + k.cls + '"><div class="label">' + esc(k.label) + '</div><div class="value sm">' + k.value + '</div><div class="foot">' + esc(k.foot) + "</div></div>";
    }).join("");

    var costs = (bt.meta || {}).costs || {};
    var ckeys = Object.keys(costs);
    $("costTable").innerHTML = "<thead><tr><th>Pair</th><th>Sampel</th><th>Spread median</th><th>Half spread</th><th>Slip beli</th><th>Slip jual</th><th>Depth ok</th></tr></thead><tbody>" +
      (ckeys.length ? ckeys.map(function (p) {
        var c = costs[p] || {};
        return "<tr><td>" + esc(p) + '</td><td class="mono">' + num(c.samples, 0) +
          '</td><td class="mono">' + (isNum(c.spread_median) ? pctPlain(c.spread_median * 100, 4) : "—") +
          '</td><td class="mono">' + (isNum(c.half_spread) ? pctPlain(c.half_spread * 100, 4) : "—") +
          '</td><td class="mono">' + (isNum(c.slippage_buy) ? pctPlain(c.slippage_buy * 100, 4) : "—") +
          '</td><td class="mono">' + (isNum(c.slippage_sell) ? pctPlain(c.slippage_sell * 100, 4) : "—") +
          '</td><td class="mono">' + (isNum(c.depth_complete_share) ? pctPlain(c.depth_complete_share * 100, 0) : "—") + "</td></tr>";
      }).join("") : '<tr><td colspan="7" class="mut">Belum ada snapshot.</td></tr>') + "</tbody>";
    $("costMethod").textContent = (bt.meta || {}).cost_method || "";

    var src = (fees.sources || []);
    $("feeSources").innerHTML = [
      statline("Buy taker dipakai", pctPlain((fees.buy_pct || 0) * 100, 4)),
      statline("Sell taker dipakai", pctPlain((fees.sell_pct || 0) * 100, 4)),
      statline("Round-trip fee", pctPlain(roundtrip * 100, 4)),
      statline("Basis", esc(fees.basis || "—")),
      statline("API /api/pairs", pctPlain((fees.api_pairs_taker_pct || 0) * 100, 3) + " (tanpa pajak/CFX)"),
      '<div class="hint" style="margin-top:10px">' + src.map(function (s) {
        return '• <a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.url) + "</a><br><span class=\"mut\">" + esc(s.value) + " · diakses " + esc(s.accessed_at) + "</span>";
      }).join("<br><br>") + "</div>",
      '<div class="hint" style="margin-top:10px">Bukti tabel biaya: <code>docs/evidence/indodax_fee_table_2026-11-08.png</code>. Minimum order memakai ketentuan lebih ketat (Rp25.000).</div>'
    ].join("");

    var snap = fwd.snapshots || {};
    $("snapshotInfo").innerHTML = [
      statline("Snapshot tersimpan", num(snap.count, 0) + " baris"),
      statline("Snapshot dipakai backtest", num((D.costs_used || 0), 0) + " baris"),
      statline("Snapshot terakhir", esc(snap.last ? dt(snap.last.at_utc, true) + " · " + snap.last.pair : "belum")),
      statline("Spread terakhir", snap.last && isNum(snap.last.spread_pct) ? pctPlain(snap.last.spread_pct * 100, 4) : "—"),
      statline("Notional target", idr((snap.last || {}).target_notional_idr)),
      '<p class="hint" style="margin-top:10px">File mentah: <code>data/snapshots/orderbook_YYYYMMDD.jsonl</code>. Satu baris = satu pair pada satu waktu, memuat 20 level bid/ask.</p>'
    ].join("");

    $("costTotals").innerHTML = [
      statline("Fee", idr(m.fee_idr)),
      statline("Spread", idr(m.spread_cost_idr)),
      statline("Slippage", idr(m.slippage_cost_idr)),
      statline("Total", idr(m.total_cost_idr)),
      statline("Gross profit", idr(m.gross_profit_idr)),
      statline("Biaya / gross profit", pctPlain(m.cost_share_of_gross_profit * 100)),
      '<p class="hint" style="margin-top:10px">Biaya dihitung per trade: fee taker pada notional fill, spread = selisih harga referensi mid ke best bid/ask, slippage = selisih best level ke VWAP hasil walk-the-book.</p>'
    ].join("");

    // audit
    var q = (bt.meta || {}).data_quality || {};
    var qk = Object.keys(q);
    $("qualityTable").innerHTML = "<thead><tr><th>Pair</th><th>Bar</th><th>Gap</th><th>Bar buruk</th><th>Mulai</th><th>Selesai</th><th>SHA256</th></tr></thead><tbody>" +
      (qk.length ? qk.map(function (p) {
        var v = q[p] || {};
        return "<tr><td>" + esc(p) + '</td><td class="mono">' + num(v.bars, 0) + '</td><td class="mono">' + num(v.gaps, 0) +
          '</td><td class="mono">' + num(v.bad_bars, 0) + "</td><td>" + esc(v.first || "—") + "</td><td>" + esc(v.last || "—") +
          '</td><td class="mono small">' + esc((v.sha256 || "").slice(0, 12)) + "…</td></tr>";
      }).join("") : '<tr><td colspan="7" class="mut">Belum ada data.</td></tr>') + "</tbody>";

    var bmeta = bt.meta || {};
    $("reproInfo").innerHTML = '<dl class="kv">' + [
      kv("Dibuat", esc(dt(bmeta.generated_at, true))),
      kv("Kode (sha256)", esc(bmeta.code_sha256 || "—")),
      kv("Python", esc(bmeta.python || "—")),
      kv("Runtime backtest", num(bmeta.runtime_seconds, 1) + " detik"),
      kv("Periode", esc(bmeta.period_start ? dt(bmeta.period_start) : "—") + " → " + esc(bmeta.period_end ? dt(bmeta.period_end) : "—")),
      kv("Tahun", num(bmeta.years, 2)),
      kv("Timeframe", esc(bmeta.timeframe || "—") + " menit"),
      kv("Universe", esc((bmeta.universe || []).join(", "))),
      kv("Parameter", esc(JSON.stringify(bmeta.params || {}))),
      kv("Sumber data", esc(bmeta.data_source || "—"))
    ].join("") + "</dl>";

    var deadline = new Date("2026-11-04T12:00:00+07:00");
    var fdate = freeze ? new Date(freeze) : null;
    var lateDays = fdate ? Math.max(0, (fdate.getTime() - deadline.getTime()) / 86400000) : null;
    $("freezeInfo").innerHTML = [
      statline("Deadline tugas", esc(dt(deadline.toISOString(), true))),
      statline("Freeze aktual", freeze ? esc(dt(freeze, true)) : '<span class="neg">belum</span>'),
      statline("Status", freeze ? (freezeLate ? '<span class="warn">TERLAMBAT ' + num(lateDays, 2) + " hari</span>" : '<span class="pos">tepat waktu</span>') : "—"),
      statline("Commit", esc(meta.freeze_commit || "lihat docs/FREEZE.md")),
      '<p class="hint" style="margin-top:10px">Tidak ada commit yang di-backdate. Freeze dibuat setelah kode dan test selesai; konsekuensi keterlambatan ditulis di laporan.</p>'
    ].join("");

    $("commands").textContent = [
      "# 1. Unduh ulang data historis (butuh internet)",
      "python3 scripts/download_history.py --pairs btcidr,dogeidr,ethidr,xrpidr,bnbidr,trxidr --tf 240 --years 4",
      "",
      "# 2. Pilih universe dari likuiditas awal periode",
      "python3 scripts/select_universe.py",
      "",
      "# 3. Kalibrasi spread & slippage dari snapshot order book",
      "python3 scripts/calibrate_costs.py",
      "",
      "# 4. Backtest final (parameter sudah dipilih dari in-sample)",
      "python3 scripts/backtest.py --final",
      "",
      "# 5. Hitung ulang metrik dari log mentah dan bandingkan",
      "python3 scripts/recompute.py --source local",
      "",
      "# 6. Jalankan satu tick live dry-run",
      "python3 scripts/run_tick.py",
      "",
      "# 7. Bangun dashboard offline (HTML mandiri)",
      "python3 scripts/build_offline_dashboard.py"
    ].join("\n");

    // checklist
    var chk = [
      ["3–10 pair likuid IDR", true, (meta.universe || []).length + " pair, dipilih dari likuiditas awal periode"],
      ["Long-only, tanpa leverage", true, "Tidak ada short/margin di kode strategi"],
      ["Tanpa API key, API publik", true, "/api/pairs, /api/depth, history_v2"],
      ["Timeframe 4 jam", true, "240 menit, candle tertutup saja"],
      ["Backtest ≥ 3 tahun", (bmeta.years || 0) >= 3, num(bmeta.years, 2) + " tahun"],
      ["Fee + spread + slippage", true, "Fee resmi; spread/slippage dari snapshot"],
      ["Eksekusi dry-run di bid/ask", true, "Walk the book; order simulasi, bukan API privat"],
      ["Scheduler", !!(ps.github_actions_enabled), ps.github_actions_enabled ? "GitHub Actions tiap 4 jam; commit memicu redeploy Vercel" : "kode siap; workflow belum pernah sukses"],
      ["Penyimpanan persisten", true, "Commit repo (data/local/*.jsonl) untuk jadwal; Upstash Redis opsional untuk endpoint /api/tick"],
      ["Log keputusan & order", true, "JSONL/Redis list, mentah dan bisa diekspor"],
      ["Manajemen risiko", true, "Max 5 posisi, 20% equity, daily loss -3%, kill switch"],
      ["Deploy Vercel", !!(ps.vercel_deployed), ps.vercel_deployed ? esc(ps.vercel_url || "live") : "belum; langkah ada di docs/DEPLOYMENT.md"],
      ["Dashboard HTML offline", true, "public/offline_dashboard.html"],
      ["Skrip hitung ulang", true, "scripts/recompute.py"],
      [".env.example tanpa secret", true, ".env di-.gitignore"],
      ["Freeze sebelum deadline", !!freeze && !freezeLate, freeze ? (freezeLate ? "terlambat " + num(lateDays, 2) + " hari" : "tepat") : "belum"],
      ["Forward test 10 hari", fwdDays >= 10, num(fwdDays, 2) + " hari aktual"],
      ["Tidak ada data/log fiktif", true, "Prinsip proses; log mentah tersedia untuk diaudit ulang, bukan klaim otomatis"]
    ];
    $("checklist").innerHTML = chk.map(function (c) {
      var icon = c[1] ? '<span class="pos">✓</span>' : '<span class="neg">✗</span>';
      return '<div class="statline"><span>' + icon + " " + esc(c[0]) + "</span><span class=\"small " + (c[1] ? "mut" : "neg") + "\">" + c[2] + "</span></div>";
    }).join("");

    $("filesInfo").innerHTML = '<dl class="kv">' + [
      kv("Soal UAS", "<code>docs/Soal_UAS_Algoritma_Trading_Bot_Dry_Run_Indodax.pdf</code>"),
      kv("README", "<code>README.md</code>"),
      kv("Freeze", "<code>docs/FREEZE.md</code>"),
      kv("Laporan akhir", "<code>docs/LAPORAN_AKHIR.md</code>"),
      kv("Deployment", "<code>docs/DEPLOYMENT.md</code>"),
      kv("Forward test", "<code>docs/FORWARD_TEST.md</code>"),
      kv("Refleksi", "<code>docs/REFLEKSI.md</code>"),
      kv("Pernyataan AI", "<code>docs/PERNYATAAN_AI.md</code>"),
      kv("Hasil backtest", "<code>data/backtest_results.json</code>"),
      kv("Trade CSV", "<code>data/backtest_trades.csv</code>"),
      kv("Log lokal", "<code>data/local/*.jsonl</code>"),
      kv("Snapshot order book", "<code>data/snapshots/*.jsonl</code>"),
      kv("Bukti fee", "<code>docs/evidence/indodax_fee_table_2026-11-08.png</code>"),
      kv("Kode strategi", "<code>core/strategy.py</code>"),
      kv("Kode bot", "<code>core/bot.py</code>"),
      kv("Backtest", "<code>core/backtest_engine.py</code>")
    ].join("") + "</dl>";

    $("methodNotes").innerHTML = [
      note("ok", "Tidak ada look-ahead", "Sinyal dihitung pada close candle t. Backtest mengeksekusi di open t+1; bot mengeksekusi setelah candle t benar-benar tertutup memakai bid/ask saat itu. Donchian memakai high <i>sebelum</i> bar yang dievaluasi."),
      note("warn", "Survivorship bias dikurangi, bukan dihilangkan", "Universe dipilih dari likuiditas 60 hari pertama periode backtest (2022), bukan dari pair yang masih ramai hari ini. Namun daftar kandidat berasal dari pair yang masih ada pada November 2026; pair yang sudah delisted tidak tersedia di API. Ini keterbatasan yang ditulis di laporan."),
      note("ok", "Biaya nyata, bukan asumsi", "Fee memakai tarif taker all-in resmi. Spread dan slippage diukur dari snapshot order book publik untuk notional 20% modal, lalu dimasukkan per trade."),
      note("warn", "Keterbatasan yang harus ditulis", "OOS negatif; " + (fwd.start ? "forward test baru " + num(fwdDays, 2) + " hari" : "forward test belum dimulai") + "; " + (freeze ? (freezeLate ? "freeze terlambat" : "freeze tepat waktu") : "freeze belum ditetapkan") + "; hasil backtest tidak menjamin masa depan; universe hanya 6 pair dan periode 4 tahun."),
      note("info", "Parameter tidak dioptimasi pada OOS", "Grid search hanya pada 70% awal. Pemilihan memakai plateau Calmar (rata-rata parameter + tetangga), bukan puncak tunggal. OOS dievaluasi sekali setelah parameter dibekukan.")
    ].join("");
  }

  // ---------- tabs ----------
  function setupTabs() {
    var btns = Array.prototype.slice.call(document.querySelectorAll(".tab-btn"));
    function activate(id, push) {
      btns.forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-tab") === id); });
      Array.prototype.slice.call(document.querySelectorAll("section.tab")).forEach(function (s) {
        s.classList.toggle("active", s.id === "tab-" + id);
      });
      if (push !== false) history.replaceState(null, "", "#" + id);
      // setTimeout, bukan requestAnimationFrame: rAF bisa ditahan saat tab
      // tidak terlihat, sehingga canvas tetap kosong setelah pindah tab.
      setTimeout(function () {
        charts.forEach(function (c) { if (c.canvas.isConnected && c.canvas.offsetParent !== null) drawChart(c); });
      }, 30);
    }
    btns.forEach(function (b) {
      b.addEventListener("click", function () { activate(b.getAttribute("data-tab")); });
    });
    var initial = (location.hash || "#ringkasan").slice(1);
    if (!document.getElementById("tab-" + initial)) initial = "ringkasan";
    activate(initial, false);
  }

  // ---------- boot ----------
  function boot() {
    setupTabs();
    var resizeTimer = null;
    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () {
        charts.forEach(function (c) { if (c.canvas.isConnected && c.canvas.offsetParent !== null) drawChart(c); });
      }, 120);
    });
    if (window.__DASHBOARD_DATA__) {
      D = window.__DASHBOARD_DATA__;
      render();
      return;
    }
    fetch("/api/dashboard", { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) { D = data; render(); })
      .catch(function (err) {
        $("heroChips").innerHTML = '<span class="chip"><span class="dot bad"></span>API tidak tersedia</span>';
        $("kpis").innerHTML = '<div class="card" style="grid-column:1/-1">' +
          note("bad", "Gagal memuat /api/dashboard", "Error: <code>" + esc(err.message) + "</code><br><br>Jika membuka file langsung dari disk, buka <code>public/offline_dashboard.html</code>. Jika di Vercel, pastikan Upstash Redis dan CRON_SECRET sudah diset.") + "</div>";
      });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
