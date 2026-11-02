# Yoru no Toshokan &nbsp;夜の図書館

*The night library. Visual novels, after hours.*

Tell it what you're in the mood for, the way you'd say it to a friend, and it
finds matching visual novels on [VNDB](https://vndb.org):

> fantasy setting, female lead, multiple endings
>
> a slice of life story with one ending, in english
>
> I'd love something about vampires made in RPG Maker, but no horror, ideally after 2015

No tag pickers and no fifty-checkbox filter forms. It runs on your own computer,
it's free, and it needs no account.

![Search results](docs/screenshots/results.png)

## What it does

- **Reads plain sentences.** Genres, tags, language, engine, platform, length,
  release years, "highly rated", "popular", and negatives like *no horror* or
  *without romance*. It understands common nicknames ("otome", "isekai", "rpgm",
  "female mc") and shrugs off typos.
- **Shows its working.** Every search is turned into a row of labels you can see
  and remove. Anything it didn't understand is marked in red rather than quietly
  ignored.
- **Proper detail pages.** Synopsis, rating, length, developer and staff,
  languages, platforms, tags by category with spoilers hidden, a screenshot
  viewer, and related titles.
- **A Mature switch that means it.** Off: nothing with sexual content, at any
  level. On: only titles with sexual content. No in-between leaking through.
- **Your own filters.** Keep a list of tags you never want to see, for example
  "Gore" or "Netorare", separately for each mode. Hide individual titles you're
  not interested in, and they stay gone.
- **Bookmarkable searches.** Each search lives in the address bar, so you can
  save it or share it.

![Detail page](docs/screenshots/detail.png)

## Getting started

You need [Python](https://www.python.org/downloads/) 3.10 or newer.

**Windows**

```bat
git clone https://github.com/wideindeed/Yoru-no-toshokan.git
cd Yoru-no-toshokan
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
run.bat
```

**Linux / macOS / Raspberry Pi**

```sh
git clone https://github.com/wideindeed/Yoru-no-toshokan.git
cd Yoru-no-toshokan
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Then open <http://127.0.0.1:5050>. `run.bat` opens it for you.

The first start takes about a minute: it downloads VNDB's tag list (around 3,000
tags) at a polite pace. After that it starts in seconds, and the list refreshes
itself once a week.

## Searching

| You write | It looks for |
|---|---|
| english, japanese, eng, jp ... | available in that language |
| RPG Maker, Ren'Py, Wolf RPG, TyranoBuilder, KiriKiri, Unity ... | made with that engine |
| windows, pc, android, linux, mac, switch, mobile ... | released on that platform |
| very short ... very long, not too long | play length |
| after 2015, before 2010, 2018-2022, in 2020, 90s | release date |
| highly rated, popular | rating 7.0+, 500+ votes (adjustable) |
| suggestive, explicit, all ages | content level |
| no X, without X, not X, avoid X, I don't want X | X excluded |
| anything else | VNDB tags, by name, nickname, or close spelling |

Filler words ("I want", "looking for", "ideally", "please") are skipped.

- **Sort** by rating, votes, release date or title.
- **Match: all tags** demands everything you asked for. **Any tag** is looser
  and puts titles that hit the most of your tags first.
- Click **×** on any label to drop it, and the search runs again.
- **how each phrase was read** shows how each part of your sentence was
  matched, handy when a result surprises you.

### Mature content

The **Mature content** switch is off by default and is remembered between
visits.

- **Off:** anything tagged with sexual content is left out, and suggestive or
  violent covers are blurred until you click them.
- **On:** only titles with sexual content are shown, covers are unblurred, and
  their sexual-content tags are listed.

Words like "explicit" or "all ages" in your search take priority over the switch
for that search.

### Preferences

Open **Preferences** under the search bar.

- **Always exclude:** tags to remove from every search, with one list for Mature
  off and one for Mature on. Type a tag name; nicknames and typos are fine. They
  appear as grey labels under your search, and **×** skips one just for that
  search.
- **Not interested:** hover over a cover and click **✕** to hide that title for
  good. You can bring it back from this list.

Preferences are stored in `data/prefs.json` on your own machine.

## Teaching it new words

Nicknames live in `parsing/synonyms.yaml`, a plain text file you can edit:

```yaml
phrases:
  female mc:  { tag: "Female Protagonist" }          # one VNDB tag
  isekai:     { tag: "Protagonist from a Different World" }
  cozy:       { any_tags: ["Slice of Life", "Comedy"] }   # at least one of these
  rpgmaker:   { engine: "RPG Maker" }
```

Tag names must match VNDB exactly; look them up at
[vndb.org/g](https://vndb.org/g). Restart the app after editing. A name that
doesn't exist is reported at startup and skipped.

## Optional extras

Both extras are off by default, and everything works without them.

**Ollama helper for long, chatty requests.** If you have
[Ollama](https://ollama.com) installed, a local model can tidy a rambling
sentence into short keywords before searching. It only rewrites your words; the
search itself still follows the rules above, and you always see the rewritten
text and can edit it.

```sh
ollama pull qwen2.5:7b-instruct    # about 4.7 GB, wants a GPU with 8 GB of memory
```

Then tick **LLM rewrite** in the page, or set `use_llm: true` in `config.yaml`.
If Ollama isn't running, the search simply goes ahead without it.

**Closer guesses for unusual words.** `use_embeddings: true` in `config.yaml`
adds a last-resort matcher for words that have no direct tag match. It needs
`pip install sentence-transformers`.

## Settings

Everything adjustable is in `config.yaml` and commented:
- results per page and default sort
- how strict typo matching is
- whether spoiler tags count
- cover blur levels
- cache duration
- port

## Command line

```sh
python cli.py "highly rated mystery with time loops"
python cli.py "fantasy, english, rpg maker" --sort votecount -n 20 --any
python cli.py "slice of life, one ending" --mature
python cli.py "..." --explain        # show how each phrase was matched
python cli.py --refresh-tags         # re-download the tag list now
```

## Fair use and privacy

- Uses only the official, public [VNDB API](https://api.vndb.org/kana); it does
  not scrape the website.
- Requests are spaced out to stay well inside VNDB's rate limits, and answers
  are cached locally for a day so repeat searches don't touch the server.
- Covers and screenshots load directly from VNDB's image server and are never
  copied or stored.
- Nothing about you leaves your computer except the searches themselves, which
  go to VNDB.

## Credits and license

**Yoru no Toshokan is an unofficial fan project. It is not affiliated with or
endorsed by VNDB.**

- Visual novel data comes from [vndb.org](https://vndb.org) and is available
  under the [Open Database License](https://vndb.org/d17#4). Thanks to the VNDB
  team and contributors for the database and the free API.
- Cover art and screenshots belong to their respective creators and
  publishers.
- The VNDB API is free for non-commercial use, so please keep forks of this
  project free as well.
- The code is released under the [MIT License](LICENSE).

## For developers

```sh
python -m pytest -q          # offline tests
python -m pytest -q --live   # also talk to the real API
```

```
app.py, cli.py, finder.py   web page, command line, shared search pipeline
parsing/                    sentence parsing, synonyms.yaml, optional helpers
query_builder.py            turns parsed criteria into VNDB API filters
details.py                  detail page data
vndb/                       API client (rate limiting, caching), tag list
templates/, static/         the web page (plain HTML, CSS, JavaScript)
docs/api_notes.md           notes on the VNDB API
```
