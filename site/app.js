/* kxsurv results viewer.
 *
 * Read-only by construction. The page has no write path: it cannot start a
 * run, reach Kalshi, or record a disposition. It renders one exported run
 * document and nothing else.
 *
 * Key names here are pinned by tests/test_export.py; renaming a field without
 * updating that contract test is a test failure rather than a blank page.
 */
"use strict";

var ACTIONS = ["no_action", "monitor", "escalated", "untriaged"];
var ACTION_LABEL = {
  no_action: "No action", monitor: "Monitor",
  escalated: "Escalated", untriaged: "Untriaged"
};

function el(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}

function num(v) {
  return typeof v === "number" ? v.toLocaleString("en-US") : String(v);
}

function score(v) {
  if (typeof v !== "number") return String(v);
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  var rounded = Number(v.toFixed(Math.abs(v) < 1 ? 4 : 2));
  return String(rounded);
}

function isEpoch(v) {
  var n = Number(v);
  return Number.isFinite(n) && n > 1e9 && n < 4e9 && String(v).indexOf(".") === -1;
}

function asTime(v) {
  return new Date(Number(v) * 1000).toISOString().replace("T", " ").replace(".000Z", "");
}

function stamp(iso) {
  if (!iso) return "—";
  return String(iso).slice(0, 19).replace("T", " ") + " UTC";
}

function shortHash(h) {
  return h ? String(h).slice(0, 16) + "…" : "—";
}

function fail(message) {
  var box = document.getElementById("error");
  box.textContent = message;
  box.hidden = false;
  document.getElementById("main").hidden = true;
}

/* ---------- provenance ---------- */

function renderProvenance(doc) {
  var run = doc.run;
  document.getElementById("run-id").textContent = "Run " + run.run_id;
  document.getElementById("run-status").textContent =
    run.status + " · " + run.controls_complete + "/" + run.controls_expected + " controls";
  document.getElementById("run-params").textContent =
    "parameters v" + (run.params_version || "unregistered");

  var rows = [
    ["Parameters SHA-256", run.params_hash],
    ["Input fingerprint", run.input_hash],
    ["Code fingerprint", run.code_hash],
    ["Source commit", run.source_commit || "—"],
    ["Started", stamp(run.started_at)],
    ["Finished", stamp(run.finished_at)]
  ];
  var grid = document.getElementById("prov-grid");
  rows.forEach(function (row) {
    var wrap = el("div", "prov-item");
    wrap.appendChild(el("dt", null, row[0]));
    var dd = el("dd", null, row[1] && row[1].length === 64 ? shortHash(row[1]) : row[1]);
    if (row[1] && row[1].length === 64) dd.title = row[1];
    wrap.appendChild(dd);
    grid.appendChild(wrap);
  });

  // Publishing a result under a code fingerprint the tree no longer matches
  // would misdescribe what produced it. Say so on the page, not only in a log.
  var warnings = document.getElementById("warnings");
  if (run.code_drift) {
    warnings.appendChild(el("div", "warn",
      "The working tree that produced this export no longer matches the code " +
      "fingerprint recorded for this run. The alerts below are the run's own; " +
      "the current checkout has since changed."));
  }
  if (run.source_dirty) {
    warnings.appendChild(el("div", "warn",
      "This export was produced from a working tree with uncommitted changes, " +
      "so the source commit above does not fully identify the code."));
  }
}

/* ---------- funnel ---------- */

function renderFunnel(doc) {
  var f = doc.funnel;
  var counts = {
    no_action: f.no_action, monitor: f.monitor,
    escalated: f.escalated, untriaged: f.untriaged
  };

  document.getElementById("funnel-total").innerHTML = "";
  var total = document.getElementById("funnel-total");
  total.appendChild(document.createTextNode(num(f.generated)));
  total.appendChild(el("small", null, " alerts generated · " + num(f.triaged) + " triaged"));

  // Only a completed review can support a claim about what the review found.
  // With nothing triaged, "none escalated" is an absence of judgement, not a
  // judgement of absence.
  var note = "";
  if (f.generated === 0) {
    note = "No candidates generated.";
  } else if (f.triaged === 0) {
    note = "awaiting analyst triage";
  } else if (f.triaged < f.generated) {
    note = f.untriaged + " still awaiting review";
  } else if (f.escalated === 0) {
    note = "All " + num(f.generated) + " candidates reviewed: " +
      num(f.no_action) + " closed, " + num(f.monitor) +
      " retained for monitoring, none escalated.";
  }
  document.getElementById("funnel-note").textContent = note;

  var bar = document.getElementById("funnel-bar");
  var legend = document.getElementById("funnel-legend");
  ACTIONS.forEach(function (action) {
    var n = counts[action] || 0;
    if (n > 0 && f.generated > 0) {
      var seg = el("i");
      seg.style.width = (100 * n / f.generated) + "%";
      seg.style.background = "var(--" + action.replace("_", "-") + ")";
      seg.title = ACTION_LABEL[action] + ": " + n;
      bar.appendChild(seg);
    }
    var item = el("div");
    item.appendChild(el("b", null, num(n)));
    var label = el("span");
    var sw = el("i", "swatch");
    sw.style.background = "var(--" + action.replace("_", "-") + ")";
    label.appendChild(sw);
    label.appendChild(document.createTextNode(ACTION_LABEL[action]));
    item.appendChild(label);
    legend.appendChild(item);
  });
}

