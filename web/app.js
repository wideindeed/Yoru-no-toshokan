// Yoru no Toshokan, browser-only version. The parser runs in Pyodide (web.py);
// this file talks to VNDB directly and keeps preferences in localStorage.
const $ = (id) => document.getElementById(id);
const API = "https://api.vndb.org/kana/vn";
const DESKTOP_URL = "https://github.com/wideindeed/Yoru-no-toshokan#getting-started";
const state = { criteria: [], unmatched: [], notes: [], page: 1, more: false, skip: [] };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

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

// ---------------------------------------------------------------- preferences (this browser only)
const MAX_EX = 50, MAX_HIDDEN = 300;
let prefs = { exclude: [], hidden: {} };        // exclude: [{id, name}], hidden: {vid: title}
try { Object.assign(prefs, JSON.parse(localStorage.getItem("prefs") || "{}")); } catch { /* fresh start */ }
const savePrefs = () => localStorage.setItem("prefs", JSON.stringify(prefs));

function renderPrefs() {
  $("ex-list").innerHTML = prefs.exclude.map((t) =>
    `<span class="chip neg">${esc(t.name)}<button data-id="${esc(t.id)}">×</button></span>`).join("") || "<em>none</em>";
  $("hidden-list").innerHTML = Object.entries(prefs.hidden).map(([id, title]) =>
    `<span class="chip pref"><a href="#${esc(id)}">${esc(title)}</a><button data-unhide="${esc(id)}">×</button></span>`).join("") || "<em>none</em>";
  if (!$("understood").hidden) renderAlways();
}

document.querySelector(".padd").addEventListener("submit", async (e) => {
  e.preventDefault();
  const inp = e.target.querySelector("input"), name = inp.value.trim();
  if (!name) return;
  $("prefs-msg").textContent = "";
  const tags = await call("resolve", name);
  if (!tags.length) { $("prefs-msg").textContent = `No VNDB tag matches "${name}".`; return; }
  for (const t of tags) if (!prefs.exclude.some((x) => x.id === t.id)) prefs.exclude.push(t);
  if (prefs.exclude.length > MAX_EX) { prefs.exclude.length = MAX_EX; $("prefs-msg").textContent = `At most ${MAX_EX} tags.`; }
  savePrefs(); renderPrefs(); inp.value = "";
});
$("prefs-panel").addEventListener("click", (e) => {
  const b = e.target.closest(".plist button");
  if (!b) return;
  if (b.dataset.unhide) delete prefs.hidden[b.dataset.unhide];
  else prefs.exclude = prefs.exclude.filter((t) => t.id !== b.dataset.id);
  savePrefs(); renderPrefs();
});

// ---------------------------------------------------------------- search
async function parseAndSearch(text) {
  if (!text.trim()) return;
  $("welcome").hidden = true;
  $("status").textContent = ready ? "Parsing..." : "Loading the search engine (the first visit takes a few seconds)...";
  try {
    const p = await call("parse", text);
    Object.assign(state, { criteria: p.criteria, unmatched: p.unmatched, notes: p.notes, skip: [] });
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
  const list = prefs.exclude.filter((t) => !state.skip.includes(t.id));
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
  if (b.dataset.i !== undefined) { state.criteria.splice(+b.dataset.i, 1); renderChips(); search(1); }
  else { state.unmatched.splice(+b.dataset.u, 1); renderChips(); }
});

