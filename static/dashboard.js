/*
 * Dashboard browser flow
 * ----------------------
 * 1. refreshTopics() loads topic names and caches attempt records by ID.
 * 2. loadScores() loads the selected topic and redraws the chart/table.
 * 3. sendChatMessage() sends the question, selected topic, and recent history
 *    to POST /api/dashboard/chat.
 * 4. FastAPI returns a final answer; this file only renders it.
 *
 * The Groq API key and all database access stay on the FastAPI server.
 */

// DOM references: these connect the JavaScript behavior to dashboard.html.
const topicSelect = document.querySelector("#topic-select");
const topicCount = document.querySelector("#topic-count");
const refreshTopicsButton = document.querySelector("#refresh-topics");
const chartContainer = document.querySelector(".chart-container");
const chartMessage = document.querySelector("#chart-message");
const chartSummary = document.querySelector("#chart-summary");
const latestScore = document.querySelector("#latest-score");
const attemptRows = document.querySelector("#attempt-rows");
const chatPanel = document.querySelector("#chat-panel");
const chatBody = document.querySelector("#chat-body");
const chatInput = document.querySelector("#chat-input");
const sendChatButton = document.querySelector("#send-chat");
const closeChatButton = document.querySelector("#close-chat");
const openChatButton = document.querySelector("#open-chat");
const chatProviderStatus = document.querySelector("#chat-provider-status");

let scoreChart;

// Attempts are cached so progression points can be enriched with the complete
// attempt record without adding another request every time the topic changes.
let attemptsById = new Map();

// Chat history is browser-memory only. The most recent messages are sent with
// each request so Llama can understand follow-up questions.
let chatHistory = [];

function formatDate(value) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(`${value}T12:00:00`));
}

function showMessage(message) {
  chartContainer.classList.remove("ready");
  chartMessage.textContent = message;
  latestScore.textContent = "—";
  chartSummary.textContent = message;
}

function drawChart(points) {
  const context = document.querySelector("#score-chart").getContext("2d");
  scoreChart?.destroy();

  scoreChart = new Chart(context, {
    type: "line",
    data: {
      labels: points.map((point) => formatDate(point.attemptedDate)),
      datasets: [
        {
          label: "Score",
          data: points.map((point) => point.score),
          borderColor: "#246bfd",
          backgroundColor: "#246bfd",
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
          tension: 0.2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => {
              const point = points[item.dataIndex];

              return [
                `${point.company ?? "Unknown"} · ${point.role ?? "Unknown role"}`,
                `Focus: ${point.focusTopic ?? point.topic}`,
                `Source: ${point.attemptSource}`,
                `Status: ${point.status}`,
                `Attempt: ${point.attemptNumber ?? "—"}`,
                point.roundNumber ? `Round: ${point.roundNumber}` : null,
                point.startedAt ? `Started: ${formatDateTime(point.startedAt)}` : null,
                point.completedAt
                  ? `Completed: ${formatDateTime(point.completedAt)}`
                  : null,
                point.notes ? `Notes: ${point.notes.slice(0, 150)}` : null,
              ].filter(Boolean);
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
        },
        y: {
          min: 0,
          max: 100,
          ticks: { stepSize: 20 },
        },
      },
    },
  });

  chartContainer.classList.add("ready");
}

function drawTable(points) {
  attemptRows.replaceChildren();

  [...points].reverse().forEach((point) => {
    const row = document.createElement("tr");
    const company = document.createElement("td");
    const role = document.createElement("td");
    const focus = document.createElement("td");
    const attemptSource = document.createElement("td");
    const status = document.createElement("td");
    const roundNumber = document.createElement("td");
    const startedAt = document.createElement("td");
    const completedAt = document.createElement("td");
    const notes = document.createElement("td");
    const date = document.createElement("td");
    const attempt = document.createElement("td");
    const score = document.createElement("td");

    company.textContent = point.company ?? "Unknown";
    role.textContent = point.role ?? "Unknown role";
    focus.textContent = point.focusTopic ?? point.topic;

    date.textContent = formatDate(point.attemptedDate);
    attempt.textContent = `Attempt ${point.attemptNumber}`;
    score.textContent = point.score.toFixed(1);
    attemptSource.textContent = point.attemptSource;
    status.textContent = point.status;
    roundNumber.textContent = point.roundNumber;
    startedAt.textContent = point.startedAt ? formatDateTime(point.startedAt) : "—";
    completedAt.textContent = point.completedAt ? formatDateTime(point.completedAt) : "—";
    notes.textContent = point.notes ? point.notes.slice(0, 150) : "—";

    row.append(date, attempt, company, role, focus, attemptSource, status, roundNumber, startedAt, completedAt, notes, score);
    attemptRows.append(row);
  });
}

async function loadScores(topic) {
  // NORMAL DASHBOARD DATA PATH:
  // selected topic -> FastAPI progression endpoint -> PostgreSQL -> chart/table.
  showMessage("Loading scores…");
  attemptRows.replaceChildren();

  try {
    const response = await fetch(
      `/api/dashboard/topic-score-progression?focusTopic=${encodeURIComponent(topic)}`,
    );
    if (!response.ok) {
      throw new Error("Could not load scores.");
    }

    const { points } = await response.json();
    if (!points.length) {
      throw new Error("No scores found for this topic.");
    }

    const enrichedPoints = points.map((point) => ({
      ...(attemptsById.get(point.attemptId) || {}),
      ...point,
    }));

    const first = enrichedPoints[0].score;
    const last = enrichedPoints.at(-1).score;
    const change = last - first;

    latestScore.textContent = last.toFixed(1);
    chartSummary.textContent =
      enrichedPoints.length === 1
        ? "1 completed attempt"
        : `${enrichedPoints.length} attempts · ${change >= 0 ? "+" : ""}${change.toFixed(1)} points`;

    drawChart(enrichedPoints);
    drawTable(enrichedPoints);
  } catch (error) {
    scoreChart?.destroy();
    showMessage(error.message);
    attemptRows.innerHTML =
      '<tr class="empty-row"><td colspan="12">No attempts to show.</td></tr>';
  }
}

async function refreshTopics() {
  // Load both the selector options and full attempts. Once those are available,
  // loadScores() fetches the chronological points for the selected topic.
  const selectedTopic = topicSelect.value;
  refreshTopicsButton.disabled = true;

  try {
    const response = await fetch("/api/dashboard/challenge-topics");
    if (!response.ok) {
      throw new Error("Could not load topics.");
    }

    const response1 = await fetch("/api/attempts?limit=500");
    if (!response1.ok) {
      throw new Error("Could not load attempts.");
    }

    const attempts = await response1.json();
    attemptsById = new Map(attempts.map((attempt) => [attempt.id, attempt]));
    
    const topics = await response.json();
    topicSelect.replaceChildren();
    topicCount.textContent = `(${topics.length})`;

    if (!topics.length) {
      topicSelect.append(new Option("No topics available", ""));
      topicSelect.disabled = true;
      showMessage("No challenge scores found.");
      return;
    }

    topics.forEach(({ focusTopic }) => {
      topicSelect.append(new Option(focusTopic, focusTopic));
    });

    if (topics.some(({ focusTopic }) => focusTopic === selectedTopic)) {
      topicSelect.value = selectedTopic;
    }

    topicSelect.disabled = false;
    await loadScores(topicSelect.value);
  } catch (error) {
    topicSelect.replaceChildren(new Option("Topics unavailable", ""));
    topicCount.textContent = "";
    topicSelect.disabled = true;
    showMessage(error.message);
  } finally {
    refreshTopicsButton.disabled = false;
  }
}

function formatDateTime(value) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "numeric",
  }).format(new Date(value));
}

