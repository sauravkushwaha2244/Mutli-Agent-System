const form = document.querySelector("#research-form");
const topicInput = document.querySelector("#topic");
const submitButton = form.querySelector("button[type='submit']");
const errorMessage = document.querySelector("#form-error");
const results = document.querySelector("#results");
const resultsTitle = document.querySelector("#results-title");
const reportContent = document.querySelector("#report-content");
const copyButton = document.querySelector("#copy-button");
const downloadButton = document.querySelector("#download-button");
const cloudSavedBadge = document.querySelector("#cloud-saved-badge");

// History drawer elements
const historyToggleBtn = document.querySelector("#history-toggle-btn");
const closeHistoryBtn = document.querySelector("#close-history-btn");
const historyDrawer = document.querySelector("#history-drawer");
const drawerOverlay = document.querySelector("#drawer-overlay");
const historyItems = document.querySelector("#history-items");

// Auth and User Profile elements
const authBtn = document.querySelector("#auth-btn");
const userPill = document.querySelector("#user-pill");
const userEmailLabel = document.querySelector("#user-email-label");
const logoutBtn = document.querySelector("#logout-btn");
const supabasePill = document.querySelector("#supabase-pill");

const authModal = document.querySelector("#auth-modal");
const authForm = document.querySelector("#auth-form");
const authTitle = document.querySelector("#auth-title");
const closeAuthBtn = document.querySelector("#close-auth-btn");
const authEmailInput = document.querySelector("#auth-email");
const authPasswordInput = document.querySelector("#auth-password");
const authError = document.querySelector("#auth-error");
const authSuccess = document.querySelector("#auth-success");
const authSubmitBtn = document.querySelector("#auth-submit-btn");
const authSubmitLabel = document.querySelector("#auth-submit-label");
const authToggleModeBtn = document.querySelector("#auth-toggle-mode-btn");

let sbClient = null;
let currentUser = null;
let authMode = "signin"; // "signin" | "signup"

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

// ── Supabase Auth Helper Functions ──
function updateAuthModalMode(mode) {
  authMode = mode;
  clearAuthMessages();
  if (authMode === "signin") {
    if (authTitle) authTitle.textContent = "Sign In to ResearchMind";
    if (authSubmitLabel) authSubmitLabel.textContent = "Sign In";
    if (authToggleModeBtn) authToggleModeBtn.textContent = "Don't have an account? Sign up";
    if (authPasswordInput) authPasswordInput.autocomplete = "current-password";
  } else {
    if (authTitle) authTitle.textContent = "Create ResearchMind Account";
    if (authSubmitLabel) authSubmitLabel.textContent = "Create Account";
    if (authToggleModeBtn) authToggleModeBtn.textContent = "Already have an account? Sign in";
    if (authPasswordInput) authPasswordInput.autocomplete = "new-password";
  }
}

function openAuthModal(mode = "signin") {
  updateAuthModalMode(mode);
  if (authModal) authModal.hidden = false;
  if (authEmailInput) authEmailInput.focus();
}

function closeAuthModal() {
  if (authModal) authModal.hidden = true;
  clearAuthMessages();
  if (authForm) authForm.reset();
}

function showAuthError(msg) {
  if (authError) {
    authError.textContent = msg;
    authError.hidden = false;
  }
  if (authSuccess) authSuccess.hidden = true;
}

function showAuthSuccess(msg) {
  if (authSuccess) {
    authSuccess.textContent = msg;
    authSuccess.hidden = false;
  }
  if (authError) authError.hidden = true;
}

function clearAuthMessages() {
  if (authError) {
    authError.hidden = true;
    authError.textContent = "";
  }
  if (authSuccess) {
    authSuccess.hidden = true;
    authSuccess.textContent = "";
  }
}

function updateUserUI(user) {
  currentUser = user;
  if (user) {
    if (authBtn) authBtn.hidden = true;
    if (userPill) userPill.hidden = false;
    if (userEmailLabel) userEmailLabel.textContent = user.email || "Authenticated";
  } else {
    if (authBtn) authBtn.hidden = false;
    if (userPill) userPill.hidden = true;
    if (userEmailLabel) userEmailLabel.textContent = "";
  }
}

