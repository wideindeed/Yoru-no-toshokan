// Yoru no Toshokan, browser-only version. The parser runs in Pyodide (web.py);
// this file talks to VNDB directly and keeps preferences in localStorage.
const $ = (id) => document.getElementById(id);
const API = "https://api.vndb.org/kana/vn";
const ANILIST = "https://graphql.anilist.co";
const DESKTOP_URL = "https://github.com/wideindeed/Yoru-no-toshokan#getting-started";
const state = { criteria: [], unmatched: [], notes: [], page: 1, more: false, skip: [], source: "vn" };
const isLN = () => state.source === "ln";
const fn = (name) => (isLN() ? "ln_" : "") + name;     // web.py: parse / ln_parse, tags / ln_tags, ...

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// toggle-button groups: .on for the look, aria-pressed for screen readers
function pressed(sel, isOn) {
  document.querySelectorAll(sel).forEach((b) => { b.classList.toggle("on", isOn(b)); b.setAttribute("aria-pressed", isOn(b)); });
}

// "Not interested" acts at once; a short message offers Undo instead of asking first
let toastTimer;
function hideWithUndo(card, unhide) {
  const grid = card.parentNode, next = card.nextElementSibling, t = $("toast");
  const away = () => {     // the message goes; keep keyboard focus on the grid
    if (t.contains(document.activeElement)) (next?.isConnected ? next.querySelector(".info a") : grid).focus();
    t.innerHTML = "";
  };
  card.remove();
  t.innerHTML = `Hidden: ${esc(card.dataset.title)} <button type="button">Undo</button>`;
  t.querySelector("button").onclick = () => {
    clearTimeout(toastTimer);
    unhide();
    if (!next || next.parentNode === grid) { grid.insertBefore(card, next); card.querySelector(".info a").focus(); }
    t.innerHTML = "";
  };
  t.querySelector("button").focus();
  clearTimeout(toastTimer);
  toastTimer = setTimeout(away, 7000);
}

// nothing found with every tag required: offer to rank by any tag instead
const TRY_ANY = ' <button type="button" id="try-any">Match any tag instead</button>';
$("status").addEventListener("click", (e) => {
  if (e.target.id === "try-any") { $("mode").value = "any"; search(1); }
});
// the sticky header must not cover what has keyboard focus
const head = document.querySelector("header");
new ResizeObserver(() => {
  document.documentElement.style.scrollPaddingTop = getComputedStyle(head).position === "sticky" ? head.offsetHeight + 12 + "px" : "";
}).observe(head);

// ---------------------------------------------------------------- Python
const py = (async () => {
  const p = await loadPyodide();
  await p.loadPackage("pyyaml");
  const zip = await fetch("py.zip");
  if (!zip.ok) throw new Error("could not load py.zip");
  p.unpackArchive(await zip.arrayBuffer(), "zip", { extractDir: "/app" });
  p.runPython('import sys; sys.path.insert(0, "/app")');
  return p.pyimport("web");
})();
let ready = false;
py.then(() => { ready = true; });
const call = async (fn, ...args) => JSON.parse((await py)[fn](...args));

// ---------------------------------------------------------------- VNDB
const cache = new Map();
async function vndb(body) {
  const key = JSON.stringify(body);
  if (cache.has(key)) return cache.get(key);
  const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body: key });
  if (r.status === 429) throw new Error("VNDB is busy right now (too many requests). Try again in a minute.");
  if (!r.ok) throw new Error(`VNDB API error ${r.status}: ${(await r.text()).slice(0, 200)}`);
  const data = await r.json();
  cache.set(key, data);
  return data;
}

// ---------------------------------------------------------------- AniList (light novels)
async function anilist(query) {
  if (cache.has(query)) return cache.get(query);
  const r = await fetch(ANILIST, { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" },
                                   body: JSON.stringify({ query }) });
  if (r.status === 429) throw new Error("AniList is busy right now (too many requests). Try again in a minute.");
  const out = await r.json().catch(() => ({}));
  if (!r.ok || out.errors) throw new Error(`AniList API error ${r.status}: ${(out.errors || []).map((e) => e.message).join("; ").slice(0, 200)}`);
  cache.set(query, out.data);
  return out.data;
}