/* ---------- by control ---------- */

function renderControls(doc) {
  var table = document.getElementById("control-table");
  var head = el("tr");
  ["Control", "Screen", "Core principle", "Generated", "No action", "Monitor", "Escalated"]
    .forEach(function (h, i) {
      var th = el("th", i >= 3 ? "num" : null, h);
      head.appendChild(th);
    });
  table.appendChild(el("thead")).appendChild(head);

  var body = el("tbody");
  doc.executions.forEach(function (ex) {
    var id = ex.control_id;
    var meta = doc.controls[id] || {};
    var row = (doc.funnel.by_control || {})[id] || {};
    var tr = el("tr");
    tr.appendChild(el("td", null, id));
    tr.appendChild(el("td", null, meta.name || "—"));
    tr.appendChild(el("td", null, (meta.core_principle || "—").split(" — ")[0]));
    [ex.alert_count, row.no_action || 0, row.monitor || 0, row.escalated || 0]
      .forEach(function (v, i) {
        tr.appendChild(el("td", "num", ex.alert_count === 0 && i > 0 ? "—" : num(v)));
      });
    body.appendChild(tr);
  });
  table.appendChild(body);
}

/* ---------- coverage ---------- */

var C1_REASONS = [
  ["no_result", "No settlement label"],
  ["low_volume", "Below volume floor"],
  ["null_too_small", "Null population too small"],
  ["release_time_unknown", "No source-coded publication time"],
  ["gate_blocked", "Gate blocked"]
];

function renderCoverage(doc) {
  var host = document.getElementById("coverage");
  var cov = doc.coverage || {};

  if (cov.C1) {
    var c1 = cov.C1;
    var card = el("div", "cov-card");
    card.appendChild(el("h3", null, "C1 — pre-release informed flow"));
    var big = el("div", "big", num(c1.scored));
    big.appendChild(el("small", null, " of " + num(c1.considered) + " markets scored"));
    card.appendChild(big);
    var list = el("ul");
    C1_REASONS.forEach(function (r) {
      if (!c1[r[0]]) return;
      var li = el("li");
      li.appendChild(document.createTextNode(r[1]));
      li.appendChild(el("b", null, num(c1[r[0]])));
      list.appendChild(li);
    });
    card.appendChild(list);
    card.appendChild(el("p", "cov-note",
      "An alert count is only interpretable against the population it was drawn " +
      "from. With small, discrete null populations a 95th-percentile result is " +
      "often simply the maximum rank."));
    host.appendChild(card);
  }

  if (cov.C3) {
    var c3 = cov.C3;
    var persisted = 0;
    doc.executions.forEach(function (e) { if (e.control_id === "C3") persisted = e.alert_count; });
    var card3 = el("div", "cov-card");
    card3.appendChild(el("h3", null, "C3 — volume / open-interest divergence"));
    var big3 = el("div", "big", num(c3.scoreable));
    big3.appendChild(el("small", null, " scoreable observations"));
    card3.appendChild(big3);
    var list3 = el("ul");
    [["Clear the percentile gate", c3.percentile_qualified],
     ["Survive persistence", persisted]].forEach(function (r) {
      var li = el("li");
      li.appendChild(document.createTextNode(r[0]));
      li.appendChild(el("b", null, num(r[1])));
      list3.appendChild(li);
    });
    card3.appendChild(list3);
    card3.appendChild(el("p", "cov-note",
      "C3 is deliberately non-specific. Flat open interest across volume-bearing " +
      "hours is a common benign signature, not evidence of wash trading."));
    host.appendChild(card3);
  }

  if (!host.children.length) {
    host.appendChild(el("p", "empty", "No coverage summary in this export."));
  }
}

/* ---------- alerts ---------- */

var state = { control: "all", action: "all", doc: null };

function alertAction(a) {
  return a.disposition ? a.disposition.action : "untriaged";
}

