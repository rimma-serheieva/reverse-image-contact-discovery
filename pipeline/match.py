"""
match.py — reverse-image matching: given a photo, which corpus entry is it?

Technique: perceptual hashing (pHash), computed locally with no paid API and
no face recognition — this project deliberately avoids matching photos of
people (consent and privacy reasons); it matches photos of PLACES, which the
businesses themselves published to be found.

THE HONEST BENCHMARK DESIGN
    A query photo is never byte-identical to the corpus copy in the real
    world — it's been resized, recompressed, cropped, re-shared. So instead
    of matching an image against itself, each evaluation query is a
    DEGRADED copy: resized down and back up, re-encoded at low JPEG quality,
    and lightly cropped. That is the realistic version of "a photo found in
    the wild," and it's the version actually scored.

    Evaluation reports both:
      - whether the nearest corpus entry is the CORRECT one (recall)
      - whether a wrong entry at that distance would have been rejected by
        the chosen threshold (precision) — using every OTHER corpus photo as
        a genuine negative, not a hand-picked easy case.
"""
import io
import os
import random

import imagehash
import requests
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, os.pardir, "data", "images_cache")
UA = "reverse-image-contact-discovery-portfolio-project/1.0"


def _cache_path(qid):
    return os.path.join(CACHE, "%s.jpg" % qid)


def fetch_image(qid, url, tries=4):
    """Download once, cache locally by qid. Returns a PIL Image or None.

    Wikimedia Commons answers a burst of sequential requests with HTTP 429.
    A first version with no backoff lost ~90% of the corpus to this — it
    looked like a data problem but was a missing-retry problem. Honouring
    Retry-After (or backing off hard if it's absent) fixes it; a fixed
    1.5s pace between calls (set by the caller, not here) keeps it from
    tripping the limit in the first place.
    """
    os.makedirs(CACHE, exist_ok=True)
    path = _cache_path(qid)
    if os.path.exists(path):
        try:
            return Image.open(path).convert("RGB"), True   # True = cache hit
        except Exception:
            os.remove(path)
    import time as _time
    for attempt in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
            if r.status_code == 429:
                # Cap this HARD. A server's Retry-After is advice, not a
                # contract — trusting it blindly is what turned "download
                # ~800 images" into a run that stalled for hours on one
                # slow image. A short wait and a limited retry count costs
                # far less than one image blocking the entire corpus.
                wait = min(int(r.headers.get("Retry-After", 5 * (attempt + 1))), 15)
                _time.sleep(wait)
                continue
            if r.status_code == 200 and len(r.content) > 500:
                im = Image.open(io.BytesIO(r.content)).convert("RGB")
                im.save(path, "JPEG", quality=90)
                return im, False
        except Exception:
            pass
        _time.sleep(min(2 * (attempt + 1), 10))
    return None, False


def degrade(im, seed=0):
    """Simulate a photo found in the wild: resized, recompressed, cropped."""
    rnd = random.Random(seed)
    w, h = im.size
    small = im.resize((max(32, w // 3), max(32, h // 3)))
    back = small.resize((w, h))
    # a light crop — a few percent off each edge
    cw, ch = int(w * 0.04), int(h * 0.04)
    cropped = back.crop((cw, ch, w - cw, h - ch))
    buf = io.BytesIO()
    cropped.save(buf, "JPEG", quality=40 + rnd.randint(0, 20))
    buf.seek(0)
    return Image.open(buf)


def build_index(corpus_rows, limit=None):
    """qid -> (phash, name). Downloads and hashes every corpus image."""
    import time as _time
    index = {}
    rows = corpus_rows[:limit] if limit else corpus_rows
    for i, r in enumerate(rows, 1):
        im, from_cache = fetch_image(r["qid"], r["image_url"])
        if im is not None:
            index[r["qid"]] = {"hash": imagehash.phash(im, hash_size=16), "name": r["name"]}
        if i % 25 == 0:
            print("  hashed %d/%d (%d successful)" % (i, len(rows), len(index)), flush=True)
        if not from_cache:
            _time.sleep(1.0)  # only pace real network calls, not cache hits
    return index


def nearest(query_hash, index, exclude=None):
    """Return [(qid, distance), ...] sorted closest first."""
    out = []
    for qid, entry in index.items():
        if qid == exclude:
            continue
        out.append((qid, query_hash - entry["hash"]))
    out.sort(key=lambda x: x[1])
    return out


def evaluate(corpus_rows, index, n_queries=120, seed=7):
    """Run the degraded-query benchmark. Returns a list of result dicts."""
    rnd = random.Random(seed)
    candidates = [r for r in corpus_rows if r["qid"] in index]
    sample = rnd.sample(candidates, min(n_queries, len(candidates)))
    results = []
    for r in sample:
        qid = r["qid"]
        im, _ = fetch_image(qid, r["image_url"])
        if im is None:
            continue
        q_hash = imagehash.phash(degrade(im, seed=hash(qid) % 1000), hash_size=16)
        ranked = nearest(q_hash, index)
        if not ranked:
            continue
        top_qid, top_dist = ranked[0]
        runner_up_dist = ranked[1][1] if len(ranked) > 1 else None
        results.append({
            "true_qid": qid, "true_name": r["name"],
            "matched_qid": top_qid, "matched_name": index[top_qid]["name"],
            "correct": top_qid == qid, "distance": top_dist,
            "runner_up_distance": runner_up_dist,
        })
    return results


def precision_recall(results, thresholds=range(60, 116, 2)):
    """For each candidate threshold: of matches accepted (distance <=
    threshold), what fraction were correct (precision)? Of all true
    positives, what fraction were accepted (recall)?"""
    out = []
    n = len(results)
    for t in thresholds:
        accepted = [r for r in results if r["distance"] <= t]
        correct_accepted = sum(1 for r in accepted if r["correct"])
        precision = correct_accepted / len(accepted) if accepted else None
        recall = correct_accepted / n if n else 0
        out.append({"threshold": t, "accepted": len(accepted),
                    "precision": precision, "recall": recall})
    return out