// ---------------------------------------------------------------- source: VN or light novel
const SRC = {
  vn: { api: "VNDB", tagline: "visual novels, after hours", placeholder: $("q").placeholder,
        titleHint: "a title, e.g. Ever17 or Steins;Gate", exHint: "tag, e.g. Gore",
        tries: ["fantasy setting, female lead, multiple endings", "a slice of life story with one ending, in english",
                "vampires, made in RPG Maker, no horror, after 2015"] },
  ln: { api: "AniList", tagline: "light novels, after hours", placeholder: "e.g. isekai villainess, slow life, no harem, after 2015",
        titleHint: "a title, e.g. Spice and Wolf or Monogatari", exHint: "tag, e.g. Female Harem",
        tries: ["isekai villainess, female lead", "time loop mystery, highly rated", "academy romance, no harem, after 2015"] },
};
let searchBy = "describe";
function applySource(src) {
  state.source = src === "ln" ? "ln" : "vn";
  const S = SRC[state.source];
  document.documentElement.dataset.src = state.source;
  localStorage.setItem("src", state.source);
  pressed(".src-switch button", (b) => b.dataset.src === state.source);
  document.querySelector(".tagline").textContent = S.tagline;
  const ji = document.querySelector(".chochin .ji");
  if (ji) ji.textContent = isLN() ? "栞" : "灯";
  document.querySelectorAll(".try").forEach((b, i) => { b.textContent = S.tries[i] ?? b.textContent; });
  document.querySelector(".padd input").placeholder = S.exHint;
  document.querySelector('#sort option[value="votecount"]').textContent = isLN() ? "popularity" : "votecount";
  setBy(searchBy);
  renderPrefs();
  renderShelves();
}

// ---------------------------------------------------------------- preferences (this browser only)
const MAX_EX = 50, MAX_HIDDEN = 300;
let prefs = { exclude: [], ln_exclude: [], hidden: {} };   // exclude: [{id, name}] per source, hidden: {id: title}
try { Object.assign(prefs, JSON.parse(localStorage.getItem("prefs") || "{}")); } catch { /* fresh start */ }
prefs.ln_exclude ??= [];
const savePrefs = () => localStorage.setItem("prefs", JSON.stringify(prefs));
const exKey = () => (isLN() ? "ln_exclude" : "exclude");

function renderPrefs() {
  $("ex-list").innerHTML = prefs[exKey()].map((t) =>
    `<span class="chip neg">${esc(t.name)}<button data-id="${esc(t.id)}" aria-label="Stop excluding ${esc(t.name)}">×</button></span>`).join("") || "<em>none</em>";
  $("hidden-list").innerHTML = Object.entries(prefs.hidden).filter(([id]) => id.startsWith(isLN() ? "l" : "v")).map(([id, title]) =>
    `<span class="chip pref"><a href="#${esc(id)}">${esc(title)}</a><button data-unhide="${esc(id)}" aria-label="Show ${esc(title)} again">×</button></span>`).join("") || "<em>none</em>";
  if (!$("understood").hidden) renderAlways();
}

document.querySelector(".padd").addEventListener("submit", async (e) => {
  e.preventDefault();
  const inp = e.target.querySelector("input"), name = inp.value.trim();
  if (!name) return;
  $("prefs-msg").textContent = "";
  const tags = await call(fn("resolve"), name), ex = prefs[exKey()];
  if (!tags.length) { $("prefs-msg").textContent = `No ${SRC[state.source].api} tag matches "${name}".`; return; }
  for (const t of tags) if (!ex.some((x) => x.id === t.id)) ex.push(t);
  if (ex.length > MAX_EX) { ex.length = MAX_EX; $("prefs-msg").textContent = `At most ${MAX_EX} tags.`; }
  savePrefs(); renderPrefs(); inp.value = "";
});
$("prefs-panel").addEventListener("click", (e) => {
  const b = e.target.closest(".plist button");
  if (!b) return;
  if (b.dataset.unhide) delete prefs.hidden[b.dataset.unhide];
  else prefs[exKey()] = prefs[exKey()].filter((t) => t.id !== b.dataset.id);
  savePrefs(); renderPrefs();
});