const FALLBACK_SUPABASE_URL = "https://tolggaarlarbcpjibehw.supabase.co";
const FALLBACK_SUPABASE_KEY = "sb_publishable_z_eNK3khqDvjafaY7KZC2Q_2sKqHKjz";

function getSupabaseSDK() {
  if (typeof window !== "undefined" && window.supabase && typeof window.supabase.createClient === "function") {
    return window.supabase;
  }
  if (typeof supabase !== "undefined" && typeof supabase.createClient === "function") {
    return supabase;
  }
  return null;
}

async function waitForSupabaseSDK(timeoutMs = 3000) {
  const start = Date.now();
  let sdk = getSupabaseSDK();
  while (!sdk && Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 100));
    sdk = getSupabaseSDK();
  }
  return sdk;
}

async function initAuth() {
  try {
    let statusData = {};
    try {
      const resp = await fetch("/api/status");
      if (resp.ok) statusData = await resp.json();
    } catch (e) {
      console.warn("Could not query /api/status:", e);
    }

    const isConnected = statusData.supabase_connected !== false;
    if (supabasePill) {
      if (isConnected) {
        supabasePill.innerHTML = '<span class="status-dot"></span>Supabase Connected';
      } else {
        supabasePill.innerHTML = '<span class="status-dot" style="background:var(--dim);box-shadow:none"></span>Local Mode';
      }
    }

    const sdk = await waitForSupabaseSDK();
    const url = statusData.supabase_url || FALLBACK_SUPABASE_URL;
    const key = statusData.supabase_key || FALLBACK_SUPABASE_KEY;

    if (url && key && sdk) {
      sbClient = sdk.createClient(url, key);

      // Check existing session
      const { data } = await sbClient.auth.getSession();
      if (data && data.session && data.session.user) {
        updateUserUI(data.session.user);
      } else {
        updateUserUI(null);
      }

      // Listen for session changes (login, logout, refresh)
      sbClient.auth.onAuthStateChange((event, session) => {
        const user = session ? session.user : null;
        updateUserUI(user);
        if (event === "SIGNED_IN") {
          closeAuthModal();
          loadHistory();
        } else if (event === "SIGNED_OUT") {
          loadHistory();
        }
      });
    } else {
      console.warn("Supabase SDK or credentials unavailable.");
    }
  } catch (err) {
    console.warn("Supabase auth initialization skipped or failed:", err);
  }
}

// ── Supabase History Functions ──
async function loadHistory() {
  try {
    let url = "/api/history";
    if (currentUser && currentUser.id) {
      url += `?user_id=${encodeURIComponent(currentUser.id)}`;
    }
    const resp = await fetch(url);
    const data = await resp.json();
    const list = data.history || [];

    if (list.length === 0) {
      historyItems.innerHTML = '<p class="history-empty">No saved investigations yet.</p>';
      return;
    }

    historyItems.innerHTML = "";
    list.forEach((item) => {
      const card = document.createElement("div");
      card.className = "history-item";
      card.innerHTML = `
        <div class="history-title">${escapeHtml(item.topic)}</div>
        <div class="history-meta">
          <span>${item.sources_count || 0} sources · ${item.claims_count || 0} claims</span>
          <span>${escapeHtml(String(item.created_at || "").slice(0, 16))}</span>
        </div>
      `;
      card.addEventListener("click", () => openHistoryDetail(item.id));
      historyItems.appendChild(card);
    });
  } catch (err) {
    historyItems.innerHTML = '<p class="history-empty">Unable to load history.</p>';
  }
}

async function openHistoryDetail(recordId) {
  closeDrawer();
  clearError();
  setLoading(true);

  try {
    const resp = await fetch(`/api/history/${encodeURIComponent(recordId)}`);
    if (!resp.ok) throw new Error("Could not fetch investigation record");
    const data = await resp.json();

    latestReport = data.report_markdown || "";
    resultsTitle.textContent = data.topic;
    reportContent.innerHTML = renderMarkdown(latestReport);

    renderVisuals(data.visuals);
    renderSources(data.sources);
    renderAudit(data.claims);

    if (cloudSavedBadge) cloudSavedBadge.hidden = false;
    results.hidden = false;
    setPipeline(stepNames.length, "");
    results.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showError(err.message || "Failed to load past investigation.");
  } finally {
    setLoading(false);
  }
}

