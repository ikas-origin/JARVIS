const params = new URLSearchParams(window.location.search);
const suppliedToken = params.get("token");
if (suppliedToken) {
  sessionStorage.setItem("jarvis-web-token", suppliedToken);
  history.replaceState({}, "", window.location.pathname);
}

const token = sessionStorage.getItem("jarvis-web-token") || "";
const health = document.querySelector("#health");
const workspace = document.querySelector("#workspace");
const model = document.querySelector("#model");
const approval = document.querySelector("#approval");
const session = document.querySelector("#session");
const state = document.querySelector("#task-state");
const timeline = document.querySelector("#timeline");
const welcome = document.querySelector("#welcome");
const form = document.querySelector("#task-form");
const taskInput = document.querySelector("#task");
const submit = document.querySelector("#submit");
const message = document.querySelector("#message");
const messageTemplate = document.querySelector("#message-template");
const traceTemplate = document.querySelector("#trace-template");
const approvalTemplate = document.querySelector("#approval-template");

let activeTaskId = null;
let lastSeq = 0;
let assistantCard = null;
let polling = false;
const approvalCards = new Map();

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "X-JARVIS-Token": token,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({
    error: { message: `HTTP ${response.status}` },
  }));
  if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
  return payload;
}

function setHealth(kind, label) {
  health.className = `health ${kind}`;
  health.querySelector("strong").textContent = label;
}

function setBusy(status) {
  const busy = ["queued", "running", "waiting_approval"].includes(status);
  state.textContent = (status || "ready").replace("_", " ").toUpperCase();
  state.className = `state ${busy ? "busy" : status === "failed" ? "failed" : "idle"}`;
  taskInput.disabled = busy;
  submit.disabled = busy;
}

function setMessage(text, isError = false) {
  message.textContent = text;
  message.classList.toggle("error", isError);
}

function scrollTimeline() {
  timeline.scrollTop = timeline.scrollHeight;
}

