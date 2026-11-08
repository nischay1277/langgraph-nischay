/* No third-party scripts. Corpus and model output are always rendered as text. */
const $ = (id) => document.getElementById(id);
let config,
  currentRun,
  currentEval,
  busy = false,
  toastTimer;
const labels = {
  console: "Incident console",
  corpus: "Runbook library",
  evaluation: "Evaluation lab",
  history: "Run history",
};
function el(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  const n = $("toast");
  n.textContent = message;
  n.className = error ? "error" : "";
  n.hidden = false;
  toastTimer = setTimeout(() => (n.hidden = true), error ? 14000 : 6000);
}
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.method && options.method !== "GET")
    headers["x-workspace-token"] = config?.token || "";
  const response = await fetch("/api/" + path, { ...options, headers });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Request failed. Check the selected scope and inputs.",
    );
  return data;
}
function page(name) {
  document
    .querySelectorAll(".page")
    .forEach((n) => n.classList.toggle("active", n.id === "page-" + name));
  document
    .querySelectorAll(".nav-item")
    .forEach((n) => n.classList.toggle("active", n.dataset.page === name));
  $("page-label").textContent = labels[name];
  if (name === "history") history();
  window.scrollTo({ top: 0, behavior: "instant" });
}
document
  .querySelectorAll("[data-page]")
  .forEach((n) => n.addEventListener("click", () => page(n.dataset.page)));
