// "Close in meaning": tags whose names are near a phrase, for the tag browser.
// Runs all-MiniLM-L6-v2 in the browser with transformers.js. The model (~23 MB, cached by
// the browser) and the tag vectors (static/vectors, from `python -m parsing.embed`) load
// the first time it's used, so nobody downloads them who doesn't need them.
//   await relatedTags("lost his memory", { base: "/static/vectors/", src: "vn", ero: false })
// role ("heroine" | "hero" | "protagonist"): the words describe that person (the parser's
// unmatched_role), so tags about the other roles are left out and theirs come first.
const relatedTags = (() => {
  const LIB = "https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.3.2";
  let model = null;
  const sets = {};

  const load = () => model ??= import(LIB)
    .then(({ pipeline }) => pipeline("feature-extraction", "Xenova/all-MiniLM-L6-v2", { dtype: "q8" }))
    .catch((e) => { model = null; throw e; });          // let a later click retry

  const vectors = (base, src) => sets[src] ??= Promise.all([
    fetch(`${base}${src}.json`).then((r) => r.json()),
    fetch(`${base}${src}.bin`).then((r) => r.arrayBuffer()),
  ]).then(([meta, buf]) => ({ ...meta, v: new Int8Array(buf) }))
    .catch((e) => { delete sets[src]; throw e; });

  const ROLE_RE = /\b(heroine|hero|protagonist)\b/i;

  return async function (text, { base, src, ero, role, k = 5, min = 0.45 }) {
    const [embed, { dim, tags, v }] = await Promise.all([load(), vectors(base, src)]);
    const q = (await embed(text, { pooling: "mean", normalize: true })).data;
    const scored = [];
    for (let i = 0; i < tags.length; i++) {
      if (!ero && tags[i][2] === "ero") continue;
      const who = role && ROLE_RE.exec(tags[i][1])?.[1].toLowerCase();
      if (who && who !== role) continue;
      let s = 0;
      for (let j = 0, o = i * dim; j < dim; j++) s += q[j] * v[o + j];
      s = s / 127 + (who ? 0.05 : 0);                     // the vectors are stored as int8 (x127)
      if (s >= min) scored.push([s, i]);
    }
    return scored.sort((a, b) => b[0] - a[0]).slice(0, k).map(([, i]) => {
      const [id, name, category, vn_count] = tags[i];
      return { id, name, category, vn_count, why: "close in meaning" };
    });
  };
})();
