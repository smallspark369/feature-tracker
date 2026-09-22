/* Community feature tracker — Telegram Mini App frontend. */
"use strict";

const tg = window.Telegram && window.Telegram.WebApp;
const inTg = !!(tg && tg.initData);
if (inTg) {
  document.body.classList.add("in-tg");
  tg.ready();
  tg.expand();
  try {
    tg.setHeaderColor("#0c0d0a");
    tg.setBackgroundColor("#0c0d0a");
    tg.MainButton.setParams({ color: "#8de3be", text_color: "#0c0d0a" });
  } catch (e) { /* older clients */ }
}

const S = {
  me: null,
  items: [],
  tab: "all",          // all | idea | bug | done
  view: "list",        // list | submit | detail
  detail: null,        // full submission object
  triage: {},          // pending admin changes {status, priority}
  files: [],           // File objects staged for submission
  submitting: false,
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

/* ---------- API ---------- */

async function api(path, opts = {}) {
  opts.headers = Object.assign({}, opts.headers, {
    Authorization: "tma " + (inTg ? tg.initData : ""),
  });
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ---------- helpers ---------- */

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.hidden = true; }, 2200);
}

function haptic(kind) {
  if (inTg && tg.HapticFeedback) {
    try { tg.HapticFeedback.impactOccurred(kind || "light"); } catch (e) { /* ignore */ }
  }
}

function timeAgo(iso) {
  const then = new Date(iso.replace(" ", "T") + "Z").getTime();
  const s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 3600) return Math.max(1, Math.floor(s / 60)) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  if (s < 86400 * 30) return Math.floor(s / 86400) + "d";
  return Math.floor(s / (86400 * 30)) + "mo";
}

const STATUS_LABEL = {
  open: "Open", planned: "Planned", in_progress: "In progress",
  completed: "Completed", declined: "Declined",
};
const PRIORITIES = ["unsorted", "low", "medium", "high", "critical"];
const STATUSES = ["open", "planned", "in_progress", "completed", "declined"];

/* ---------- views ---------- */

function show(view) {
  S.view = view;
  $("#view-list").hidden = view !== "list";
  $("#view-submit").hidden = view !== "submit";
  $("#view-detail").hidden = view !== "detail";
  window.scrollTo(0, 0);
  syncChrome();
}

function goBack() {
  if (S.view === "list") return;
  S.detail = null;
  S.triage = {};
  show("list");
}

/* Telegram native Back/Main buttons; in-page fallbacks cover plain browsers. */
function syncChrome() {
  if (!inTg) {
    const fb = $("#fallback-submit");
    if (fb) fb.disabled = S.submitting;
    return;
  }
  if (S.view === "list") tg.BackButton.hide(); else tg.BackButton.show();

  const mb = tg.MainButton;
  if (S.view === "list") {
    mb.setParams({ text: "New request", is_visible: true, is_active: true });
  } else if (S.view === "submit") {
    mb.setParams({ text: S.submitting ? "Submitting…" : "Submit", is_visible: true, is_active: !S.submitting });
  } else if (S.view === "detail") {
    const dirty = Object.keys(S.triage).length > 0;
    if (S.me && S.me.is_admin && dirty) {
      mb.setParams({ text: "Save changes", is_visible: true, is_active: true });
    } else {
      mb.hide();
    }
  }
}

function mainAction() {
  if (S.view === "list") openSubmit();
  else if (S.view === "submit") submitForm();
  else if (S.view === "detail") saveTriage();
}

if (inTg) {
  tg.BackButton.onClick(goBack);
  tg.MainButton.onClick(mainAction);
}

/* ---------- list ---------- */

async function refresh() {
  try {
    S.items = await api("/api/submissions");
    renderList();
  } catch (e) {
    renderError(e.message);
  }
}

function filtered() {
  const active = (s) => ["open", "planned", "in_progress"].includes(s.status);
  if (S.tab === "done") return S.items.filter((s) => !active(s));
  let out = S.items.filter(active);
  if (S.tab === "idea" || S.tab === "bug") out = out.filter((s) => s.kind === S.tab);
  return out;
}

function renderError(msg) {
  const list = $("#list");
  list.replaceChildren();
  const box = el("div", "empty");
  box.append(el("b", null, "Couldn't load the board. "), document.createElement("br"), el("span", null, msg));
  list.append(box);
}

