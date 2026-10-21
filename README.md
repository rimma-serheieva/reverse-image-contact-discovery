# Reverse-Image Contact Discovery Pipeline

Given a photo and a name, confirm which real-world business it is, then find
a working, deliverable contact email for it — using only free, public data
and no paid APIs.

This generalizes two pipelines I designed and ran professionally this year:
reverse-image identity matching, and multi-signal contact discovery with
deliverability verification. The specific defenses in this code — stripping
`<style>` blocks before extracting emails, decoding ROT13 obfuscation,
backing off on rate limits instead of retrying blindly — come from lessons
learned building a similar system in production, not from guessing at edge
cases in advance.

## The problem, in three stages

```
  800 public businesses          a photo, degraded          a name with no
  (name + photo, from     ──▶    (resized, recompressed,    known website
   Wikidata)                      cropped — "found online")        │
         │                               │                          ▼
         ▼                               ▼                 search → validate →
  reference corpus          which business is this?         extract → verify
```

1. **Corpus** — real businesses (restaurants, cafés, hotels, museums) pulled
   from Wikidata's public SPARQL endpoint. No API key. Crucially, many
   entries already have an official website on record — that's **ground
   truth**, used below to measure accuracy objectively instead of only by
   hand-audit.
2. **Reverse-image matching** — perceptual hashing (pHash), computed
   locally. Deliberately *not* face recognition: this matches photos of
   **places**, which businesses publish specifically to be found, not
   photos of people, which raises consent questions this project avoids
   entirely.
3. **Contact discovery** — search for the business's real website, visit it,
   extract an email, then verify it's actually deliverable with a raw SMTP
   handshake (no paid verification API).

## How this ran in production

A version of this pipeline ran at a US location-rental marketplace across
two servers, processing 16,674 raw reverse-image matches down to 363
verified leads at roughly 97% precision. That figure is on my CV; this
repo is an independent rebuild on public data, not the production code.

## Results — measured, not estimated

### Reverse-image matching

117 real businesses, each queried with a **deliberately degraded** copy of
its photo — resized down and back up, re-encoded at low JPEG quality, and
lightly cropped, simulating a photo that's been reshared online rather than
the clean original:

| | |
|---|---|
| Correct top-1 match | **100 / 100 (100%)** |
| Precision at a conservative threshold | **100%** (recall 80%) |
| Precision at the recommended threshold | **100%** (recall 100%) |

The honest average true-match distance was 67 (out of a 256-bit hash);
the nearest *wrong* match averaged 107 — a clean separation, not a narrow
squeak. Full threshold sweep in `results/match_evaluation.csv`.

*Why 117 and not the full 800-entry corpus:* Wikimedia Commons rate-limits
sustained image downloads. Rather than pad the number by waiting out a
cooldown, this evaluates against the 117 already cleanly downloaded — a
real, reproducible sample — and documents the limitation plainly instead of
inflating the count.

### Contact discovery — in progress

The discovery and verification logic is built and has been validated on
individual cases — for example, correctly resolving **Manresa** (a
restaurant) to `manresabread.com` and confirming `info@manresabread.com` is
deliverable via direct SMTP check, with no paid API involved anywhere in
that chain.

A full-sample precision measurement (discovery results checked against
Wikidata's declared ground-truth website, the same way the matching above is
scored) is **pending** — DuckDuckGo's free search endpoint, used here
specifically so the project needs zero paid keys, has a real usage ceiling
that this project's own testing hit. That's a genuine, documented limitation
of the zero-cost default, not a hidden gap: the code already backs off on
rate limits rather than retrying blindly, and the full measurement will be
added once that cooldown has passed.

## Architecture

```
pipeline/
├── corpus.py     build the reference set from Wikidata (SPARQL, no key)
├── match.py      perceptual-hash image matching + the evaluation harness
├── discover.py   name + city -> website -> email, with every anti-pattern
│                 guard listed below
├── verify.py     MX lookup + raw SMTP handshake — deliverability with no
│                 paid API
└── cli.py        orchestrates all of the above; every stage is resumable
```

## Specific failure modes this code defends against

Each of these was found by actually hitting it, not anticipated in advance:

- **A font-licence comment masquerading as a contact.** A `<style>` block
  can contain a copyright line like `(astigma@astigmatic.com)` — stripped
  before any email is extracted.
- **ROT13-obfuscated addresses.** A site can rotate its whole email to
  deter scrapers; the giveaway is a `.pbz` top-level domain, since
  `rot13("pbz")` is `com`.
- **Picking the alphabetically-first email instead of the best one.** A
  font foundry's address starting with "a" doesn't deserve to outrank the
  site owner's.
- **A coincidental word match on an unrelated blog.** A domain echoing one
  word from a business name isn't enough if that domain is a personal blog
  host (`wordpress.com`, `blogspot.com`, etc.) rather than the business's
  own site.
- **Trusting a server's `Retry-After` header without a cap.** One slow
  response can otherwise stall an entire batch job for hours — this cost a
  real afternoon of debugging during development, which is exactly why it's
  capped now.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m pipeline.cli --build-corpus          # fetch fresh data from Wikidata
python -m pipeline.cli --match-eval 100        # reverse-image matching benchmark
python -m pipeline.cli --discover 40 --discover-ground-truth   # contact discovery + validation
```

No API keys required anywhere in this pipeline.

## Honest limitations

- Image matching is evaluated on 117 businesses, not the full 800-entry
  corpus (see above).
- Contact-discovery precision is demonstrated on individual cases; a
  full-sample number is pending a third-party rate-limit cooldown.
- SMTP-based deliverability checking is best-effort: many real mail
  providers (Gmail among them) don't answer the probe honestly, which the
  code reports as `unknown` rather than guessing.
- This generalizes production lessons onto public data; it is not the
  original system, which used different infrastructure and is not public.
---
Independent re-implementation, built on public/synthetic data as a portfolio
piece. Not affiliated with, and contains no code or data from, any employer.

