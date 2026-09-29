const form = document.querySelector("#research-form");
const topicInput = document.querySelector("#topic");
const submitButton = form.querySelector("button[type='submit']");
const errorMessage = document.querySelector("#form-error");
const results = document.querySelector("#results");
const resultsTitle = document.querySelector("#results-title");
const reportContent = document.querySelector("#report-content");
const copyButton = document.querySelector("#copy-button");
const downloadButton = document.querySelector("#download-button");

const stepNames = ["search_and_read", "extract_claims", "analyze_claims", "synthesize_and_visualize"];
const stepLabels = {
  search_and_read: "Searching & Reading",
  extract_claims: "Extracting Claims",
  analyze_claims: "Analyzing Consensus",
  synthesize_and_visualize: "Synthesizing & Visualizing"
};

let latestReport = "";
let activeEventSource = null;

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderMarkdown(markdown) {
  let html = escapeHtml(markdown || "");
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  html = html.replace(/^[-*] (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>.*<\/li>\n?)+/g, (list) => `<ul>${list}</ul>`);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\[\[(.+?)\]\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer" class="source-cite">$1</a>');
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  html = html.split(/\n{2,}/).map((block) => {
    const trimmed = block.trim();
    if (!trimmed || /^<(h[1-3]|ul)/.test(trimmed)) return trimmed;
    return `<p>${trimmed.replaceAll("\n", "<br>")}</p>`;
  }).join("");
  return html;
}

function setPipeline(state, activeStep = "") {
  stepNames.forEach((name, index) => {
    const element = document.querySelector(`[data-step="${name}"]`);
    if (!element) return;
    element.classList.toggle("is-running", name === activeStep);
    element.classList.toggle("is-done", state >= index + 1);
    element.querySelector("b").textContent = state >= index + 1 ? "Done" : name === activeStep ? stepLabels[name] : "Waiting";
  });
}

function setLoading(isLoading) {
  submitButton.disabled = isLoading;
  submitButton.querySelector("span:first-child").textContent = isLoading ? "Investigating..." : "Run research";
  topicInput.disabled = isLoading;
  document.querySelectorAll(".suggestion").forEach((btn) => { btn.disabled = isLoading; });
}

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
}

function clearError() {
  errorMessage.hidden = true;
  errorMessage.textContent = "";
}

function renderVisuals(visuals) {
  const agreementCard = document.querySelector("#agreement-chart-card");
  const credibilityCard = document.querySelector("#credibility-chart-card");
  const conflictCard = document.querySelector("#conflict-map-card");

  // 1. Plotly Agreement Chart
  if (visuals && visuals.agreement_chart && window.Plotly) {
    agreementCard.hidden = false;
    Plotly.newPlot("agreement-chart", visuals.agreement_chart.data, visuals.agreement_chart.layout, { responsive: true, displayModeBar: false });
  } else {
    agreementCard.hidden = true;
  }

  // 2. Plotly Credibility Chart
  if (visuals && visuals.credibility_chart && window.Plotly) {
    credibilityCard.hidden = false;
    Plotly.newPlot("credibility-chart", visuals.credibility_chart.data, visuals.credibility_chart.layout, { responsive: true, displayModeBar: false });
  } else {
    credibilityCard.hidden = true;
  }

  // 3. Mermaid Conflict Map (Hide if no data / None)
  if (visuals && visuals.conflict_map && window.mermaid) {
    conflictCard.hidden = false;
    const mermaidBox = document.querySelector("#conflict-map-mermaid");
    mermaidBox.removeAttribute("data-processed");
    mermaidBox.textContent = visuals.conflict_map;
    try {
      mermaid.run({ nodes: [mermaidBox] });
    } catch (e) {
      console.warn("Mermaid render error:", e);
    }
  } else {
    conflictCard.hidden = true;
  }
}