// ---------------------------------------------------------------- search
async function parseAndSearch(text) {
  if (!text.trim()) return;
  $("welcome").hidden = true;
  $("status").textContent = ready ? "Parsing..." : "Loading the search engine (the first visit takes a few seconds)...";
  try {
    const p = await call(fn("parse"), text);
    Object.assign(state, { criteria: p.criteria, unmatched: p.unmatched, roles: p.unmatched_role || {},
                           notes: p.notes, skip: [] });
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
    `<span class="chip ${c.exclude ? "neg" : ""}" title="${esc(c.method)} from '${esc(c.phrase)}'">${esc(c.display)}<button data-i="${i}" aria-label="Remove ${esc(c.display)}">×</button></span>`);
  const bad = state.unmatched.map((u, i) =>
    `<span class="chip bad"><button class="find" data-find="${i}" title="not understood - click to look it up in Browse tags">${esc(u)}</button><button data-u="${i}" aria-label="Remove ${esc(u)}">×</button></span>`);
  $("chips").innerHTML = good.concat(bad).join("") || "<em>nothing</em>";
  renderAlways();
}

function renderAlways() {
  const list = prefs[exKey()].filter((t) => !state.skip.includes(t.id));
  $("always-row").hidden = !list.length;
  $("always").innerHTML = list.map((t) =>
    `<span class="chip pref" title="from Preferences; × skips it for this search">NOT: ${esc(t.name)}<button data-skip="${esc(t.id)}" aria-label="Skip ${esc(t.name)} for this search">×</button></span>`).join("");
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
  if (b?.dataset.find !== undefined) {   // look the unread words up in the tag browser
    lookingUp = state.unmatched[+b.dataset.find];
    $("tags-panel").open = true;
    tags.open(lookingUp);
    return;
  }
  if (!b) return;
  if (b.dataset.i !== undefined) { state.criteria.splice(+b.dataset.i, 1); renderChips(); search(1); }
  else { state.unmatched.splice(+b.dataset.u, 1); renderChips(); }
});