function renderList() {
  const list = $("#list");
  list.replaceChildren();
  const items = filtered();

  if (!items.length) {
    const box = el("div", "empty");
    if (S.tab === "done") {
      box.append(el("span", null, "Nothing has shipped yet — it will show up here."));
    } else {
      box.append(el("b", null, "Nothing here yet."), document.createElement("br"),
        el("span", null, "File the first " + (S.tab === "bug" ? "bug report" : "idea") + "."));
    }
    list.append(box);
    return;
  }

  const byVotes = (a, b) => b.votes - a.votes || b.id - a.id;

  if (S.tab === "done") {
    items.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
    items.forEach((s) => list.append(card(s)));
    return;
  }

  const groups = [
    ["in_progress", "In progress"],
    ["planned", "Planned"],
    ["open", "Open"],
  ];
  for (const [status, label] of groups) {
    const rows = items.filter((s) => s.status === status).sort(byVotes);
    if (!rows.length) continue;
    list.append(el("div", "section-label sl-" + status, label));
    rows.forEach((s) => list.append(card(s)));
  }
}

function card(s) {
  const c = el("article", "card st-" + s.status);
  c.append(voteButton(s));

  const body = el("div", "body");
  const h = el("h3", null, s.title);
  body.append(h);

  const meta = el("div", "meta");
  if (s.kind === "bug") meta.append(el("span", "tag-bug", "bug"));
  meta.append(el("span", null, "#" + s.id));
  meta.append(el("span", "sep"));
  meta.append(el("span", null, s.submitter_name));
  meta.append(el("span", "sep"));
  meta.append(el("span", null, timeAgo(s.created_at)));
  if (s.attachment_count > 0) {
    meta.append(el("span", "sep"));
    meta.append(el("span", null, "📎" + s.attachment_count));
  }
  if (S.tab === "done") {
    meta.append(el("span", "sep"));
    meta.append(el("span", "status-word st-" + s.status, STATUS_LABEL[s.status]));
  }
  if (S.me && S.me.is_admin && s.status !== "completed" && s.status !== "declined") {
    meta.append(el("span", "sep"));
    meta.append(el("span", "prio prio-" + s.priority, s.priority));
  }
  body.append(meta);
  c.append(body);

  c.addEventListener("click", () => openDetail(s.id));
  return c;
}

function voteButton(s) {
  const b = el("button", "vote" + (s.my_vote ? " voted" : ""));
  b.type = "button";
  b.setAttribute("aria-label", "Vote");
  b.append(el("span", "tri", "▲"), el("span", "count", String(s.votes)));
  b.addEventListener("click", async (ev) => {
    ev.stopPropagation();
    haptic("light");
    // optimistic flip
    s.my_vote = !s.my_vote;
    s.votes += s.my_vote ? 1 : -1;
    b.classList.toggle("voted", s.my_vote);
    b.querySelector(".count").textContent = String(s.votes);
    try {
      const r = await api(`/api/submissions/${s.id}/vote`, { method: "POST" });
      s.votes = r.votes; s.my_vote = r.my_vote;
      b.classList.toggle("voted", s.my_vote);
      b.querySelector(".count").textContent = String(s.votes);
    } catch (e) {
      toast(e.message);
      refresh();
    }
  });
  return b;
}

/* ---------- detail ---------- */

async function openDetail(id) {
  try {
    S.detail = await api(`/api/submissions/${id}`);
  } catch (e) {
    toast(e.message);
    return;
  }
  S.triage = {};
  renderDetail();
  show("detail");
}

function renderDetail() {
  const s = S.detail;
  $("#d-eyebrow").textContent = (s.kind === "bug" ? "Bug" : "Idea") + " #" + s.id;

  const box = $("#detail");
  box.replaceChildren();

  box.append(el("h1", null, s.title));

  const meta = el("div", "meta");
  meta.append(el("span", "status-word st-" + s.status, STATUS_LABEL[s.status]));
  meta.append(el("span", "sep"));
  meta.append(el("span", null, s.submitter_name));
  meta.append(el("span", "sep"));
  meta.append(el("span", null, timeAgo(s.created_at) + " ago"));
  if (S.me && S.me.is_admin && s.priority !== "unsorted") {
    meta.append(el("span", "sep"));
    meta.append(el("span", "prio prio-" + s.priority, s.priority + " priority"));
  }
  box.append(meta);

  box.append(el("p", "desc", s.description));

  if (s.attachments && s.attachments.length) {
    const grid = el("div", "shots");
    for (const a of s.attachments) {
      const img = document.createElement("img");
      img.src = "/uploads/" + a.filename;
      img.loading = "lazy";
      img.alt = a.original_name || "Screenshot";
      img.addEventListener("click", () => openLightbox(img.src));
      grid.append(img);
    }
    box.append(grid);
  }

  const voteRow = el("div", "detail-vote");
  voteRow.append(voteButton(s), el("span", "hint", s.votes === 1 ? "1 vote" : s.votes + " votes"));
  box.append(voteRow);

  if (S.me && S.me.is_admin) box.append(triagePanel(s));
}