// ---------------------------------------------------------------- tag browser
let lookingUp = null;           // an unmatched phrase being looked up; replaced by the tag picked
const tags = mountTagBrowser($("tag-browser"), {
  search: (q) => call("tags", q),
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
  $("status").textContent = "Searching VNDB...";
  $("more").disabled = true;
  try {
    const crits = JSON.stringify(state.criteria), mode = $("mode").value;
    const excludes = prefs.exclude.filter((t) => !state.skip.includes(t.id));
    const body = await call("query", crits, $("sort").value, mode, page,
                            JSON.stringify(excludes), JSON.stringify(Object.keys(prefs.hidden)));
    const data = await vndb(body);
    const cards = await call("cards", JSON.stringify(data.results || []), crits, mode);
    state.page = page;
    state.more = !!data.more;
    if (page === 1) $("grid").innerHTML = "";
    cards.forEach((c) => $("grid").insertAdjacentHTML("beforeend", card(c)));
    const n = $("grid").children.length;
    const notes = [...state.notes, ...(state.criteria.length ? [] : ["No criteria understood; showing top VNDB results."])];
    $("status").textContent = [...notes, n ? `${n} shown${state.more ? ", more available" : ""}` : "Nothing found - try removing a label."].join(" ");
    if (state.notes.length)       // the only note is the adult one: point to the desktop version
      $("status").insertAdjacentHTML("beforeend", ` <a href="${DESKTOP_URL}" target="_blank" rel="noopener">Adult titles: get the free desktop version ↗</a>`);
    $("more").hidden = !state.more;
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
  const meta = [c.year, c.rating ? `★ ${c.rating.toFixed(2)}` : "unrated", c.votecount ? `${c.votecount} votes` : ""]
    .filter(Boolean).join(" · ");
  const hits = $("mode").value === "any" && c.wanted ? ` · ${c.hits}/${c.wanted} tags` : "";
  return `<div class="card" data-id="${esc(c.id)}" data-title="${esc(c.title)}">
    <button class="hide-btn" title="Not interested: never show this again">✕</button>
    <a class="cover ${c.blur ? "blur" : ""}" href="#${esc(c.id)}">${cover}</a>
    <div class="info">
      <a href="#${esc(c.id)}">${esc(c.title)}</a> <a class="ext" href="${esc(c.url)}" target="_blank" rel="noopener" title="open on vndb.org">↗</a>
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
    savePrefs(); renderPrefs(); c.remove();
    return;
  }
  const cov = e.target.closest(".cover.blur");
  if (cov) { e.preventDefault(); cov.classList.remove("blur"); }   // first click reveals, second opens
});

$("search-form").addEventListener("submit", (e) => {
  e.preventDefault();
  history.replaceState(null, "", location.pathname + "?q=" + encodeURIComponent($("q").value));
  parseAndSearch($("q").value);
});
["sort", "mode"].forEach((id) => $(id).addEventListener("change", () => { if (state.criteria.length || $("grid").children.length) search(1); }));
$("more").addEventListener("click", () => search(state.page + 1));
document.querySelectorAll(".try").forEach((b) => b.addEventListener("click", () => {
  $("q").value = b.textContent;
  $("search-form").requestSubmit();
}));

// ---------------------------------------------------------------- detail view (#v17)
let fields = null, searchScroll = 0, fromSearch = false;

async function showVN(vid) {
  if ($("vn-view").hidden) { searchScroll = window.scrollY; fromSearch = !$("search-view").hidden && booted; }
  $("search-view").hidden = true;
  $("vn-view").hidden = false;
  document.body.classList.remove("spoilers");
  $("vn-body").innerHTML = `<p class="vn-status">Loading ${esc(vid)}...</p>`;
  window.scrollTo(0, 0);
  try {
    fields ??= (await py).FIELDS.get("detail");
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
    ? `<div class="cover big ${vn.cover_blur ? "blur" : ""}"><img src="${esc(vn.cover)}" alt="" referrerpolicy="no-referrer"></div>`
    : `<div class="cover big"><div class="placeholder">no cover</div></div>`;
  const staff = vn.staff.map(([role, names]) => row(role, list(names.slice(0, 4)) +
    (names.length > 4 ? ` <span class="muted">+${names.length - 4}</span>` : ""))).join("");
  const tags = vn.tag_groups.map((g) => `<div class="tag-group"><span class="tag-cat">${esc(g.label)}</span>
    ${g.tags.map((t, i) => `<a class="tag ${t.spoiler ? "spoiler-tag" : ""} ${i >= 30 ? "extra" : ""}" href="https://vndb.org/${esc(t.id)}" target="_blank" rel="noopener" title="score ${t.rating}${t.spoiler ? " · spoiler" : ""}">${esc(t.name)}</a>`).join("")}
    ${g.tags.length > 30 ? `<button class="all-tags">show all ${g.tags.length}</button>` : ""}</div>`).join("") || `<p class="muted">No tags.</p>`;
  const shots = vn.screenshots.length ? `<h2>Screenshots</h2><div class="shots">
    ${vn.screenshots.map((s, i) => `<a class="cover shot ${s.blur ? "blur" : ""}" href="${esc(s.url)}" data-i="${i}"><img src="${esc(s.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer"></a>`).join("")}</div>
    <div id="viewer" hidden>
      <button class="v-close" title="Close (Esc)">×</button>
      <button class="v-nav v-prev" title="Previous (←)">‹</button>
      <figure><img id="v-img" alt="" referrerpolicy="no-referrer"><figcaption id="v-count"></figcaption></figure>
      <button class="v-nav v-next" title="Next (→)">›</button>
      <div class="v-strip">${vn.screenshots.map((s, i) => `<img src="${esc(s.thumb)}" data-i="${i}" alt="" loading="lazy" referrerpolicy="no-referrer">`).join("")}</div>
    </div>` : "";
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
$("vn-body").addEventListener("change", (e) => {
  if (e.target.id === "show-spoilers") document.body.classList.toggle("spoilers", e.target.checked);
});

let viewerKeys = null;
function bindViewer() {
  if (viewerKeys) document.removeEventListener("keydown", viewerKeys);
  viewerKeys = null;
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
  const open = (i) => { viewer.hidden = false; document.body.style.overflow = "hidden"; show(i); };
  const close = () => { viewer.hidden = true; document.body.style.overflow = ""; };
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
  viewerKeys = (e) => {
    if (viewer.hidden) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") show(cur - 1);
    else if (e.key === "ArrowRight") show(cur + 1);
  };
  document.addEventListener("keydown", viewerKeys);
}

function showSearch() {
  if ($("search-view").hidden === false) return;
  document.body.style.overflow = "";
  $("vn-view").hidden = true;
  $("search-view").hidden = false;
  document.title = "Yoru no Toshokan";
  requestAnimationFrame(() => window.scrollTo(0, searchScroll));
}

function route() {
  const vid = location.hash.match(/^#(v\d{1,7})$/)?.[1];
  if (vid) showVN(vid); else showSearch();
}
window.addEventListener("hashchange", route);
$("back").addEventListener("click", (e) => {
  e.preventDefault();
  if (fromSearch) history.back();
  else { history.pushState(null, "", location.pathname + location.search); route(); }
});

// ---------------------------------------------------------------- start
renderPrefs();
let booted = false;
const urlQ = new URLSearchParams(location.search).get("q");
if (location.hash) route();
if (urlQ) { $("q").value = urlQ; parseAndSearch(urlQ); }
booted = true;
py.catch((e) => { $("status").textContent = "Could not start the search engine: " + e.message; });
