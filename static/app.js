// Yoru no Toshokan front end (vanilla JS).
const $ = (id) => document.getElementById(id);
const state = { criteria: [], unmatched: [], page: 1, more: false, skip: [] };
let prefs = { exclude: { normal: [], mature: [] }, hidden: [] };
const layer = () => ($("mature").checked ? "mature" : "normal");

async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function parseAndSearch(text, useLlm) {
  if (!text.trim()) return;
  $("welcome").hidden = true;
  $("status").textContent = useLlm ? "Rewriting with LLM and parsing..." : "Parsing...";
  try {
    const p = await post("/api/parse", { text, use_llm: useLlm });
    state.criteria = p.criteria;
    state.unmatched = p.unmatched;
    state.skip = [];            // a new query brings back every always-exclude
    $("rewritten-row").hidden = !useLlm;
    $("rewritten").value = p.rewritten ?? "";
    $("llm-note").textContent = p.note || "";
    $("report").innerHTML = p.report.map((r) =>
      `<tr><td>${esc(r.phrase)}</td><td>${esc(r.method)}</td><td>${r.score.toFixed(0)}</td><td>${esc(r.got.join(", ") || "-")}</td></tr>`).join("");
    renderChips();
    await search(1);
  } catch (e) {
    $("status").textContent = "Error: " + e.message;
  }
}

function renderChips() {
  $("understood").hidden = false;
  const good = state.criteria.map((c, i) =>
    `<span class="chip ${c.exclude ? "neg" : ""}" title="${esc(c.method)} from '${esc(c.phrase)}'">${esc(c.display)}<button data-i="${i}">×</button></span>`);
  const bad = state.unmatched.map((u, i) =>
    `<span class="chip bad" data-find="${i}" title="not understood - click to look it up in Browse tags">${esc(u)}<button data-u="${i}">×</button></span>`);
  $("chips").innerHTML = good.concat(bad).join("") || "<em>nothing</em>";
  renderAlways();
}

function renderAlways() {
  const list = prefs.exclude[layer()].filter((t) => !state.skip.includes(t.id));
  $("always-row").hidden = !list.length;
  $("always").innerHTML = list.map((t) =>
    `<span class="chip pref" title="from Preferences; × skips it for this search">NOT: ${esc(t.name)}<button data-skip="${esc(t.id)}">×</button></span>`).join("");
}

$("always").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  state.skip.push(b.dataset.skip);
  renderAlways();
  search(1);
});

$("chips").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  const bad = e.target.closest(".chip.bad");
  if (!b && bad) {              // look the unread words up in the tag browser
    lookingUp = state.unmatched[+bad.dataset.find];
    $("tags-panel").open = true;
    tags.open(lookingUp);
    return;
  }
  if (!b) return;
  if (b.dataset.i !== undefined) {
    state.criteria.splice(+b.dataset.i, 1);
    renderChips();
    search(1);                 // removing a criterion re-runs the search
  } else {
    state.unmatched.splice(+b.dataset.u, 1);
    renderChips();
  }
});

// ---------------------------------------------------------------- tag browser
let lookingUp = null;           // an unmatched phrase being looked up; replaced by the tag picked
const tags = mountTagBrowser($("tag-browser"), {
  async search(q) {
    const r = await fetch(`/api/tags?q=${encodeURIComponent(q)}${$("mature").checked ? "&mature=1" : ""}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  },
  onPick(t, exclude) {
    const w = $("welcome"); if (w) w.hidden = true;
    state.criteria = state.criteria.filter((c) => !(c.kind === "tag" && c.value === t.id));   // + then − flips it
    state.criteria.push({ kind: "tag", value: t.id, label: t.name, exclude, phrase: "", method: "tag browser",
                          display: (exclude ? "NOT: " : "") + t.name });
    if (lookingUp !== null) { state.unmatched = state.unmatched.filter((u) => u !== lookingUp); lookingUp = null; }
    renderChips();
    search(1);
  },
});

async function search(page) {
  $("status").textContent = "Searching VNDB...";
  $("more").disabled = true;
  try {
    const r = await post("/api/search", {
      criteria: state.criteria, page, sort: $("sort").value, mode: $("mode").value,
      mature: $("mature").checked, skip_excludes: state.skip,
    });
    state.page = r.page;
    state.more = r.more;
    if (page === 1) $("grid").innerHTML = "";
    r.cards.forEach((c) => $("grid").insertAdjacentHTML("beforeend", card(c)));
    const n = $("grid").children.length;
    $("status").textContent = [...r.notes, n ? `${n} shown${r.more ? ", more available" : ""}` : "Nothing found - try removing a chip."].join(" ");
    $("more").hidden = !r.more;
  } catch (e) {
    $("status").textContent = "Error: " + e.message;
  } finally {
    $("more").disabled = false;
  }
}

function card(c) {
  const blur = c.blur;
  const href = `/vn/${c.id}${$("mature").checked ? "?mature=1" : ""}`;
  const cover = c.cover
    ? `<img src="${esc(c.cover)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : `<div class="placeholder">no cover</div>`;
  const meta = [c.year, c.rating ? `★ ${c.rating.toFixed(2)}` : "unrated", c.votecount ? `${c.votecount} votes` : ""]
    .filter(Boolean).join(" · ");
  const hits = $("mode").value === "any" && c.wanted ? ` · ${c.hits}/${c.wanted} tags` : "";
  return `<div class="card" data-id="${esc(c.id)}" data-title="${esc(c.title)}">
    <button class="hide-btn" title="Not interested: never show this again">✕</button>
    <a class="cover ${blur ? "blur" : ""}" href="${esc(href)}">${cover}</a>
    <div class="info">
      <a href="${esc(href)}">${esc(c.title)}</a> <a class="ext" href="${esc(c.url)}" target="_blank" rel="noopener" title="open on vndb.org">↗</a>
      <div class="meta">${esc(meta + hits)}</div>
      <div class="tags">${c.tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div>
    </div></div>`;
}

// click a blurred cover to reveal it; ✕ hides the VN for good
$("grid").addEventListener("click", async (e) => {
  const hb = e.target.closest(".hide-btn");
  if (hb) {
    const card = hb.closest(".card");
    await prefsAction({ action: "hide", id: card.dataset.id, title: card.dataset.title });
    card.remove();
    return;
  }
  const cov = e.target.closest(".cover.blur");
  if (cov) { e.preventDefault(); cov.classList.remove("blur"); }   // first click reveals, second opens
});

$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  history.replaceState(null, "", "/?q=" + encodeURIComponent($("q").value));
  parseAndSearch($("q").value, $("llm").checked);
});
// editing the rewritten line re-parses it directly (no second LLM pass)
$("rewritten").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); parseAndSearch($("rewritten").value, false).then(() => { $("rewritten-row").hidden = false; }); }
});
["sort", "mode", "mature"].forEach((id) => $(id).addEventListener("change", () => { if (state.criteria.length || $("grid").children.length) search(1); }));
$("more").addEventListener("click", () => search(state.page + 1));