function triagePanel(s) {
  const wrap = el("div", "triage");

  const mkChips = (title, values, current, key, labelFn) => {
    wrap.append(el("h4", null, title));
    const row = el("div", "chips");
    for (const v of values) {
      const chip = el("button", "chip" + (v === current ? " selected" : ""), labelFn(v));
      chip.type = "button";
      chip.addEventListener("click", () => {
        if (v === (S.triage[key] !== undefined ? S.triage[key] : s[key])) return;
        S.triage[key] = v;
        if (v === s[key]) delete S.triage[key];
        row.querySelectorAll(".chip").forEach((c) => c.classList.remove("selected"));
        chip.classList.add("selected");
        syncChrome();
        renderFallbackSave(wrap);
      });
      row.append(chip);
    }
    wrap.append(row);
  };

  mkChips("Status", STATUSES, s.status, "status", (v) => STATUS_LABEL[v]);
  mkChips("Priority", PRIORITIES, s.priority, "priority", (v) => v);
  renderFallbackSave(wrap);
  return wrap;
}

function renderFallbackSave(wrap) {
  if (inTg) return;
  let btn = wrap.querySelector(".save-fallback");
  const dirty = Object.keys(S.triage).length > 0;
  if (dirty && !btn) {
    btn = el("button", "primary-btn save-fallback", "Save changes");
    btn.type = "button";
    btn.style.marginTop = "14px";
    btn.style.width = "100%";
    btn.addEventListener("click", saveTriage);
    wrap.append(btn);
  } else if (!dirty && btn) {
    btn.remove();
  }
}

async function saveTriage() {
  if (!S.detail || !Object.keys(S.triage).length) return;
  try {
    const r = await api(`/api/submissions/${S.detail.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(S.triage),
    });
    S.triage = {};
    S.detail = r;
    renderDetail();
    syncChrome();
    haptic("medium");
    toast(r.announced ? "Saved — announced in the group chat" : "Saved");
    refresh();
  } catch (e) {
    toast(e.message);
  }
}

/* ---------- submit ---------- */

function openSubmit() {
  S.files = [];
  $("#submit-form").reset();
  document.querySelectorAll(".kind").forEach((b) => b.classList.toggle("active", b.dataset.kind === "idea"));
  renderPreviews();
  show("submit");
}

function currentKind() {
  const active = document.querySelector(".kind.active");
  return active ? active.dataset.kind : "idea";
}

function renderPreviews() {
  const wrap = $("#previews");
  wrap.replaceChildren();
  S.files.forEach((f, i) => {
    const t = el("div", "thumb");
    const img = document.createElement("img");
    img.src = URL.createObjectURL(f);
    img.alt = f.name;
    const rm = el("button", null, "×");
    rm.type = "button";
    rm.setAttribute("aria-label", "Remove " + f.name);
    rm.addEventListener("click", () => { S.files.splice(i, 1); renderPreviews(); });
    t.append(img, rm);
    wrap.append(t);
  });
}

async function submitForm() {
  if (S.submitting) return;
  const title = $("#f-title").value.trim();
  const desc = $("#f-desc").value.trim();
  if (title.length < 3) { toast("Give it a title (at least 3 characters)."); return; }

  S.submitting = true;
  syncChrome();

  const fd = new FormData();
  fd.append("kind", currentKind());
  fd.append("title", title);
  fd.append("description", desc);
  for (const f of S.files) fd.append("files", f);

  try {
    await api("/api/submissions", { method: "POST", body: fd });
    haptic("medium");
    toast("Submitted");
    S.files = [];
    show("list");
    refresh();
  } catch (e) {
    toast(e.message);
  } finally {
    S.submitting = false;
    syncChrome();
  }
}

/* ---------- wiring ---------- */

$("#tabs").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".tab");
  if (!btn) return;
  S.tab = btn.dataset.tab;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === btn));
  renderList();
});

document.querySelectorAll("[data-back]").forEach((b) => b.addEventListener("click", goBack));
$("#fallback-new").addEventListener("click", openSubmit);

$("#submit-form").addEventListener("submit", (ev) => { ev.preventDefault(); submitForm(); });

document.querySelectorAll(".kind").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".kind").forEach((x) => x.classList.toggle("active", x === b));
  })
);

$("#f-files").addEventListener("change", (ev) => {
  for (const f of ev.target.files) {
    if (S.files.length >= 4) { toast("Up to 4 screenshots."); break; }
    if (!f.type.startsWith("image/")) continue;
    S.files.push(f);
  }
  ev.target.value = "";
  renderPreviews();
});

function openLightbox(src) {
  const lb = $("#lightbox");
  lb.querySelector("img").src = src;
  lb.hidden = false;
}
$("#lightbox").addEventListener("click", () => { $("#lightbox").hidden = true; });

/* ---------- boot ---------- */

(async function boot() {
  try {
    S.me = await api("/api/me");
  } catch (e) {
    renderError(e.message);
    return;
  }
  syncChrome();
  refresh();
})();
