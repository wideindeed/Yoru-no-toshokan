// Yoru no Toshokan front end (vanilla JS).
const $ = (id) => document.getElementById(id);
const state = { criteria: [], unmatched: [], page: 1, more: false, skip: [], source: "vn" };
let prefs = { exclude: { normal: [], mature: [], ln_normal: [], ln_mature: [] }, hidden: [] };
let searchBy = "describe";
const isLN = () => state.source === "ln";
const layerOf = (l) => (isLN() ? "ln_" : "") + l;              // prefs layers: normal, mature, ln_normal, ln_mature
const layer = () => layerOf($("mature").checked ? "mature" : "normal");

// ---------------------------------------------------------------- source: VN or light novel
const SRC = {
  vn: { api: "VNDB", tagline: "visual novels, after hours",
        placeholder: $("q").placeholder, titleHint: "a title, e.g. Ever17 or Steins;Gate",
        tries: ["fantasy setting, female lead, multiple endings", "a slice of life story with one ending, in english",
                "vampires, made in RPG Maker, no horror, after 2015"],
        exNormal: "tag, e.g. Otome Game", exMature: "tag, e.g. Rape" },
  ln: { api: "AniList", tagline: "light novels, after hours",
        placeholder: "e.g. isekai villainess, slow life, no harem, after 2015",
        titleHint: "a title, e.g. Spice and Wolf or Monogatari",
        tries: ["isekai villainess, female lead", "time loop mystery, highly rated", "academy romance, no harem, after 2015"],
        exNormal: "tag, e.g. Female Harem", exMature: "tag, e.g. Rape" },
};
function applySource(src) {
  state.source = src === "ln" ? "ln" : "vn";
  const S = SRC[state.source];
  document.documentElement.dataset.src = state.source;
  localStorage.setItem("src", state.source);
  document.querySelectorAll(".src-switch button").forEach((b) => b.classList.toggle("on", b.dataset.src === state.source));
  document.querySelector(".tagline").textContent = S.tagline;
  const ji = document.querySelector(".chochin .ji");
  if (ji) ji.textContent = isLN() ? "栞" : "灯";            // lantern (light) / bookmark
  document.querySelectorAll(".try").forEach((b, i) => { b.textContent = S.tries[i] ?? b.textContent; });
  document.querySelector('.padd[data-layer="normal"] input').placeholder = S.exNormal;
  document.querySelector('.padd[data-layer="mature"] input').placeholder = S.exMature;
  document.querySelector('#sort option[value="votecount"]').textContent = isLN() ? "popularity" : "votecount";
  setBy(searchBy);
  renderPrefs();
}

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
    const p = await post("/api/parse", { text, use_llm: useLlm, source: state.source });
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
    const r = await fetch(`/api/tags?q=${encodeURIComponent(q)}&source=${state.source}${$("mature").checked ? "&mature=1" : ""}`);
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
  $("status").textContent = `Searching ${SRC[state.source].api}...`;
  $("more").disabled = true;
  try {
    const r = await post("/api/search", {
      criteria: state.criteria, page, sort: $("sort").value, mode: $("mode").value,
      mature: $("mature").checked, skip_excludes: state.skip, source: state.source,
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
  const ln = c.id.startsWith("l");
  const href = `/${ln ? "ln" : "vn"}/${c.id}${$("mature").checked ? "?mature=1" : ""}`;
  const cover = c.cover
    ? `<img src="${esc(c.cover)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : `<div class="placeholder">no cover</div>`;
  const meta = [c.year, c.volumes ? `${c.volumes} vol.` : "",
                c.rating ? `★ ${c.rating.toFixed(ln ? 1 : 2)}` : "unrated", c.votecount ? `${c.votecount} ${ln ? "users" : "votes"}` : ""]
    .filter(Boolean).join(" · ");
  const hits = $("mode").value === "any" && c.wanted ? ` · ${c.hits}/${c.wanted} tags` : "";
  return `<div class="card" data-id="${esc(c.id)}" data-title="${esc(c.title)}">
    <button class="hide-btn" title="Not interested: never show this again">✕</button>
    <a class="cover ${blur ? "blur" : ""}" href="${esc(href)}">${cover}</a>
    <div class="info">
      <a href="${esc(href)}">${esc(c.title)}</a> <a class="ext" href="${esc(c.url)}" target="_blank" rel="noopener" title="open on ${ln ? "anilist.co" : "vndb.org"}">↗</a>
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


// ---------------------------------------------------------------- title search
function titleSearch(t) {
  t = t.trim();
  if (!t) return;
  $("welcome").hidden = true;
  $("report").innerHTML = "";
  Object.assign(state, { criteria: [{ kind: "title", value: t, label: "Title: " + t, exclude: false,
                                      phrase: t, method: "title search", display: "Title: " + t }],
                         unmatched: [], skip: [] });
  renderChips();
  search(1);
}
// one bar, two ways to search: "describe" (the parser) or "title" (VNDB title search)
function setBy(by) {
  searchBy = by;
  document.querySelectorAll("#search-form .by button").forEach((b) => b.classList.toggle("on", b.dataset.by === by));
  $("q").placeholder = by === "title" ? SRC[state.source].titleHint : SRC[state.source].placeholder;
}
document.querySelectorAll("#search-form .by button").forEach((b) => b.addEventListener("click", () => { setBy(b.dataset.by); $("q").focus(); }));

$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("q").value.trim();
  pushUrl(q);
  if (searchBy === "title") titleSearch(q);
  else parseAndSearch(q, $("llm").checked);
});
function pushUrl(q) {
  const u = new URLSearchParams();
  if (isLN()) u.set("src", "ln");
  if (q) u.set(searchBy === "title" ? "title" : "q", q);
  history.replaceState(null, "", "/" + (u.toString() ? "?" + u : ""));
}
// switching VN <-> light novel re-runs the current search against the other source
document.querySelectorAll(".src-switch button").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.src === state.source) return;
  applySource(b.dataset.src);
  const q = $("q").value.trim();
  pushUrl(q);
  Object.assign(state, { criteria: [], unmatched: [], skip: [] });
  $("grid").innerHTML = ""; $("more").hidden = true; $("status").textContent = "";
  if (!q) { $("understood").hidden = true; $("welcome").hidden = false; return; }
  if (searchBy === "title") titleSearch(q);
  else parseAndSearch(q, $("llm").checked);
}));
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
    $("ex-" + l).innerHTML = (prefs.exclude[layerOf(l)] || []).map((t) =>
      `<span class="chip neg">${esc(t.name)}<button data-l="${layerOf(l)}" data-id="${esc(t.id)}">×</button></span>`).join("") || "<em>none</em>";
  }
  const mine = prefs.hidden.filter((h) => h.id.startsWith(isLN() ? "l" : "v"));
  $("hidden-list").innerHTML = mine.map((h) =>
    `<span class="chip pref"><a href="/${isLN() ? "ln" : "vn"}/${esc(h.id)}">${esc(h.title)}</a><button data-unhide="${esc(h.id)}">×</button></span>`).join("") || "<em>none</em>";
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
  if (inp.value.trim() && await prefsAction({ action: "exclude", layer: layerOf(f.dataset.layer), name: inp.value,
                                               source: state.source })) inp.value = "";
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
    q: $("q").value, by: searchBy, rewritten: $("rewritten").value, rewrittenShown: !$("rewritten-row").hidden,
    note: $("llm-note").textContent, report: $("report").innerHTML, state,
    grid: $("grid").innerHTML, status: $("status").textContent, more: !$("more").hidden,
    sort: $("sort").value, mode: $("mode").value, scroll: window.scrollY,
  }));
});
(function restore() {
  let saved = JSON.parse(sessionStorage.getItem("search") || "null");
  const params = new URLSearchParams(location.search);
  const urlQ = params.get("q"), urlT = params.get("title");
  applySource(params.get("src") || (urlQ || urlT ? "vn" : localStorage.getItem("src")) || "vn");
  if (saved && (saved.state?.source || "vn") !== state.source) saved = null;   // a grid from the other source
  if (urlT && (!saved || saved.by !== "title" || saved.q !== urlT)) { setBy("title"); $("q").value = urlT; titleSearch(urlT); return; }
  if (urlQ && (!saved || saved.q !== urlQ)) {   // /?q=... runs that search (bookmarkable)
    $("q").value = urlQ;
    parseAndSearch(urlQ, $("llm").checked);
    return;
  }
  if (!saved || !saved.grid) return;
  $("welcome").hidden = true;
  Object.assign(state, saved.state);
  setBy(saved.by || "describe"); $("q").value = saved.q; $("sort").value = saved.sort; $("mode").value = saved.mode;
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