function options(node, values, selected) {
  node.replaceChildren();
  for (const v of values) {
    const o = el("option", "", v);
    o.value = v;
    node.append(o);
  }
  if (values.includes(selected)) node.value = selected;
}
function versions(preferred) {
  const values = [
    ...new Set(
      config.documents
        .filter((d) => d.service === $("service").value)
        .map((d) => d.version),
    ),
  ].sort();
  options($("version"), values, preferred || $("version").value);
}
function scope(service, version) {
  if ([...$("service").options].some((o) => o.value === service)) {
    $("service").value = service;
    versions(version);
  }
}
function refreshDocuments(docs) {
  config.documents = docs;
  const services = [...new Set(docs.map((d) => d.service))].sort();
  options($("service"), services, $("service").value || "atlas-api");
  versions($("version").value || "2.4");
  $("doc-count").textContent = String(docs.length).padStart(2, "0");
  $("library-count").textContent = docs.length + " DOCUMENTS";
  $("document-list").replaceChildren();
  if (!docs.length)
    $("document-list").append(
      el(
        "p",
        "field-hint",
        "Your library is empty. Add a runbook or load the synthetic demo.",
      ),
    );
  for (const d of docs) {
    const card = el("article", "card document-card");
    card.append(el("div", "doc-icon", "▤"), el("div", "doc-title", d.title));
    const meta = el("div", "doc-meta");
    meta.append(
      el("span", "badge neutral", d.service),
      el("span", "badge neutral", "v" + d.version),
    );
    card.append(meta);
    card.append(
      el(
        "p",
        "doc-alias",
        d.aliases
          ? "Search aliases: " + d.aliases
          : "No search aliases supplied.",
      ),
      el(
        "span",
        "mono",
        d.chunks + " CHUNKS · " + d.characters.toLocaleString() + " CHARACTERS",
      ),
    );
    const del = el("button", "delete-doc", "×");
    del.type = "button";
    del.setAttribute("aria-label", "Remove " + d.title);
    del.addEventListener("click", async () => {
      if (
        !window.confirm(
          "Remove this runbook from the local index? Saved runs retain their evidence snapshots.",
        )
      )
        return;
      try {
        await api("documents/" + d.id, { method: "DELETE" });
        refreshDocuments(await api("documents"));
        toast("Runbook removed from the index.");
      } catch (e) {
        toast(e.message, true);
      }
    });
    card.append(del);
    $("document-list").append(card);
  }
}
$("service").addEventListener("change", () => versions());
$("provider").addEventListener("change", () => {
  $("provider-hint").textContent =
    $("provider").value === "openai"
      ? "This sends your question and retrieved runbook passages to OpenAI. Credentials stay on the server."
      : $("provider").value === "ollama"
        ? "Evidence selection uses your configured local Ollama model. No external endpoint is used."
        : "Local mode returns verbatim excerpts. No LLM or external request.";
});
const examples = {
  deploy: {
    service: "atlas-api",
    version: "2.4",
    question: "How do I revert a bad deploy?",
  },
  pool: {
    service: "atlas-api",
    version: "2.4",
    question: "How do I investigate conection pool exhuastion?",
  },
  queue: {
    service: "ledger-worker",
    version: "3.1",
    question: "Why are events arriving twice?",
  },
};
document.querySelectorAll("[data-example]").forEach((n) =>
  n.addEventListener("click", () => {
    const e = examples[n.dataset.example];
    scope(e.service, e.version);
    $("question").value = e.question;
    $("question").focus();
  }),
);
function setBusy(value) {
  busy = value;
  for (const id of ["run-button", "evaluate-button", "seed-button"])
    $(id).disabled = value;
  $("run-button").classList.toggle("loading", value);
}
function download(data, name) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const a = el("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("export-run").addEventListener(
  "click",
  () =>
    currentRun && download(currentRun, "atlas-run-" + currentRun.id + ".json"),
);
$("export-eval").addEventListener(
  "click",
  () =>
    currentEval &&
    download(currentEval, "atlas-evaluation-" + currentEval.id + ".json"),
);
function renderRun(run) {
  currentRun = run;
  $("result-empty").hidden = true;
  $("result-content").hidden = false;
  const abstain = run.status === "abstained";
  $("result-status").textContent = abstain ? "Abstained" : "Sources cited";
  $("result-status").className = "badge " + (abstain ? "warning" : "success");
  $("result-reason").textContent = run.reason;
  $("run-stats").replaceChildren();
  for (const [value, label] of [
    [run.attempts, "Retrieval attempts"],
    [run.latency_ms.toFixed(1) + " ms", "Elapsed"],
    [run.model_calls, "Model calls"],
  ]) {
    const n = el("div");
    n.append(el("strong", "", value), el("span", "", label));
    $("run-stats").append(n);
  }
  $("claims").replaceChildren();
  run.claims.forEach((claim, i) => {
    const source = run.evidence.find((c) => c.id === claim.chunk_id);
    const card = el("article", "claim");
    const title = el("div", "claim-title");
    title.append(
      el("span", "claim-num", String(i + 1).padStart(2, "0")),
      el("span", "", source?.title || "Source unavailable"),
    );
    card.append(title, el("blockquote", "", claim.quote));
    const detail = el("details");
    detail.append(
      el(
        "summary",
        "",
        `${source.service} / v${source.version} · exact quote verified · inspect passage`,
      ),
      el("pre", "", source.text),
      el("div", "mono", "CHUNK " + source.id),
    );
    if (source.alias_matches.length)
      detail.append(
        el(
          "p",
          "",
          "Metadata alias matches: " + source.alias_matches.join(", "),
        ),
      );
    card.append(detail);
    $("claims").append(card);
  });
  $("evidence-footer").textContent = abstain
    ? "No proposed answer was published. Try a more specific symptom or add a runbook for the selected version."
    : "Quotes are checked against the retrieved passages. Their relevance and the operational safety of a proposed action still require human review. No commands were executed.";
  $("trace").replaceChildren();
  $("trace-label").textContent = run.service + " / v" + run.version;
  for (const step of run.trace) {
    const n = el("div", "trace-item");
    n.dataset.stage = step.stage;
    const title = el("div", "trace-title");
    title.append(
      el(
        "span",
        "",
        step.stage + " / " + String(step.attempt).padStart(2, "0"),
      ),
      el("time", "", step.elapsed_ms.toFixed(1) + " ms"),
    );
    n.append(title, el("p", "", step.message));
    const { stage, message, elapsed_ms, attempt, ...details } = step;
    if (Object.keys(details).length) {
      const d = el("details");
      d.append(
        el("summary", "", "Inspect decision data"),
        el("pre", "", JSON.stringify(details, null, 2)),
      );
      n.append(d);
    }
    $("trace").append(n);
  }
}
$("query-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  if (!$("service").value || !$("version").value) {
    toast("Add runbooks or load the demo before investigating.", true);
    return;
  }
  setBusy(true);
  $("result-status").textContent = "Investigating…";
  $("result-status").className = "badge warning";
  $("result-content").hidden = true;
  $("result-empty").hidden = false;
  try {
    const result = await api("run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: $("question").value,
        service: $("service").value,
        version: $("version").value,
        provider: $("provider").value,
        recovery: $("recovery").checked,
        max_attempts: Number($("attempts").value),
      }),
    });
    renderRun(result);
    toast("Investigation saved. Inspect the evidence and execution trail.");
  } catch (e) {
    $("result-status").textContent = "Run failed";
    $("result-status").className = "badge warning";
    toast(e.message, true);
  } finally {
    setBusy(false);
  }
});
$("seed-button").addEventListener("click", async () => {
  try {
    await api("demo", { method: "POST" });
    refreshDocuments(await api("documents"));
    toast("Demo runbooks loaded. Existing identical documents were preserved.");
  } catch (e) {
    toast(e.message, true);
  }
});
$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.target.querySelector("button[type=submit]");
  button.disabled = true;
  const data = new FormData();
  data.append("file", $("upload-file").files[0]);
  data.append("service", $("upload-service").value);
  data.append("version", $("upload-version").value);
  data.append("aliases", $("upload-aliases").value);
  try {
    const r = await api("documents", { method: "POST", body: data });
    refreshDocuments(await api("documents"));
    toast(
      r.duplicate
        ? "This content is already indexed for the same service and version."
        : "Runbook indexed and ready for retrieval.",
    );
    event.target.reset();
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.disabled = false;
  }
});
const pct = (n) => (n * 100).toFixed(1) + "%";
function renderEval(data) {
  currentEval = data;
  $("eval-empty").hidden = true;
  $("eval-results").hidden = false;
  $("metric-grid").replaceChildren();
  const metrics = [
    [
      "Source recall",
      "source_recall",
      "Expected source documents found in final retrieval. Candidate limit: 3 baseline, up to 5 recovery.",
    ],
    [
      "Expected source cited",
      "cited_source_hit_rate",
      "Answerable cases with all expected documents cited. This is not answer accuracy.",
    ],
    [
      "Unknowns abstained",
      "unanswerable_abstention_rate",
      "Unanswerable fixtures for which no answer was published.",
    ],
  ];
  for (const [label, key, hint] of metrics) {
    const n = el("div", "card metric");
    const values = el("div", "metric-values");
    values.append(
      el("strong", "old", pct(data.summary.baseline[key])),
      el("span", "", "→"),
      el("strong", "new", pct(data.summary.recovery[key])),
    );
    n.append(
      el("div", "metric-label", label.toUpperCase()),
      values,
      el("p", "metric-foot", "BASELINE → RECOVERY. " + hint),
    );
    $("metric-grid").append(n);
  }
  $("eval-cases").replaceChildren();
  for (const item of data.cases) {
    const tr = el("tr");
    const question = el("td", "", item.question);
    question.append(
      el(
        "span",
        "mono",
        item.id + (item.answerable ? " · ANSWERABLE" : " · UNANSWERABLE"),
      ),
    );
    tr.append(question, el("td", "", item.service + " / " + item.version));
    for (const name of ["baseline", "recovery"]) {
      const r = item[name],
        pass = r.outcome_correct && (!item.answerable || r.cited_source_hit);
      const cell = el("td");
      cell.append(
        el(
          "span",
          "badge " + (pass ? "success" : "warning"),
          pass ? "PASS" : r.abstained ? "ABSTAINED" : "SOURCE MISS",
        ),
        el(
          "span",
          "mono",
          r.attempts + " attempts · " + r.latency_ms.toFixed(1) + " ms",
        ),
      );
      tr.append(cell);
    }
    const inspect = el("td");
    for (const [name, label] of [
      ["baseline", "Baseline ↗"],
      ["recovery", "Recovery ↗"],
    ]) {
      const b = el("button", "text-button", label);
      b.addEventListener("click", () => {
        page("console");
        scope(item.service, item.version);
        $("question").value = item.question;
        renderRun(item[name].run);
      });
      inspect.append(b, el("br"));
    }
    tr.append(inspect);
    $("eval-cases").append(tr);
  }
}
$("evaluate-button").addEventListener("click", async () => {
  if (busy) return;
  setBusy(true);
  const old = $("evaluate-button").textContent;
  $("evaluate-button").textContent = "Comparing both paths…";
  try {
    renderEval(await api("evaluate", { method: "POST" }));
    toast("Comparison complete. All case results and traces are available.");
  } catch (e) {
    toast(e.message, true);
  } finally {
    setBusy(false);
    $("evaluate-button").textContent = old;
  }
});
async function history() {
  try {
    const rows = await api("runs");
    $("history-rows").replaceChildren();
    if (!rows.length) {
      const td = el(
        "td",
        "empty-table",
        "No saved runs yet. Start an investigation in the console.",
      );
      td.colSpan = 5;
      const tr = el("tr");
      tr.append(td);
      $("history-rows").append(tr);
    }
    for (const r of rows) {
      const tr = el("tr");
      tr.append(
        el("td", "history-question", r.question),
        el("td", "", r.service + " / " + r.version),
      );
      const outcome = el("td");
      outcome.append(
        el(
          "span",
          "badge " + (r.status === "abstained" ? "warning" : "success"),
          r.status === "abstained" ? "Abstained" : "Evidence",
        ),
        el("span", "mono", r.recovery ? "Recovery enabled" : "Baseline"),
      );
      tr.append(outcome, el("td", "", new Date(r.created_at).toLocaleString()));
      const action = el("td"),
        b = el("button", "text-button", "Open run ↗");
      b.addEventListener("click", async () => {
        try {
          const run = await api("runs/" + r.id);
          page("console");
          scope(run.service, run.version);
          $("question").value = run.question;
          renderRun(run);
        } catch (e) {
          toast(e.message, true);
        }
      });
      action.append(b);
      tr.append(action);
      $("history-rows").append(tr);
    }
  } catch (e) {
    toast(e.message, true);
  }
}
$("refresh-history").addEventListener("click", history);
async function init() {
  try {
    config = await api("config");
    refreshDocuments(config.documents);
    $("provider").replaceChildren();
    for (const [key, p] of Object.entries(config.providers)) {
      const o = el(
        "option",
        "",
        p.label + (p.ready ? "" : " · not configured"),
      );
      o.value = key;
      o.disabled = !p.ready;
      $("provider").append(o);
    }
    $("connection-text").textContent = "Local workspace";
    const past = await api("evaluations");
    if (past.length) renderEval(past[0]);
  } catch (e) {
    $("connection-text").textContent = "Connection failed";
    toast("Could not load the workspace. " + e.message, true);
  }
}
init();