// ---------------------------------------------------------------- tag browser
let lookingUp = null;           // an unmatched phrase being looked up; replaced by the tag picked
const tags = mountTagBrowser($("tag-browser"), {
  search: (q) => call(fn("tags"), q),
  related: (q) => relatedTags(q, { base: "vectors/", src: state.source, ero: false,   // all ages
                                   role: state.roles?.[q] }),
  onPick(t, exclude) {
    $("welcome").hidden = true;
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
    const crits = JSON.stringify(state.criteria), mode = $("mode").value, sort = $("sort").value;
    const excludes = JSON.stringify(prefs[exKey()].filter((t) => !state.skip.includes(t.id)));
    const hidden = JSON.stringify(Object.keys(prefs.hidden));
    let cards, more, extra = [];
    if (isLN()) {
      const q = await call("ln_query", crits, sort, mode, page, excludes, hidden);
      const out = await call("ln_cards", JSON.stringify(await anilist(q.query)), crits, mode, sort);
      ({ cards, more } = out);
      extra = q.notes;
    } else {
      const data = await vndb(await call("query", crits, sort, mode, page, excludes, hidden));
      cards = await call("cards", JSON.stringify(data.results || []), crits, mode);
      more = !!data.more;
    }
    state.page = page;
    state.more = more;
    if (page === 1) $("grid").innerHTML = "";
    const before = $("grid").children.length;
    cards.forEach((c) => $("grid").insertAdjacentHTML("beforeend", card(c)));
    const n = $("grid").children.length;
    const notes = [...state.notes, ...extra,
                   ...(state.criteria.length ? [] : [`No criteria understood; showing top ${SRC[state.source].api} results.`])];
    $("status").textContent = [...notes, n ? `${n} shown${state.more ? ", more available" : ""}` : "Nothing found - try removing a label."].join(" ");
    if (state.notes.length)       // the only note is the adult one: point to the desktop version
      $("status").insertAdjacentHTML("beforeend", ` <a href="${DESKTOP_URL}" target="_blank" rel="noopener">Adult titles: get the free desktop version ↗</a>`);
    if (!n && mode === "all" && state.criteria.length > 1) $("status").insertAdjacentHTML("beforeend", TRY_ANY);
    $("more").hidden = !state.more;
    if (page > 1) $("grid").children[before]?.querySelector(".info a")?.focus();   // keyboard users carry on from the new cards
  } catch (e) {
    $("status").textContent = "Error: " + e.message;
  } finally {
    $("more").disabled = false;
  }
}

function card(c) {
  const cover = c.cover
    ? `<img src="${esc(c.cover)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : `<div class="placeholder">no cover</div>`;
  const ln = c.id.startsWith("l");
  const meta = [c.year, c.volumes ? `${c.volumes} vol.` : "",
                c.rating ? `★ ${c.rating.toFixed(ln ? 1 : 2)}` : "unrated", c.votecount ? `${c.votecount} ${ln ? "users" : "votes"}` : ""]
    .filter(Boolean).join(" · ");
  const hits = $("mode").value === "any" && c.wanted ? ` · ${c.hits}/${c.wanted} tags` : "";
  return `<div class="card" data-id="${esc(c.id)}" data-title="${esc(c.title)}">
    <button class="hide-btn" title="Not interested: never show this again" aria-label="Not interested in ${esc(c.title)}">✕</button>
    <a class="cover ${c.blur ? "blur" : ""}" href="#${esc(c.id)}" tabindex="-1" aria-hidden="true">${cover}</a>
    <div class="info">
      <a href="#${esc(c.id)}">${esc(c.title)}</a> <a class="ext" href="${esc(c.url)}" target="_blank" rel="noopener" title="open on ${ln ? "anilist.co" : "vndb.org"}" aria-label="Open on ${ln ? "anilist.co" : "vndb.org"}">↗</a>
      <div class="meta">${esc(meta + hits)}</div>
      <div class="tags">${c.tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div>
    </div></div>`;
}

$("grid").addEventListener("click", (e) => {
  const hb = e.target.closest(".hide-btn");
  if (hb) {
    const c = hb.closest(".card");
    if (Object.keys(prefs.hidden).length >= MAX_HIDDEN) { $("status").textContent = `At most ${MAX_HIDDEN} hidden titles.`; return; }
    prefs.hidden[c.dataset.id] = c.dataset.title;
    savePrefs(); renderPrefs();
    hideWithUndo(c, () => { delete prefs.hidden[c.dataset.id]; savePrefs(); renderPrefs(); });
    return;
  }
  const cov = e.target.closest(".cover.blur");
  if (cov) { e.preventDefault(); cov.classList.remove("blur"); }   // first click reveals, second opens
});


// ---------------------------------------------------------------- shelves: ready-made browsing for when you don't know what you want
const day = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);   // n days from today
const crit = (kind, value, display, op = "=") => ({ kind, value, op, label: display, display, exclude: false, phrase: "", method: "shelf" });
const SHELVES = {   // [label, sort, criteria]
  vn: [["New and popular", "votecount", () => [crit("released", [[">=", day(-90)], ["<=", day(0)]], "Released in the last 3 months")]],
       ["Best of the past year", "rating", () => [crit("released", [[">=", day(-365)], ["<=", day(0)]], "Released in the past year"),
                                                  crit("votecount", 30, "30+ votes", ">=")]],
       ["Top rated, all time", "rating", () => [crit("votecount", 500, "500+ votes", ">=")]],
       ["Most popular, all time", "votecount", () => [crit("votecount", 100, "100+ votes", ">=")]],
       ["Coming soon", "soonest", () => [crit("released", [[">", day(0)], ["<=", day(180)]], "Out in the next 6 months")]]],
  ln: [["Trending now", "trending", () => [crit("votecount", 100, "100+ users", ">=")]]],
};
function renderShelves() {
  $("shelves").innerHTML = SHELVES[state.source].map(([label], i) => `<button type="button" data-i="${i}">${esc(label)}</button>`).join("");
  document.querySelector('#sort option[value="trending"]').hidden = !isLN();
  const s = $("sort").value;
  if ((s === "trending" && !isLN()) || (s === "soonest" && isLN())) $("sort").value = "rating";
}
$("shelves").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  const [, sort, crits] = SHELVES[state.source][+b.dataset.i];
  $("q").value = "";
  pushUrl("");
  $("welcome").hidden = true;
  $("report").innerHTML = "";
  $("sort").value = sort;
  $("mode").value = "all";
  Object.assign(state, { criteria: crits(), unmatched: [], skip: [], notes: [] });
  renderChips();
  search(1);
});

// ---------------------------------------------------------------- title search
function titleSearch(t) {
  t = t.trim();
  if (!t) return;
  $("welcome").hidden = true;
  $("report").innerHTML = "";
  Object.assign(state, { criteria: [{ kind: "title", value: t, label: "Title: " + t, exclude: false,
                                      phrase: t, method: "title search", display: "Title: " + t }],
                         unmatched: [], skip: [], notes: [] });
  renderChips();
  search(1);
}
// one bar, two ways to search: "describe" (the parser) or "title" (VNDB title search)
function setBy(by) {
  searchBy = by;
  pressed("#search-form .by button", (b) => b.dataset.by === by);
  $("q").placeholder = by === "title" ? SRC[state.source].titleHint : SRC[state.source].placeholder;
}
document.querySelectorAll("#search-form .by button").forEach((b) => b.addEventListener("click", () => { setBy(b.dataset.by); $("q").focus(); }));

$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("q").value.trim();
  if ($("sort").value === "soonest") $("sort").value = "rating";   // a shelf's special order doesn't carry over
  pushUrl(q);
  if (searchBy === "title") titleSearch(q);
  else parseAndSearch(q);
});
function pushUrl(q) {
  const u = new URLSearchParams();
  if (isLN()) u.set("src", "ln");
  if (q) u.set(searchBy === "title" ? "title" : "q", q);
  history.replaceState(null, "", location.pathname + (u.toString() ? "?" + u : ""));
}
// switching VN <-> light novel re-runs the current search against the other source
document.querySelectorAll(".src-switch button").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.src === state.source) return;
  applySource(b.dataset.src);
  const q = $("q").value.trim();
  pushUrl(q);
  Object.assign(state, { criteria: [], unmatched: [], notes: [], skip: [] });
  $("grid").innerHTML = ""; $("more").hidden = true; $("status").textContent = "";
  if (!q) { $("understood").hidden = true; $("welcome").hidden = false; return; }
  if (searchBy === "title") titleSearch(q);
  else parseAndSearch(q);
}));
["sort", "mode"].forEach((id) => $(id).addEventListener("change", () => { if (state.criteria.length || $("grid").children.length) search(1); }));
$("more").addEventListener("click", () => search(state.page + 1));
document.querySelectorAll(".try").forEach((b) => b.addEventListener("click", () => {
  $("q").value = b.textContent;
  setBy("describe");
  $("search-form").requestSubmit();
}));

// ---------------------------------------------------------------- detail view (#v17)
let fields = null, searchScroll = 0, fromSearch = false;

async function showVN(vid) {
  if ($("vn-view").hidden) { searchScroll = window.scrollY; fromSearch = !$("search-view").hidden && booted; }
  $("search-view").hidden = true;
  $("vn-view").hidden = false;
  document.documentElement.dataset.src = vid.startsWith("l") ? "ln" : "vn";   // the page wears its source's theme
  document.body.classList.remove("spoilers");
  $("vn-body").innerHTML = `<p class="vn-status">Loading ${esc(vid)}...</p>`;
  window.scrollTo(0, 0);
  try {
    fields ??= (await py).FIELDS.get("detail");
    if (vid.startsWith("l")) return await showLN(vid);
    const data = await vndb({ filters: ["id", "=", vid], fields, results: 1 });
    if (!data.results?.length) { $("vn-body").innerHTML = `<p class="vn-status">No visual novel ${esc(vid)} on VNDB.</p>`; return; }
    const vn = await call("detail", JSON.stringify(data.results[0]));
    document.title = `${vn.title} - Yoru no Toshokan`;
    $("vn-body").innerHTML = vnHtml(vn);
    bindViewer();
  } catch (e) {
    $("vn-body").innerHTML = `<p class="vn-status">Error: ${esc(e.message)}</p>`;
  }
}

function vnHtml(vn) {
  const row = (th, td) => td ? `<tr><th>${esc(th)}</th><td>${td}</td></tr>` : "";
  const list = (xs) => xs.map(esc).join(", ");
  const cover = vn.cover
    ? `<div class="cover big ${vn.cover_blur ? "blur" : ""}"${vn.cover_blur ? ' role="button" tabindex="0" aria-label="Reveal cover"' : ""}><img src="${esc(vn.cover)}" alt="" referrerpolicy="no-referrer"></div>`
    : `<div class="cover big"><div class="placeholder">no cover</div></div>`;
  const staff = vn.staff.map(([role, names]) => row(role, list(names.slice(0, 4)) +
    (names.length > 4 ? ` <span class="muted">+${names.length - 4}</span>` : ""))).join("");
  const tags = vn.tag_groups.map((g) => `<div class="tag-group"><span class="tag-cat">${esc(g.label)}</span>
    ${g.tags.map((t, i) => `<a class="tag ${t.spoiler ? "spoiler-tag" : ""} ${i >= 30 ? "extra" : ""}" href="https://vndb.org/${esc(t.id)}" target="_blank" rel="noopener" title="score ${t.rating}${t.spoiler ? " · spoiler" : ""}">${esc(t.name)}</a>`).join("")}
    ${g.tags.length > 30 ? `<button class="all-tags">show all ${g.tags.length}</button>` : ""}</div>`).join("") || `<p class="muted">No tags.</p>`;
  const shots = vn.screenshots.length ? `<h2>Screenshots</h2><div class="shots">
    ${vn.screenshots.map((s, i) => `<a class="cover shot ${s.blur ? "blur" : ""}" href="${esc(s.url)}" data-i="${i}" aria-label="Screenshot ${i + 1}"><img src="${esc(s.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer"></a>`).join("")}</div>
    <dialog id="viewer" aria-label="Screenshots">
      <button class="v-close" title="Close (Esc)" aria-label="Close">×</button>
      <button class="v-nav v-prev" title="Previous (←)" aria-label="Previous screenshot">‹</button>
      <figure><img id="v-img" alt="" referrerpolicy="no-referrer"><figcaption id="v-count"></figcaption></figure>
      <button class="v-nav v-next" title="Next (→)" aria-label="Next screenshot">›</button>
      <div class="v-strip">${vn.screenshots.map((s, i) => `<img src="${esc(s.thumb)}" data-i="${i}" alt="" loading="lazy" referrerpolicy="no-referrer">`).join("")}</div>
    </dialog>` : "";
  const rels = vn.relations.length ? `<h2>Related</h2><div class="relations">${vn.relations.map((r) => `
    <a class="rel" href="#${esc(r.id)}">
      <div class="cover ${r.blur ? "blur" : ""}">${r.cover ? `<img src="${esc(r.cover)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<div class="placeholder">no cover</div>`}</div>
      <div class="rel-info"><span class="muted">${esc(r.relation)}${r.year ? ` · ${esc(r.year)}` : ""}</span><br>${esc(r.title)}</div>
    </a>`).join("")}</div>` : "";
  return `${vn.cover && !vn.cover_blur ? `<div class="backdrop" style="background-image: url('${esc(vn.cover)}')"></div>` : ""}
  <main class="vn">
    <div class="vn-side">${cover}
      <a class="vndb-link" href="${esc(vn.url)}" target="_blank" rel="noopener">Open on vndb.org ↗</a>
      ${vn.links.map((l) => `<a class="ext-link" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`).join("")}
    </div>
    <div class="vn-main">
      <h1>${esc(vn.title)}</h1>
      ${vn.alttitle && vn.alttitle !== vn.title ? `<div class="alttitle">${esc(vn.alttitle)}</div>` : ""}
      <table class="facts">
        ${row("Rating", vn.rating ? `★ ${vn.rating.toFixed(2)} <span class="muted">(${vn.votecount} votes)</span>` : "unrated")}
        ${row("Released", esc(vn.released) + (vn.devstatus ? ` <span class="muted">(${esc(vn.devstatus)})</span>` : ""))}
        ${row("Length", esc(vn.length || ""))}
        ${row("Developer", list(vn.developers))}
        ${staff}
        ${row("Original language", esc(vn.original_language || ""))}
        ${row("Languages", list(vn.languages))}
        ${row("Platforms", list(vn.platforms))}
        ${row("Aliases", list(vn.aliases))}
      </table>
      <h2>Synopsis</h2>
      <div class="description">${vn.description || "No description on VNDB."}</div>
      <h2>Tags ${vn.tag_groups.length ? `<label class="spoil-toggle"><input type="checkbox" id="show-spoilers"> show spoilers</label>` : ""}</h2>
      ${tags}
      ${shots}${rels}
    </div>
  </main>`;
}

async function showLN(lid) {
  const q = await call("ln_detail_query", lid);
  const m = q && (await anilist(q)).Media;
  const ln = m && await call("ln_detail", JSON.stringify(m));
  if (!ln) { $("vn-body").innerHTML = `<p class="vn-status">No light novel ${esc(lid)} on AniList.</p>`; return; }
  if (ln.adult) {
    $("vn-body").innerHTML = `<p class="vn-status">This title is for adults only, so the web version doesn't show it.
      <a href="${DESKTOP_URL}" target="_blank" rel="noopener">The free desktop version can ↗</a></p>`;
    return;
  }
  document.title = `${ln.title} - Yoru no Toshokan`;
  $("vn-body").innerHTML = lnHtml(ln);
}

function lnHtml(ln) {
  const row = (th, td) => td ? `<tr><th>${esc(th)}</th><td>${td}</td></tr>` : "";
  const list = (xs) => xs.map(esc).join(", ");
  const cover = ln.cover
    ? `<div class="cover big"><img src="${esc(ln.cover)}" alt="" referrerpolicy="no-referrer"></div>`
    : `<div class="cover big"><div class="placeholder">no cover</div></div>`;
  const staff = ln.staff.map(([role, names]) => row(role, list(names.slice(0, 4)) +
    (names.length > 4 ? ` <span class="muted">+${names.length - 4}</span>` : ""))).join("");
  const tags = ln.tag_groups.map((g) => `<div class="tag-group"><span class="tag-cat">${esc(g.label)}</span>
    ${g.tags.map((t, i) => `<a class="tag ${t.spoiler ? "spoiler-tag" : ""} ${i >= 30 ? "extra" : ""}" href="${esc(t.url)}" target="_blank" rel="noopener" title="${t.rating ? `${t.rating}% relevant` : ""}${t.spoiler ? " · spoiler" : ""}">${esc(t.name)}</a>`).join("")}
    ${g.tags.length > 30 ? `<button class="all-tags">show all ${g.tags.length}</button>` : ""}</div>`).join("") || `<p class="muted">No tags.</p>`;
  const rels = ln.relations.length ? `<h2>Related</h2><div class="relations">${ln.relations.map((r) => `
    <a class="rel" href="${r.id ? "#" + esc(r.id) : esc(r.url)}"${r.id ? "" : ' target="_blank" rel="noopener"'}>
      <div class="cover">${r.cover ? `<img src="${esc(r.cover)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<div class="placeholder">no cover</div>`}</div>
      <div class="rel-info"><span class="muted">${esc(r.relation)}${r.year ? ` · ${esc(r.year)}` : ""}</span><br>${esc(r.title)}${r.id ? "" : " ↗"}</div>
    </a>`).join("")}</div>` : "";
  return `${ln.cover ? `<div class="backdrop" style="background-image: url('${esc(ln.cover)}')"></div>` : ""}
  <main class="vn">
    <div class="vn-side">${cover}
      <a class="vndb-link" href="${esc(ln.url)}" target="_blank" rel="noopener">Open on anilist.co ↗</a>
      ${ln.links.map((l) => `<a class="ext-link" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`).join("")}
    </div>
    <div class="vn-main">
      <h1>${esc(ln.title)}</h1>
      ${ln.alttitle ? `<div class="alttitle">${esc(ln.alttitle)}</div>` : ""}
      <table class="facts">
        ${row("Score", ln.rating ? `★ ${ln.rating.toFixed(1)} <span class="muted">(${ln.votecount} users, ${ln.favourites} favourites)</span>` : "unscored")}
        ${row("Published", esc(ln.released) + (ln.status ? ` <span class="muted">(${esc(ln.status)})</span>` : ""))}
        ${row("Volumes", esc(ln.volumes || ""))}
        ${staff}
        ${row("Country", esc(ln.country || ""))}
        ${row("Aliases", list(ln.aliases))}
      </table>
      <h2>Synopsis</h2>
      <div class="description">${ln.description || "No description on AniList."}</div>
      <h2>Tags ${ln.tag_groups.length ? `<label class="spoil-toggle"><input type="checkbox" id="show-spoilers"> show spoilers</label>` : ""}</h2>
      ${tags}
      ${rels}
    </div>
  </main>`;
}

// blurred images and [spoiler] text: first click reveals (detail view)
$("vn-body").addEventListener("click", (e) => {
  const all = e.target.closest(".all-tags");
  if (all) { all.parentElement.classList.add("open"); all.remove(); return; }
  const b = e.target.closest(".blur:not(.shot), .spoiler:not(.shown)");
  if (!b) return;
  e.preventDefault();
  b.classList.remove("blur");
  b.classList.add("shown");
});
$("vn-body").addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches('[role="button"]')) { e.preventDefault(); e.target.click(); }
});
$("vn-body").addEventListener("change", (e) => {
  if (e.target.id === "show-spoilers") document.body.classList.toggle("spoilers", e.target.checked);
});

function bindViewer() {
  const viewer = $("viewer");
  if (!viewer) return;
  const thumbs = [...document.querySelectorAll(".shots .shot")];
  const strip = [...viewer.querySelectorAll(".v-strip img")];
  const img = $("v-img");
  let cur = 0;
  const show = (i) => {
    cur = (i + thumbs.length) % thumbs.length;
    const hidden = thumbs[cur].classList.contains("blur");     // not revealed yet: stay blurred
    img.src = thumbs[cur].href;
    img.classList.toggle("veiled", hidden);
    $("v-count").textContent = `${cur + 1} / ${thumbs.length}` + (hidden ? " · click to reveal" : "");
    strip.forEach((s, j) => { s.classList.toggle("on", j === cur); s.classList.toggle("veiled", thumbs[j].classList.contains("blur")); });
    strip[cur].scrollIntoView({ block: "nearest", inline: "center" });
    [cur - 1, cur + 1].forEach((j) => { new Image().src = thumbs[(j + thumbs.length) % thumbs.length].href; });
  };
  const open = (i) => { viewer.showModal(); document.body.style.overflow = "hidden"; show(i); };
  const close = () => viewer.close();
  viewer.addEventListener("close", () => { document.body.style.overflow = ""; });
  thumbs.forEach((t) => t.addEventListener("click", (e) => {
    e.preventDefault();
    if (t.classList.contains("blur")) t.classList.remove("blur");   // first click reveals
    else open(+t.dataset.i);
  }));
  img.addEventListener("click", () => { if (img.classList.contains("veiled")) { thumbs[cur].classList.remove("blur"); show(cur); } });
  viewer.querySelector(".v-prev").addEventListener("click", () => show(cur - 1));
  viewer.querySelector(".v-next").addEventListener("click", () => show(cur + 1));
  viewer.querySelector(".v-close").addEventListener("click", close);
  strip.forEach((s) => s.addEventListener("click", () => show(+s.dataset.i)));
  viewer.addEventListener("click", (e) => { if (e.target === viewer || e.target.tagName === "FIGURE") close(); });
  viewer.addEventListener("keydown", (e) => {   // Esc is the dialog's own
    if (e.key === "ArrowLeft") show(cur - 1);
    else if (e.key === "ArrowRight") show(cur + 1);
  });
}

function showSearch() {
  if ($("search-view").hidden === false) return;
  document.body.style.overflow = "";
  $("vn-view").hidden = true;
  $("search-view").hidden = false;
  document.documentElement.dataset.src = state.source;
  document.title = "Yoru no Toshokan";
  requestAnimationFrame(() => window.scrollTo(0, searchScroll));
}

function route() {
  const vid = location.hash.match(/^#(v\d{1,7}|l\d{1,9})$/)?.[1];
  if (vid) showVN(vid); else showSearch();
}
window.addEventListener("hashchange", route);
$("back").addEventListener("click", (e) => {
  e.preventDefault();
  if (fromSearch) history.back();
  else { history.pushState(null, "", location.pathname + location.search); route(); }
});

// ---------------------------------------------------------------- start
let booted = false;
const urlQ = new URLSearchParams(location.search).get("q");
applySource(new URLSearchParams(location.search).get("src") || (location.search ? "vn" : localStorage.getItem("src")) || "vn");
if (location.hash) route();
const urlT = new URLSearchParams(location.search).get("title");
if (urlT) { setBy("title"); $("q").value = urlT; titleSearch(urlT); }
else if (urlQ) { $("q").value = urlQ; parseAndSearch(urlQ); }
booted = true;
py.catch((e) => { $("status").textContent = "Could not start the search engine: " + e.message; });
