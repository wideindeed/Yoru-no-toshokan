// Tag browser widget, shared by the desktop and web pages.
//   const tb = mountTagBrowser(rootElement, { search: async (q) => rows, onPick: (row, exclude) => {} });
//   tb.open("some text")   // fill the box and search
// rows: [{id, name, category, vn_count, why, description}] from parsing/tag_browser.py
function mountTagBrowser(root, { search, onPick }) {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  root.innerHTML = `<input class="tb-q" type="search" autocomplete="off"
      placeholder="find a tag by name, nickname or description (typos are fine)">
    <div class="tb-list"></div>`;
  const input = root.querySelector(".tb-q"), list = root.querySelector(".tb-list");
  let rows = [], timer = null, seq = 0;

  async function run() {
    const q = input.value.trim(), my = ++seq;
    if (q.length < 2) { list.innerHTML = ""; rows = []; return; }
    try {
      const found = await search(q);
      if (my !== seq) return;                      // a newer search has started
      rows = found;
      list.innerHTML = rows.map((t, i) => `<div class="tb-row">
          <button class="tb-add" data-i="${i}" title="Add to the search">+</button>
          <button class="tb-ex" data-i="${i}" title="Exclude from the search">−</button>
          <span class="tb-main"><a href="https://vndb.org/${esc(t.id)}" target="_blank" rel="noopener" title="open on vndb.org">${esc(t.name)}</a>
            <span class="tb-n">${t.vn_count} VNs${t.category === "tech" ? " · technical" : ""}${t.why ? " · " + esc(t.why) : ""}</span>
            ${t.description ? `<span class="tb-desc">${esc(t.description)}</span>` : ""}</span>
        </div>`).join("") || `<em class="tb-none">No tag matches "${esc(q)}".</em>`;
    } catch (e) {
      if (my === seq) list.innerHTML = `<em class="tb-none">Error: ${esc(e.message)}</em>`;
    }
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