function timeLabel(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function addMessage(role, text, at = new Date()) {
  welcome?.remove();
  const card = messageTemplate.content.firstElementChild.cloneNode(true);
  card.classList.add(role);
  card.querySelector(".role").textContent = role === "user" ? "YOU" : "JARVIS";
  card.querySelector("time").textContent = timeLabel(at);
  card.querySelector(".body").textContent = text;
  timeline.append(card);
  scrollTimeline();
  return card;
}

function addTrace(title, detail = "", tone = "") {
  const row = traceTemplate.content.firstElementChild.cloneNode(true);
  if (tone) row.classList.add(tone);
  row.querySelector("strong").textContent = title;
  row.querySelector("pre").textContent = detail;
  timeline.append(row);
  scrollTimeline();
  return row;
}

function renderApproval(data) {
  const card = approvalTemplate.content.firstElementChild.cloneNode(true);
  card.querySelector("strong").textContent = data.action;
  for (const button of card.querySelectorAll("button")) {
    button.addEventListener("click", async () => {
      for (const candidate of card.querySelectorAll("button")) candidate.disabled = true;
      try {
        await request(`/api/approvals/${data.approval_id}`, {
          method: "POST",
          body: JSON.stringify({ approved: button.dataset.decision === "true" }),
        });
      } catch (error) {
        setMessage(error.message, true);
      }
    });
  }
  approvalCards.set(data.approval_id, card);
  timeline.append(card);
  scrollTimeline();
}

function renderEvent(event) {
  const data = event.data || {};
  switch (event.type) {
    case "task_started":
      addTrace("TASK STARTED", "Agent loop is running");
      break;
    case "model_request":
      assistantCard = null;
      addTrace(`THINKING · TURN ${data.turn || "?"}`, "Requesting the configured model");
      break;
    case "assistant_delta":
      if (!assistantCard) assistantCard = addMessage("assistant", "", event.at);
      assistantCard.querySelector(".body").textContent += data.text || "";
      scrollTimeline();
      break;
    case "tool_start":
      addTrace(`TOOL ▶ ${data.name}`, JSON.stringify(data.arguments || {}, null, 2));
      break;
    case "tool_end":
      addTrace(
        `TOOL ${data.ok ? "✓" : "✗"} ${data.name}`,
        [JSON.stringify(data.metadata || {}), data.content || ""].filter(Boolean).join("\n"),
        data.ok ? "ok" : "error",
      );
      break;
    case "context_trimmed":
      addTrace("CONTEXT COMPACTED", `${data.before_messages} → ${data.after_messages} messages`);
      break;
    case "verification_required":
      addTrace("VERIFY REQUIRED", "Executable evidence is required after file changes", "error");
      break;
    case "approval_required":
      setBusy("waiting_approval");
      renderApproval(data);
      break;
    case "approval_resolved": {
      const card = approvalCards.get(data.approval_id);
      if (card) {
        card.querySelector(".eyebrow").textContent = data.approved ? "APPROVED" : "DENIED";
        for (const button of card.querySelectorAll("button")) button.disabled = true;
      }
      break;
    }
    case "task_failed":
      addTrace("TASK FAILED", data.message || "Unknown failure", "error");
      break;
    default:
      break;
  }
}

function finishTask(task) {
  setBusy(task.status);
  const answer = task.result?.answer || "";
  if (answer && (!assistantCard || !assistantCard.querySelector(".body").textContent.trim())) {
    assistantCard = addMessage("assistant", answer);
  }
  if (task.result) {
    const result = task.result;
    addTrace(
      `${result.status?.toUpperCase()} · ${result.stop_reason}`,
      `turns ${result.turns} · tools ${result.tool_calls} · verify ${result.verification_status} · ${result.elapsed_seconds}s`,
      result.ok ? "ok" : "error",
    );
  }
  if (task.error) addTrace("ERROR", task.error.message, "error");
  activeTaskId = null;
  polling = false;
  setMessage("任务结束，可以继续多轮对话");
  taskInput.focus();
}

async function pollTask() {
  if (polling || !activeTaskId) return;
  polling = true;
  while (activeTaskId) {
    try {
      const payload = await request(`/api/tasks/${activeTaskId}?after=${lastSeq}`);
      const task = payload.task;
      for (const event of task.events) renderEvent(event);
      lastSeq = task.last_seq;
      setBusy(task.status);
      if (!["queued", "running", "waiting_approval"].includes(task.status)) {
        finishTask(task);
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 350));
    } catch (error) {
      polling = false;
      setMessage(error.message, true);
      setHealth("error", "DISCONNECTED");
      break;
    }
  }
}

async function loadStatus() {
  if (!token) throw new Error("Missing local Web token. Restart jarvis-web and use the printed URL.");
  const payload = await request("/api/status");
  workspace.textContent = payload.workspace;
  workspace.title = payload.workspace;
  model.textContent = payload.model || "(missing)";
  approval.textContent = payload.approval;
  session.textContent = payload.session_id ? payload.session_id.slice(0, 10) : "not saved";
  setHealth("online", `LOCAL · ${payload.version}`);
  if (payload.active_task_id) {
    activeTaskId = payload.active_task_id;
    lastSeq = 0;
    setBusy(payload.active_status);
    pollTask();
  } else {
    setBusy("ready");
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const task = taskInput.value.trim();
  if (!task) return;
  addMessage("user", task);
  assistantCard = null;
  lastSeq = 0;
  setBusy("queued");
  setMessage("任务已进入本地 Agent");
  try {
    const payload = await request("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ task }),
    });
    activeTaskId = payload.task_id;
    taskInput.value = "";
    pollTask();
  } catch (error) {
    setBusy("failed");
    setMessage(error.message, true);
    addTrace("REQUEST REJECTED", error.message, "error");
  }
});

taskInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.ctrlKey) form.requestSubmit();
});

loadStatus().catch((error) => {
  setHealth("error", "UNAUTHORIZED");
  setBusy("failed");
  setMessage(error.message, true);
});
