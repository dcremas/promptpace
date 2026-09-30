// PromptPace front end: records edit timings in the text box and renders the analysis.
// All URLs are relative so the app works at a domain root or under an nginx sub-path.

const $ = (id) => document.getElementById(id);
const ui = {
  taskText: $("task-text"), taskCategory: $("task-category"), newTask: $("new-task"),
  input: $("response"), finish: $("finish"), reset: $("reset"), error: $("error"),
  liveTime: $("live-time"), liveWords: $("live-words"), liveState: $("live-state"),
  results: $("results"), resultsPrompt: $("results-prompt"), threshold: $("threshold"),
  insights: $("insights"), chart: $("chart"), tooltip: $("tooltip"), chartTable: $("chart-table"),
  bands: $("pause-bands"), details: $("details"), written: $("written"),
  issueList: $("issue-list"), reviewSummary: $("review-summary"),
  dictList: $("dict-list"), dictCount: $("dict-count"),
  history: $("history"), historyEmpty: $("history-empty"),
};

const state = {
  prompt: null,
  shownAt: 0,        // performance.now() when the task appeared
  events: [],
  prevLen: 0,
  selLen: 0,
  finished: false,
  session: null,     // last SessionOut from the server
  words: [],         // this browser's dictionary
  ticker: 0,
};

// ---------- API ----------

