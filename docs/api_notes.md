# VNDB Kana API — verified notes (checked 2026-11-02)

Source: https://api.vndb.org/kana and GET /kana/schema.

## Requests
- `POST https://api.vndb.org/kana/<type>` with JSON body:
  `filters, fields, sort, reverse, results (max 100), page, count, ...`
- Response: `{"results": [...], "more": bool}` (+ `count` if requested).
- `fields` is a comma-separated string; nested via dot (`image.url`).
  `id` is always included.

## Rate limits
- 200 requests / 5 minutes, and 1 s server execution time / minute.
- Requests over 3 s are aborted. 429 = throttled.
- Our client: min 1.5 s between live requests (200/5min = 1 per 1.5 s),
  exponential backoff on 429/502/503 (honours `Retry-After` if present).

## Filters
- Predicate: `[name, op, value]`; combine with `["and", ...]` / `["or", ...]`
  (each needs 2+ children). All filters support `=` and `!=`.
- VN filters used: `lang` (m, availability), `olang`, `platform` (m),
  `length` (o, 1..5), `released` (o,n, "YYYY[-MM[-DD]]"), `rating` (o, 10..100),
  `votecount` (o), `tag` (m, includes parent tags), `release` (nested release filters).
- Tag filter value: `["g134", max_spoiler(0-2), min_level(0-3)]`,
  e.g. `["tag","=",["g505",2,1.2]]`. Bare ID = `[id,0,0]`.
- Release filter `engine` is an exact string. Use it nested:
  `["release","=",["engine","=","RPG Maker"]]`.
- VN sort values: id, title, released, rating, votecount, searchrank.

## Engine strings (live release counts)
- `RPG Maker` 2093 — VNDB does NOT distinguish versions (XP/VX/MV/MZ all = "RPG Maker").
- `Wolf RPG Editor` 240, `Ren'Py` 30067, `KiriKiri` 8747, `TyranoScript` 5956
  (TyranoBuilder = TyranoScript), `Unity` 5525, `NScripter` 2299, `Godot` 607,
  `GameMaker` 220, `Visual Novel Maker` 234, `RealLive` 250, `Unreal Engine` 22.

## Tags
- 3015 tags total. Fields: id, name, aliases, category (cont/ero/tech),
  searchable, applicable, vn_count. We keep `searchable == true`.
- Note: some searchable tags are not `applicable` (e.g. g235 "No Sexual Content",
  a parent tag) — still usable as filters.

## VN image fields
- `image.sexual`, `image.violence`: 0..2 averages.