function renderAlertList() {
  var host = document.getElementById("alerts");
  host.innerHTML = "";
  var shown = state.doc.alerts.filter(function (a) {
    return (state.control === "all" || a.control_id === state.control) &&
           (state.action === "all" || alertAction(a) === state.action);
  });

  document.getElementById("alert-note").textContent =
    shown.length + " of " + state.doc.alerts.length + " shown";

  if (!shown.length) {
    host.appendChild(el("p", "empty", "No alerts match this filter."));
    return;
  }

  shown.forEach(function (a) {
    var action = alertAction(a);
    var d = el("details", "alert");
    d.setAttribute("data-action", action);

    var s = el("summary");
    s.appendChild(el("span", "cid", a.control_id));
    s.appendChild(el("span", "target", a.target));
    s.appendChild(el("span", "tag " + action, ACTION_LABEL[action]));
    var scoreText = "score " + score(a.score);
    if (a.percentile !== null && a.percentile !== undefined) {
      scoreText += " · pct " + score(a.percentile);
    }
    s.appendChild(el("span", "score", scoreText));
    d.appendChild(s);

    var body = el("div", "body");

    var r = el("div", "rationale");
    if (a.disposition) {
      var text = a.disposition.rationale.replace(
        /^(No action|Monitor|Escalated)\.\s*/i, "");
      r.appendChild(el("strong", null, ACTION_LABEL[action] + " — "));
      r.appendChild(document.createTextNode(text));
    } else {
      r.appendChild(el("em", null,
        "Untriaged. Dispositions are scoped to a run; a prior run's review is not inherited."));
    }
    body.appendChild(r);

    var kv = el("table", "kv");
    var tb = el("tbody");
    var meta = [["threshold", a.threshold], ["window_start", a.window_start],
                ["window_end", a.window_end]];
    meta.concat(Object.keys(a.evidence).sort().map(function (k) {
      return [k, a.evidence[k]];
    })).forEach(function (pair) {
      if (pair[1] === null || pair[1] === undefined) return;
      var tr = el("tr");
      tr.appendChild(el("td", null, pair[0]));
      var value;
      if (isEpoch(pair[1]) && /(_ts|window_start|window_end)$/.test(pair[0])) {
        value = asTime(pair[1]) + " UTC";
      } else if (typeof pair[1] === "number") {
        value = score(pair[1]);
      } else {
        value = String(pair[1]);
      }
      tr.appendChild(el("td", null, value));
      tb.appendChild(tr);
    });
    kv.appendChild(tb);
    body.appendChild(kv);

    d.appendChild(body);
    host.appendChild(d);
  });
}

function buildFilters(doc) {
  var controls = ["all"].concat(doc.executions.map(function (e) { return e.control_id; }));
  var host = document.getElementById("filter-control");
  controls.forEach(function (c) {
    var count = c === "all" ? doc.alerts.length
      : doc.alerts.filter(function (a) { return a.control_id === c; }).length;
    var b = el("button", null, (c === "all" ? "All controls" : c) + " (" + count + ")");
    b.setAttribute("aria-pressed", String(c === state.control));
    b.onclick = function () {
      state.control = c;
      Array.prototype.forEach.call(host.children, function (x) {
        x.setAttribute("aria-pressed", String(x === b));
      });
      renderAlertList();
    };
    host.appendChild(b);
  });

  var ahost = document.getElementById("filter-action");
  var present = ["all"].concat(ACTIONS.filter(function (act) {
    return doc.alerts.some(function (a) { return alertAction(a) === act; });
  }));
  if (present.length <= 2) return;          // only one disposition kind: no filter needed
  present.forEach(function (act) {
    var count = act === "all" ? doc.alerts.length
      : doc.alerts.filter(function (a) { return alertAction(a) === act; }).length;
    var b = el("button", null,
      (act === "all" ? "All dispositions" : ACTION_LABEL[act]) + " (" + count + ")");
    b.setAttribute("aria-pressed", String(act === state.action));
    b.onclick = function () {
      state.action = act;
      Array.prototype.forEach.call(ahost.children, function (x) {
        x.setAttribute("aria-pressed", String(x === b));
      });
      renderAlertList();
    };
    ahost.appendChild(b);
  });
}

/* ---------- boot ---------- */

function render(doc) {
  state.doc = doc;
  document.getElementById("disclaimer").innerHTML = "";
  var note = document.getElementById("disclaimer");
  note.appendChild(el("strong", null, "Methodology demonstration on public data. "));
  note.appendChild(document.createTextNode(doc.disclaimer.replace(
    "A methodology demonstration on public Kalshi market data. ", "")));

  renderProvenance(doc);
  renderFunnel(doc);
  renderControls(doc);
  renderCoverage(doc);
  buildFilters(doc);
  renderAlertList();

  var c = doc.corpus;
  document.getElementById("footer-provenance").textContent =
    "Corpus: " + num(c.markets) + " markets across " + c.series.length + " series (" +
    c.series.join(", ") + "), " + num(c.trades) + " trades, " + num(c.candles) +
    " candlestick periods, " + num(c.events) + " events. Exported " +
    doc.generated_at.slice(0, 19).replace("T", " ") + " UTC from a gitignored database; " +
    "this artifact carries derived results only.";

  document.getElementById("main").hidden = false;
}

function load() {
  fetch("data/index.json")
    .then(function (r) {
      if (!r.ok) throw new Error("index.json returned HTTP " + r.status);
      return r.json();
    })
    .then(function (index) {
      var name = new URLSearchParams(location.search).get("run");
      var file = name ? "run-" + name + ".json" : index.latest;
      if (!file) throw new Error("no published run listed in index.json");
      return fetch("data/" + file).then(function (r) {
        if (!r.ok) throw new Error(file + " returned HTTP " + r.status);
        return r.json();
      });
    })
    .then(render)
    .catch(function (e) {
      fail("Could not load the published results: " + e.message +
           ". If you are opening this file directly from disk, serve the " +
           "directory instead — for example: python3 -m http.server --directory site");
    });
}

load();