async function api(path, options = {}) {
  const res = await fetch(`api/${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* keep status text */ }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

// ---------- Task & recording ----------

async function loadTask() {
  const exclude = state.prompt ? `?exclude=${encodeURIComponent(state.prompt.id)}` : "";
  try {
    state.prompt = await api(`prompts/random${exclude}`);
    ui.taskText.textContent = state.prompt.text;
    ui.taskCategory.textContent = state.prompt.category;
  } catch (err) {
    ui.taskText.textContent = "Couldn't load a task. Is the server running?";
    showError(err);
  }
  resetRecording();
}

function resetRecording() {
  state.events = [];
  state.prevLen = 0;
  state.selLen = 0;
  state.finished = false;
  state.shownAt = performance.now();
  ui.input.value = "";
  ui.input.disabled = !state.prompt;
  ui.input.readOnly = false;
  ui.finish.disabled = true;
  setStatus("Waiting for your first keystroke", "idle");
  showError(null);
  updateLive();
  ui.input.focus();
}

ui.input.addEventListener("beforeinput", () => {
  state.selLen = ui.input.selectionEnd - ui.input.selectionStart;
});

ui.input.addEventListener("input", (e) => {
  if (state.finished) return;
  const len = ui.input.value.length;
  const delta = len - state.prevLen;
  const type = e.inputType || "insertText";
  let kind = "type", added = 0, removed = 0;

  if (type.startsWith("delete")) {
    kind = "delete";
    removed = Math.max(0, -delta);
  } else if (type.startsWith("history")) {
    // Undo/redo: count what changed, but never as typing.
    kind = delta < 0 ? "delete" : "paste";
    added = Math.max(0, delta);
    removed = Math.max(0, -delta);
  } else {
    added = Math.max(0, delta + state.selLen);
    removed = state.selLen;
    if (type === "insertFromPaste" || type === "insertFromDrop" || type === "insertReplacementText") {
      kind = "paste";
    }
  }
  state.prevLen = len;
  state.selLen = 0;

  const t = Math.max(0, e.timeStamp - state.shownAt);
  state.events.push({ t: Math.round(t * 10) / 10, kind, added, removed });

  if (state.events.length === 1) {
    setStatus("Recording", "recording");
    clearInterval(state.ticker);
    state.ticker = setInterval(updateLive, 250);
  }
  ui.finish.disabled = ui.input.value.trim().length === 0;
  updateLive();
});

// Enter finishes, like sending a message in an AI chat box; Shift+Enter adds a line break.
// preventDefault means no input event fires, so the timing still ends at the last real edit.
// On touch screens Return stays a line break (as in mobile chat apps) unless ⌘/Ctrl is held.
const touchOnly = matchMedia("(hover: none) and (pointer: coarse)").matches;
if (touchOnly) {
  ui.input.placeholder =
    "Write the prompt you'd send to the AI. The timer starts on your first keystroke. Tap Finish when you're done.";
}
ui.input.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.shiftKey || e.altKey || e.isComposing) return;
  if (touchOnly && !e.metaKey && !e.ctrlKey) return;
  e.preventDefault();
  if (!ui.finish.disabled) finish();
});

// The mode drives the status light's color (see .live-state in styles.css).
function setStatus(text, mode) {
  ui.liveState.textContent = text;
  ui.liveState.dataset.state = mode;
}

function updateLive() {
  const first = state.events[0];
  const elapsed = first ? (performance.now() - state.shownAt - first.t) / 1000 : 0;
  ui.liveTime.textContent = clock(state.finished ? lastWritingSeconds() : elapsed);
  const words = ui.input.value.trim().split(/\s+/).filter(Boolean).length;
  ui.liveWords.textContent = words;
}

function lastWritingSeconds() {
  const ev = state.events;
  return ev.length ? (ev.at(-1).t - ev[0].t) / 1000 : 0;
}

async function finish() {
  if (state.finished || !state.events.length) return;
  state.finished = true;
  clearInterval(state.ticker);
  ui.input.readOnly = true;
  ui.finish.disabled = true;
  setStatus("Analyzing…", "busy");
  updateLive();
  try {
    const session = await api("sessions", {
      method: "POST",
      body: JSON.stringify({
        prompt_id: state.prompt.id,
        text: ui.input.value,
        events: state.events,
        pause_threshold_ms: Number(ui.threshold.value),
      }),
    });
    setStatus("Done. Timing stopped at your last keystroke.", "done");
    renderSession(session);
    loadHistory();
  } catch (err) {
    state.finished = false;
    ui.input.readOnly = false;
    ui.finish.disabled = false;
    setStatus("Recording", "recording");
    showError(err);
  }
}

ui.finish.addEventListener("click", finish);
ui.reset.addEventListener("click", resetRecording);
ui.newTask.addEventListener("click", loadTask);

ui.threshold.addEventListener("change", async () => {
  if (!state.session) return;
  try {
    renderSession(await api(`sessions/${state.session.id}?pause_threshold_ms=${ui.threshold.value}`));
  } catch (err) {
    showError(err);
  }
});

function showError(err) {
  ui.error.hidden = !err;
  ui.error.textContent = err ? `Something went wrong: ${err.message}` : "";
}

// ---------- Formatting ----------

function clock(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function duration(seconds) {
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}\u00a0s`;
  const m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}
const num = (v) => (v == null ? "–" : Math.round(v).toLocaleString());
const pct = (v) => `${Math.round(v * 100)}%`;
// One decimal place, but never round 99.6% up to a "perfect" 100%.
const pct1 = (v) => `${(Math.floor(v * 1000) / 10).toFixed(1).replace(/\.0$/, "")}%`;
const plural = (n, word, many = `${word}s`) => `${n.toLocaleString()} ${n === 1 ? word : many}`;

// ---------- Results ----------

function renderSession(session, { scroll = true } = {}) {
  state.session = session;
  const a = session.analysis;
  const s = a.summary;
  ui.results.hidden = false;
  ui.resultsPrompt.textContent = `${session.prompt.category} · ${session.prompt.text}`;
  ui.threshold.value = String(a.pause_threshold_ms);

  $("m-overall").textContent = num(s.overall_wpm);
  $("m-overall-sub").textContent = `${plural(s.final_words, "word")} in ${duration(s.writing_seconds)}`;
  $("m-burst").textContent = num(s.burst_wpm);
  $("m-burst-sub").textContent = s.peak_burst_wpm
    ? `Fastest burst ${num(s.peak_burst_wpm)} WPM`
    : `Over ${duration(s.active_seconds)} of active typing`;
  $("m-pause").textContent = duration(s.pause_seconds);
  $("m-pause-sub").textContent = s.pause_count
    ? `${pct(s.pause_share)} of writing time · ${plural(s.pause_count, "pause")} · longest ${duration(s.longest_pause_seconds)}`
    : "No pauses at this threshold";
  $("m-back").textContent = s.backspaces_per_100_keys.toFixed(1).replace(/\.0$/, "");
  $("m-back-sub").textContent =
    `${plural(s.backspace_count, "press", "presses")} · ${pct(s.deleted_share)} of typed characters removed`;
  const acc = a.accuracy;
  $("m-acc").textContent = acc.spelling_accuracy == null ? "–" : pct1(acc.spelling_accuracy);
  $("m-acc-sub").textContent = acc.words_checked
    ? `${plural(acc.misspelled, "misspelled word")} of ${acc.words_checked.toLocaleString()} checked · net ${num(acc.net_wpm)} WPM`
    : "Nothing to check yet";

  ui.insights.replaceChildren(...a.insights.map((text) => el("li", {}, text)));

  renderReview(session.text, acc);
  renderBands(a.pause_buckets);
  renderDetails(s, a.pause_threshold_ms);
  renderChart(a);
  renderChartTable(a);
  markCurrentHistoryRow();
  if (scroll) {
    // Restart the entrance animation for a fresh result (void forces a reflow).
    ui.results.classList.remove("reveal");
    void ui.results.offsetWidth;
    ui.results.classList.add("reveal");
    ui.results.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function renderBands(buckets) {
  const max = Math.max(1, ...buckets.map((b) => b.seconds));
  ui.bands.replaceChildren(...buckets.map((b) => {
    const fill = el("div", { class: "band-fill" });
    fill.style.width = `${(b.seconds / max) * 100}%`;
    return el("li", { class: "band-row" },
      el("span", {}, b.label),
      el("div", { class: "band-track", "aria-hidden": "true" }, fill),
      el("span", { class: "band-val" }, b.count ? `${plural(b.count, "pause")} · ${duration(b.seconds)}` : "None"),
    );
  }));
}

function renderDetails(s, thresholdMs) {
  const rows = [
    ["Time before first keystroke", duration(s.time_to_first_key_seconds)],
    ["Writing time (first to last key)", duration(s.writing_seconds)],
    ["Active typing time", duration(s.active_seconds)],
    ["Pause threshold", `${thresholdMs / 1000} s`],
    ["Characters typed", s.chars_typed.toLocaleString()],
    ["Characters in final text", s.final_chars.toLocaleString()],
    ["Characters removed", s.chars_deleted.toLocaleString()],
  ];
  if (s.paste_count) rows.push(["Pasted", `${plural(s.paste_count, "paste")}, ${s.chars_pasted} chars`]);
  ui.details.replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
}

function renderChartTable(a) {
  const pauses = a.pauses;
  const step = a.timeline.bucket_seconds;
  const head = el("thead", {}, el("tr", {},
    el("th", {}, "Time"), el("th", { class: "num" }, "WPM"), el("th", { class: "num" }, "Typed"),
    el("th", { class: "num" }, "Deleted"), el("th", {}, "Paused")));
  const body = el("tbody", {}, ...a.timeline.buckets.map((b) => {
    const paused = pausedSeconds(pauses, b.start_s, b.start_s + step);
    return el("tr", {},
      el("td", {}, `${clock(b.start_s)}–${clock(b.start_s + step)}`),
      el("td", { class: "num" }, num(b.wpm)),
      el("td", { class: "num" }, String(b.typed)),
      el("td", { class: "num" }, String(b.deleted)),
      el("td", {}, paused > 0 ? duration(paused) : ""));
  }));
  ui.chartTable.replaceChildren(head, body);
}

function pausedSeconds(pauses, from, to) {
  return pauses.reduce((sum, p) => sum + Math.max(0, Math.min(to, p.end_s) - Math.max(from, p.start_s)), 0);
}

// ---------- Rhythm chart (SVG) ----------

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  node.append(...children);
  return node;
}

function niceStep(max, target = 4) {
  const raw = max / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
}

function renderChart(a) {
  const { buckets, bucket_seconds: step } = a.timeline;
  const width = Math.max(300, ui.chart.clientWidth);
  const height = 240;
  const m = { top: 26, right: 8, bottom: 52, left: 36 };
  const plotW = width - m.left - m.right;
  const plotH = height - m.top - m.bottom;
  const total = buckets.length * step;
  const x = (sec) => m.left + (sec / total) * plotW;
  const maxWpm = Math.max(20, ...buckets.map((b) => b.wpm));
  const yStep = niceStep(maxWpm);
  const yMax = Math.ceil(maxWpm / yStep) * yStep;
  const y = (v) => m.top + plotH - (v / yMax) * plotH;
  const band = plotW / buckets.length;
  const barW = Math.max(1, Math.min(24, band - 2));
  const laneY = m.top + plotH + 16;

  const root = svg("svg", {
    viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": `Typing speed over ${clock(total)}, in ${step}-second columns, with pauses shaded.`,
  });

  // Pauses first, so bars and gridlines sit on top.
  for (const p of a.pauses) {
    const x0 = x(p.start_s), x1 = x(p.end_s);
    root.append(svg("rect", { class: "pause", x: x0, y: m.top, width: Math.max(1, x1 - x0), height: plotH }));
    if (x1 - x0 >= 34) {
      root.append(svg("text", { x: (x0 + x1) / 2, y: m.top + 12, "text-anchor": "middle" }, `${Math.round(p.seconds)} s`));
    }
  }

  for (let v = 0; v <= yMax; v += yStep) {
    root.append(svg("line", { class: v === 0 ? "axis" : "grid", x1: m.left, x2: width - m.right, y1: y(v), y2: y(v) }));
    root.append(svg("text", { x: m.left - 8, y: y(v) + 4, "text-anchor": "end" }, String(v)));
  }
  root.append(svg("text", { x: 0, y: 11 }, "WPM"));

  // Columns: 4px rounded data end, square at the baseline.
  buckets.forEach((b, i) => {
    if (b.wpm <= 0) return;
    const cx = m.left + band * (i + 0.5);
    const top = y(b.wpm), base = y(0);
    const r = Math.min(4, barW / 2, base - top);
    const l = cx - barW / 2, rr = cx + barW / 2;
    root.append(svg("path", {
      class: "bar",
      d: `M${l},${base}V${top + r}Q${l},${top} ${l + r},${top}H${rr - r}Q${rr},${top} ${rr},${top + r}V${base}Z`,
    }));
  });

  // Deletion lane beneath the axis: dot size grows with characters removed.
  root.append(svg("text", { class: "lane-label", x: 0, y: laneY + 4 }, "Del"));
  const maxDel = Math.max(1, ...buckets.map((b) => b.deleted));
  buckets.forEach((b, i) => {
    if (!b.deleted) return;
    root.append(svg("circle", {
      class: "del", cx: m.left + band * (i + 0.5), cy: laneY, r: 4 + 3 * Math.sqrt(b.deleted / maxDel),
    }));
  });

  // Time axis.
  const tStep = niceStep(total, Math.max(2, Math.floor(plotW / 90)));
  for (let t = 0; t <= total + 0.001; t += tStep) {
    root.append(svg("text", { x: x(t), y: height - 8, "text-anchor": t === 0 ? "start" : "middle" }, clock(t)));
  }

  // Hit targets: one full-height column per bucket, wider than the mark.
  buckets.forEach((b, i) => {
    const hit = svg("rect", { class: "hit", x: m.left + band * i, y: m.top, width: band, height: laneY + 10 - m.top });
    hit.addEventListener("pointerenter", (e) => showTip(e, b, step, a.pauses, hit));
    hit.addEventListener("pointermove", moveTip);
    hit.addEventListener("pointerleave", () => hideTip(hit));
    root.append(hit);
  });

  ui.chart.replaceChildren(root);
}

function showTip(e, b, step, pauses, hit) {
  hit.classList.add("active");
  const paused = pausedSeconds(pauses, b.start_s, b.start_s + step);
  const lines = [
    el("b", {}, `${clock(b.start_s)}–${clock(b.start_s + step)}`),
    el("br"), `${num(b.wpm)} WPM · ${plural(b.typed, "char")} typed`,
  ];
  if (b.deleted) lines.push(el("br"), `${plural(b.deleted, "char")} deleted`);
  if (paused > 0.05) lines.push(el("br"), `Paused ${duration(paused)}`);
  ui.tooltip.replaceChildren(...lines);
  ui.tooltip.hidden = false;
  moveTip(e);
}
function moveTip(e) {
  const tip = ui.tooltip;
  const pad = 14;
  let left = e.clientX + pad;
  if (left + tip.offsetWidth > window.innerWidth - 8) left = e.clientX - tip.offsetWidth - pad;
  tip.style.left = `${Math.max(8, left)}px`;
  tip.style.top = `${Math.max(8, e.clientY - tip.offsetHeight - pad)}px`;
}
function hideTip(hit) {
  hit.classList.remove("active");
  ui.tooltip.hidden = true;
}

new ResizeObserver(() => {
  if (state.session && !ui.results.hidden) renderChart(state.session.analysis);
}).observe(ui.chart);

// ---------- Writing review (spelling & mechanics) ----------

const ISSUE_LABELS = {
  spelling: "Spelling",
  unknown: "Not in dictionary",
  repeated_word: "Repeated word",
  capitalization: "Capitalization",
  spacing: "Spacing",
};
const issueClass = (kind) =>
  kind === "spelling" ? "sp" : kind === "unknown" ? "unk" : "mech";

function renderReview(text, acc) {
  // Offsets from the server are UTF-16 indexes, which is how JS slices strings.
  const parts = [];
  let cursor = 0;
  acc.issues.forEach((issue, i) => {
    if (issue.start < cursor) return; // overlapping issue: listed, not highlighted
    parts.push(text.slice(cursor, issue.start));
    const mark = el("mark", { class: `issue ${issueClass(issue.kind)}`, "data-i": i,
      title: `${ISSUE_LABELS[issue.kind]}${issue.suggestions.length ? ` → ${issue.suggestions.join(", ")}` : ""}` },
      text.slice(issue.start, issue.end));
    mark.addEventListener("click", () => focusIssue(i));
    parts.push(mark);
    cursor = issue.end;
  });
  parts.push(text.slice(cursor));
  ui.written.replaceChildren(...parts);

  const counts = [
    [acc.misspelled, "sp", plural(acc.misspelled, "misspelling")],
    [acc.unknown, "unk", `${acc.unknown} not in dictionary`],
    [acc.mechanics, "mech", plural(acc.mechanics, "other thing to check", "other things to check")],
  ];
  ui.reviewSummary.replaceChildren(...(acc.issues.length
    ? counts.filter(([n]) => n).map(([, cls, label]) =>
        el("span", { class: "count" }, el("span", { class: `swatch ${cls}`, "aria-hidden": "true" }, "abc"), label))
    : [el("span", { class: "count" }, "No issues found. Nice and clean.")]));

  ui.issueList.replaceChildren(...acc.issues.map((issue, i) => {
    const item = el("li", { class: "issue-item", "data-i": i, tabindex: "-1" },
      el("span", { class: `badge ${issueClass(issue.kind)}` }, ISSUE_LABELS[issue.kind]),
      el("span", { class: "issue-text" },
        el(issue.kind === "spelling" ? "s" : "span", { class: "found" }, issue.text),
        ...(issue.suggestions.length
          ? [" → ", el("span", { class: "fix" }, issue.suggestions.join(", "))]
          : [el("span", { class: "muted" }, ` · ${issue.message}`)])),
    );
    if (issue.kind === "spelling" || issue.kind === "unknown") {
      const add = el("button", { class: "btn ghost tiny", type: "button" }, "Add to dictionary");
      add.addEventListener("click", () => addWord(issue.text));
      item.append(add);
    }
    item.addEventListener("pointerenter", () => hotMark(i, true));
    item.addEventListener("pointerleave", () => hotMark(i, false));
    return item;
  }));
}

function focusIssue(i) {
  const item = ui.issueList.querySelector(`[data-i="${i}"]`);
  if (!item) return;
  item.focus({ preventScroll: true });
  item.scrollIntoView({ behavior: "smooth", block: "nearest" });
  item.classList.remove("flash");
  void item.offsetWidth; // restart the animation
  item.classList.add("flash");
}

function hotMark(i, on) {
  ui.written.querySelector(`mark[data-i="${i}"]`)?.classList.toggle("hot", on);
}

// ---------- Personal dictionary ----------

async function loadWords() {
  try {
    state.words = await api("dictionary");
  } catch {
    return;
  }
  ui.dictCount.textContent = state.words.length;
  ui.dictList.replaceChildren(...state.words.map((word) => {
    const remove = el("button", { class: "chip-x", type: "button", "aria-label": `Remove ${word}` }, "✕");
    remove.addEventListener("click", () => removeWord(word));
    return el("li", { class: "dict-chip" }, word, remove);
  }));
}

async function addWord(word) {
  await changeWord(word, "PUT");
}
async function removeWord(word) {
  await changeWord(word, "DELETE");
}
async function changeWord(word, method) {
  try {
    await api(`dictionary/${encodeURIComponent(word)}`, { method });
  } catch (err) {
    showError(err);
    return;
  }
  // Re-score the open session and history against the updated dictionary.
  const refresh = [loadWords(), loadHistory()];
  if (state.session) {
    refresh.push(api(`sessions/${state.session.id}?pause_threshold_ms=${ui.threshold.value}`)
      .then((s) => renderSession(s, { scroll: false }), showError));
  }
  await Promise.all(refresh);
}

// ---------- History ----------

async function loadHistory() {
  let items;
  try {
    items = await api("sessions");
  } catch {
    return;
  }
  ui.history.hidden = items.length === 0;
  ui.historyEmpty.hidden = items.length > 0;
  const fmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  ui.history.tBodies[0].replaceChildren(...items.map((it) => {
    const del = el("button", { class: "icon-btn", type: "button", "aria-label": "Delete session", title: "Delete" }, "✕");
    del.addEventListener("click", async (e) => {
      e.stopPropagation();
      await api(`sessions/${it.id}`, { method: "DELETE" }).catch(showError);
      if (state.session?.id === it.id) {
        state.session = null;
        ui.results.hidden = true;
      }
      loadHistory();
    });
    const row = el("tr", { "data-id": it.id, tabindex: "0" },
      el("td", {}, fmt.format(new Date(it.created_at))),
      el("td", { class: "task-cell" }, it.prompt_text),
      el("td", { class: "num" }, num(it.overall_wpm)),
      el("td", { class: "num" }, num(it.burst_wpm)),
      el("td", { class: "num" }, pct(it.pause_share)),
      el("td", { class: "num" }, it.backspaces_per_100_keys.toFixed(1)),
      el("td", { class: "num" }, it.spelling_accuracy == null ? "–" : pct1(it.spelling_accuracy)),
      el("td", { class: "num" }, del),
    );
    const open = async () => {
      try {
        renderSession(await api(`sessions/${it.id}?pause_threshold_ms=${ui.threshold.value}`));
      } catch (err) {
        showError(err);
      }
    };
    row.addEventListener("click", open);
    row.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    return row;
  }));
  markCurrentHistoryRow();
}

function markCurrentHistoryRow() {
  for (const row of ui.history.tBodies[0].rows) {
    row.classList.toggle("current", Number(row.dataset.id) === state.session?.id);
  }
}

// ---------- DOM helper ----------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  node.append(...children);
  return node;
}

loadTask();
loadHistory();
loadWords();