function addChatMessage(text, type, extraClass) {
  const message = document.createElement("div");
  message.classList.add("chat-message", type);
  if (extraClass) {
    message.classList.add(extraClass);
  }
  message.textContent = text;
  chatBody.appendChild(message);
  chatBody.scrollTop = chatBody.scrollHeight;
  return message;
}

async function sendChatMessage() {
  // CHAT DATA PATH:
  // browser -> POST /api/dashboard/chat -> Llama/tool/database flow -> browser.
  const messageText = chatInput.value.trim();
  if (!messageText || sendChatButton.disabled) {
    return;
  }

  addChatMessage(messageText, "outgoing");

  // Keep the payload bounded. The current message is added separately after
  // priorHistory is captured, so it is not duplicated in the request.
  const priorHistory = chatHistory.slice(-10);
  chatHistory.push({ role: "user", content: messageText });
  chatInput.value = "";
  chatInput.disabled = true;
  sendChatButton.disabled = true;
  const pendingMessage = addChatMessage("Checking your dashboard…", "incoming", "pending");

  try {
    const response = await fetch("/api/dashboard/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: messageText,
        // This lets phrases such as "this topic" resolve to the current select.
        focusTopic: topicSelect.value || null,
        history: priorHistory,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "The chat service could not answer.");
    }
    pendingMessage.remove();

    // The response also contains an ``operations`` audit trace. It is useful
    // for debugging but intentionally not displayed in the chat panel yet.
    chatProviderStatus.textContent =
      data.provider === "groq" ? data.model : "Local fallback";
    addChatMessage(data.reply, "incoming");
    chatHistory.push({ role: "assistant", content: data.reply });
  } catch (error) {
    pendingMessage.remove();
    addChatMessage(error.message, "incoming", "error");
  } finally {
    chatInput.disabled = false;
    sendChatButton.disabled = false;
    chatInput.focus();
  }
}

// UI wiring and initial page load.
topicSelect.addEventListener("change", () => loadScores(topicSelect.value));
refreshTopicsButton.addEventListener("click", refreshTopics);
window.addEventListener("focus", refreshTopics);
sendChatButton.addEventListener("click", sendChatMessage);
chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.isComposing) {
    event.preventDefault();
    sendChatMessage();
  }
});
closeChatButton.addEventListener("click", () => {
  chatPanel.classList.add("hidden");
  openChatButton.classList.remove("hidden");
});
openChatButton.addEventListener("click", () => {
  chatPanel.classList.remove("hidden");
  openChatButton.classList.add("hidden");
  chatInput.focus();
});
refreshTopics();