// Mature toggle is remembered between visits
$("mature").checked = localStorage.getItem("mature") === "1";
$("mature").addEventListener("change", () => { localStorage.setItem("mature", $("mature").checked ? "1" : "0"); renderAlways(); });

// ---------------------------------------------------------------- preferences
function renderPrefs() {
  for (const l of ["normal", "mature"]) {
    $("ex-" + l).innerHTML = prefs.exclude[l].map((t) =>
      `<span class="chip neg">${esc(t.name)}<button data-l="${l}" data-id="${esc(t.id)}">×</button></span>`).join("") || "<em>none</em>";
  }
  $("hidden-list").innerHTML = prefs.hidden.map((h) =>
    `<span class="chip pref"><a href="/vn/${esc(h.id)}">${esc(h.title)}</a><button data-unhide="${esc(h.id)}">×</button></span>`).join("") || "<em>none</em>";
  if ($("understood").hidden === false) renderAlways();
}

async function prefsAction(body) {
  try {
    prefs = await post("/api/prefs", body);
    $("prefs-msg").textContent = "";
    renderPrefs();
    return true;
  } catch (e) {
    $("prefs-msg").textContent = e.message;
    return false;
  }
}

document.querySelectorAll(".padd").forEach((f) => f.addEventListener("submit", async (e) => {
  e.preventDefault();
  const inp = f.querySelector("input");
  if (inp.value.trim() && await prefsAction({ action: "exclude", layer: f.dataset.layer, name: inp.value })) inp.value = "";
}));
$("prefs-panel").addEventListener("click", (e) => {
  const b = e.target.closest(".plist button");
  if (!b) return;
  if (b.dataset.unhide) prefsAction({ action: "unhide", id: b.dataset.unhide });
  else prefsAction({ action: "unexclude", layer: b.dataset.l, id: b.dataset.id });
});
fetch("/api/prefs").then((r) => r.json()).then((p) => { prefs = p; renderPrefs(); });

// keep the search when opening a detail page, so Back returns to the same grid and scroll
window.addEventListener("pagehide", () => {
  sessionStorage.setItem("search", JSON.stringify({ url: location.search,
    q: $("q").value, rewritten: $("rewritten").value, rewrittenShown: !$("rewritten-row").hidden,
    note: $("llm-note").textContent, report: $("report").innerHTML, state,
    grid: $("grid").innerHTML, status: $("status").textContent, more: !$("more").hidden,
    sort: $("sort").value, mode: $("mode").value, scroll: window.scrollY,
  }));
});
(function restore() {
  const saved = JSON.parse(sessionStorage.getItem("search") || "null");
  const urlQ = new URLSearchParams(location.search).get("q");
  if (urlQ && (!saved || saved.q !== urlQ)) {   // /?q=... runs that search (bookmarkable)
    $("q").value = urlQ;
    parseAndSearch(urlQ, $("llm").checked);
    return;
  }
  if (!saved || !saved.grid) return;
  $("welcome").hidden = true;
  Object.assign(state, saved.state);
  $("q").value = saved.q; $("sort").value = saved.sort; $("mode").value = saved.mode;
  $("rewritten").value = saved.rewritten; $("rewritten-row").hidden = !saved.rewrittenShown;
  $("llm-note").textContent = saved.note; $("report").innerHTML = saved.report;
  renderChips();
  $("grid").innerHTML = saved.grid; $("status").textContent = saved.status; $("more").hidden = !saved.more;
  requestAnimationFrame(() => window.scrollTo(0, saved.scroll));
})();

document.querySelectorAll(".try").forEach((b) => b.addEventListener("click", () => {
  $("q").value = b.textContent;
  parseAndSearch(b.textContent, $("llm").checked);
}));