function openDrawer() {
  historyDrawer.hidden = false;
  drawerOverlay.hidden = false;
  loadHistory();
}

function closeDrawer() {
  historyDrawer.hidden = true;
  drawerOverlay.hidden = true;
}

if (historyToggleBtn) historyToggleBtn.addEventListener("click", openDrawer);
if (closeHistoryBtn) closeHistoryBtn.addEventListener("click", closeDrawer);
if (drawerOverlay) drawerOverlay.addEventListener("click", closeDrawer);

function runResearch(topic) {
  clearError();
  results.hidden = true;
  if (cloudSavedBadge) cloudSavedBadge.hidden = true;
  setLoading(true);
  setPipeline(0, "");

  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }

  let streamUrl = `/api/research/stream?topic=${encodeURIComponent(topic)}`;
  if (currentUser) {
    if (currentUser.id) streamUrl += `&user_id=${encodeURIComponent(currentUser.id)}`;
    if (currentUser.email) streamUrl += `&user_email=${encodeURIComponent(currentUser.email)}`;
  }
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

      if (cloudSavedBadge) cloudSavedBadge.hidden = false;
      results.hidden = false;
      setPipeline(stepNames.length, "");
      results.scrollIntoView({ behavior: "smooth", block: "start" });

      // Refresh history in background
      loadHistory();
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

// ── Auth & Modal Event Listeners ──
if (authBtn) {
  authBtn.addEventListener("click", () => openAuthModal("signin"));
}
if (closeAuthBtn) {
  closeAuthBtn.addEventListener("click", closeAuthModal);
}
if (authToggleModeBtn) {
  authToggleModeBtn.addEventListener("click", () => {
    updateAuthModalMode(authMode === "signin" ? "signup" : "signin");
  });
}
if (authModal) {
  authModal.addEventListener("click", (e) => {
    if (e.target === authModal) closeAuthModal();
  });
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (authModal && !authModal.hidden) closeAuthModal();
    if (historyDrawer && !historyDrawer.hidden) closeDrawer();
  }
});
if (logoutBtn) {
  logoutBtn.addEventListener("click", async () => {
    if (sbClient) {
      await sbClient.auth.signOut();
    }
    updateUserUI(null);
  });
}

if (authForm) {
  authForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearAuthMessages();

    const email = authEmailInput ? authEmailInput.value.trim() : "";
    const password = authPasswordInput ? authPasswordInput.value : "";

    if (!email || !password) {
      showAuthError("Please provide both email and password.");
      return;
    }
    if (!sbClient) {
      await initAuth();
    }
    if (!sbClient) {
      showAuthError("Unable to establish Supabase connection. Please refresh the page and try again.");
      return;
    }

    if (authSubmitBtn) authSubmitBtn.disabled = true;
    if (authSubmitLabel) {
      authSubmitLabel.textContent = authMode === "signin" ? "Signing In..." : "Creating Account...";
    }

    try {
      if (authMode === "signin") {
        const { data, error } = await sbClient.auth.signInWithPassword({ email, password });
        if (error) throw error;
        closeAuthModal();
      } else {
        const { data, error } = await sbClient.auth.signUp({ email, password });
        if (error) throw error;
        if (data.session) {
          closeAuthModal();
        } else {
          showAuthSuccess("Account created! Please check your email inbox to confirm your account, or sign in if confirmed.");
        }
      }
    } catch (err) {
      showAuthError(err.message || "Authentication error occurred.");
    } finally {
      if (authSubmitBtn) authSubmitBtn.disabled = false;
      if (authSubmitLabel) {
        authSubmitLabel.textContent = authMode === "signin" ? "Sign In" : "Create Account";
      }
    }
  });
}

// Initialize Supabase Auth and load history on startup
initAuth();
loadHistory();