function renderSources(sources) {
  const sourcesList = document.querySelector("#sources-list");
  sourcesList.innerHTML = "";

  (sources || []).forEach((s) => {
    const li = document.createElement("li");
    li.className = "source-item";
    li.id = `source-${s.source_id}`;

    let badgeClass = "cred-med";
    if (s.credibility >= 0.75) badgeClass = "cred-high";
    else if (s.credibility < 0.50) badgeClass = "cred-low";

    li.innerHTML = `
      <div>
        <strong style="color:var(--orange)">[${escapeHtml(s.source_id)}]</strong>
        <a href="${escapeHtml(s.url)}" target="_blank" rel="noreferrer">${escapeHtml(s.source_name)}</a>
        ${s.is_snippet_fallback ? '<small style="color:#ff8d83;margin-left:6px">(Snippet fallback)</small>' : ''}
      </div>
      <div class="source-meta">
        <span>${escapeHtml(s.published || "Unknown date")}</span>
        <span class="cred-badge ${badgeClass}">Score: ${s.credibility.toFixed(2)}</span>
      </div>
    `;
    sourcesList.appendChild(li);
  });
}

function renderAudit(claims) {
  const auditList = document.querySelector("#audit-list");
  auditList.innerHTML = "";

  if (!claims || claims.length === 0) {
    auditList.innerHTML = "<p style='color:var(--muted);padding:10px'>No verified claims recorded.</p>";
    return;
  }

  claims.forEach((c) => {
    const div = document.createElement("div");
    div.className = "audit-item";
    div.innerHTML = `
      <div><strong>[${escapeHtml(c.source_id)}] ${escapeHtml(c.text)}</strong></div>
      <div class="audit-quote">&ldquo;${escapeHtml(c.quote)}&rdquo;</div>
      <div style="margin-top:4px;font-size:0.7rem;color:var(--dim)">Source: ${escapeHtml(c.source_name)} · Credibility: ${c.credibility.toFixed(2)} · Status: <span style="color:var(--green)">${escapeHtml(c.status)}</span></div>
    `;
    auditList.appendChild(div);
  });
}

function runResearch(topic) {
  clearError();
  results.hidden = true;
  setLoading(true);
  setPipeline(0, "");

  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }

  const streamUrl = `/api/research/stream?topic=${encodeURIComponent(topic)}`;
  const es = new EventSource(streamUrl);
  activeEventSource = es;

  let completedCount = 0;

  es.addEventListener("step", (event) => {
    try {
      const data = JSON.parse(event.data);
      const stageIndex = stepNames.indexOf(data.stage);
      if (stageIndex !== -1) {
        if (data.status === "running") {
          setPipeline(completedCount, data.stage);
        } else if (data.status === "done") {
          completedCount = Math.max(completedCount, stageIndex + 1);
          setPipeline(completedCount, "");
        }
      }
    } catch (err) {
      console.error("Failed to parse step event:", err);
    }
  });

  es.addEventListener("result", (event) => {
    es.close();
    activeEventSource = null;
    try {
      const data = JSON.parse(event.data);
      latestReport = data.report_markdown || data.report || "";
      resultsTitle.textContent = data.topic;
      reportContent.innerHTML = renderMarkdown(latestReport);

      renderVisuals(data.visuals);
      renderSources(data.sources);
      renderAudit(data.claims);

      results.hidden = false;
      setPipeline(stepNames.length, "");
      results.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      showError("Failed to display research results.");
    } finally {
      setLoading(false);
    }
  });

  es.addEventListener("error", (event) => {
    es.close();
    activeEventSource = null;
    setLoading(false);

    let errorMsg = "The research run failed.";
    if (event.data) {
      try {
        const parsed = JSON.parse(event.data);
        if (parsed.error) errorMsg = parsed.error;
      } catch {}
    } else {
      errorMsg = "Connection lost — the research run may have failed.";
    }

    showError(errorMsg);
    setPipeline(0, "");
  });
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const topic = topicInput.value.trim();
  if (!topic) {
    showError("Enter a research topic first.");
    topicInput.focus();
    return;
  }
  if (topic.length > 300) {
    showError("Topic cannot exceed 300 characters.");
    topicInput.focus();
    return;
  }
  runResearch(topic);
});

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    topicInput.value = button.dataset.topic;
    topicInput.focus();
  });
});

copyButton.addEventListener("click", async () => {
  if (!latestReport) return;
  await navigator.clipboard.writeText(latestReport);
  copyButton.textContent = "Copied";
  window.setTimeout(() => { copyButton.textContent = "Copy report"; }, 1400);
});

downloadButton.addEventListener("click", () => {
  if (!latestReport) return;
  const blob = new Blob([latestReport], { type: "text/markdown" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `evidence-report-${Date.now()}.md`;
  link.click();
  URL.revokeObjectURL(link.href);
});
