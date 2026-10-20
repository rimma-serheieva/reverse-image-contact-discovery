# Reverse-Image Contact Discovery Pipeline

🚧 **Work in progress** — this README will be replaced with the full writeup,
results and metrics as each stage is built. The repo link below will not change.

## What this will do

Given only a photo of a business storefront and a partial name, resolve:
1. **Identity** — match the photo against a reference set to confirm which real
   business it is (local image-similarity matching, no paid API)
2. **Contact** — find that business's real website and a validated, deliverable
   email address

Built entirely on public, openly-licensed data (OpenStreetMap / Wikimedia
Commons) — no private company data, no scraped personal photos of individuals.

## Why

This generalizes two pipelines I designed and ran end-to-end this year:
reverse-image identity matching, and multi-signal contact-discovery with
deliverability verification. Full writeup coming with real measured results
(precision on a hand-labeled validation set, not just a raw hit rate).

## Status
- [ ] Reference corpus built from public business listings
- [ ] Image-similarity matching + validated
- [ ] Contact discovery + deliverability check
- [ ] Results and methodology documented below
