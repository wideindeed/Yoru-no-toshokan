// Tag browser widget, shared by the desktop and web pages.
//   const tb = mountTagBrowser(rootElement, { search: async (q) => rows, onPick: (row, exclude) => {},
//                                             related: async (q) => rows });   // related is optional
//   tb.open("some text")   // fill the box and search
// rows: [{id, name, category, vn_count, why, description}] from parsing/tag_browser.py;
// related rows (static/related.js) are listed after them under "Close in meaning".
function mountTagBrowser(root, { search, onPick, related }) {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  root.innerHTML = `<input class="tb-q" type="search" autocomplete="off" aria-label="Find a tag"
      placeholder="find a tag by name, nickname or description (typos are fine)">
    <div class="tb-list"></div>`;
  const input = root.querySelector(".tb-q"), list = root.querySelector(".tb-list");
  let rows = [], timer = null, seq = 0;

  const row = (t, i) => `<div class="tb-row">
      <button class="tb-add" data-i="${i}" title="Add to the search" aria-label="Add ${esc(t.name)}">+</button>
      <button class="tb-ex" data-i="${i}" title="Exclude from the search" aria-label="Exclude ${esc(t.name)}">−</button>
      <span class="tb-main">${tagLink(t)}
        <span class="tb-n">${[/^g\d/.test(t.id) ? `${t.vn_count} VNs` : t.id.startsWith("genre:") ? "genre" : "",
                              t.category === "tech" ? "technical" : "", esc(t.why || "")].filter(Boolean).join(" · ")}</span>
        ${t.description ? `<span class="tb-desc">${esc(t.description)}</span>` : ""}</span>
    </div>`;

  async function run() {
    const q = input.value.trim(), my = ++seq;
    if (q.length < 2) { list.innerHTML = ""; rows = []; return; }
    try {
      const found = await search(q);
      if (my !== seq) return;                      // a newer search has started
      rows = found;
      list.innerHTML = rows.map(row).join("") || (related ? "" : `<em class="tb-none">No tag matches "${esc(q)}".</em>`);
    } catch (e) {
      if (my === seq) list.innerHTML = `<em class="tb-none">Error: ${esc(e.message)}</em>`;
      return;
    }
    // tags close in meaning, for phrases and for words whose names found little:
    // the model takes a few seconds (and ~23 MB) the first time
    if (!related || q.length < 3 || (rows.length >= 3 && !q.includes(" "))) return;
    list.insertAdjacentHTML("beforeend", `<em class="tb-none tb-rel">Looking for tags close in meaning…</em>`);
    let more;
    try { more = await related(q); } catch { more = null; }
    if (my !== seq) return;
    const have = new Set(rows.map((t) => t.id)), start = rows.length;
    more = (more || []).filter((t) => !have.has(t.id));
    rows = rows.concat(more);
    list.querySelector(".tb-rel").outerHTML = more.length
      ? `<p class="tb-head">Close in meaning</p>` + more.map((t, i) => row(t, start + i)).join("")
      : start ? "" : `<em class="tb-none">No tag matches "${esc(q)}".</em>`;
  }

  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 200); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); clearTimeout(timer); run(); } });
  list.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-i]");
    if (!b) return;
    onPick(rows[+b.dataset.i], b.classList.contains("tb-ex"));
    b.closest(".tb-row").classList.add(b.classList.contains("tb-ex") ? "picked-ex" : "picked");
  });
  return { open(q) { input.value = q; run(); input.focus(); } };
}

// VNDB tags are "g123"; AniList tags "t123" and genres "genre:Name" (light novel mode)
function tagLink(t) {
  const e = (x) => String(x ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const vndb = /^g\d/.test(t.id);
  const url = vndb ? `https://vndb.org/${t.id}` : `https://anilist.co/search/manga?format=NOVEL&genres=${encodeURIComponent(t.name)}`;
  return `<a href="${e(url)}" target="_blank" rel="noopener" title="open on ${vndb ? "vndb.org" : "anilist.co"}">${e(t.name)}</a>`;
}
