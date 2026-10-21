"""
cli.py — run the full pipeline end to end and write results + metrics.

    python -m pipeline.cli --build-corpus      # fetch fresh data from Wikidata
    python -m pipeline.cli --match-eval 120     # reverse-image matching benchmark
    python -m pipeline.cli --discover 150       # contact discovery + validation
    python -m pipeline.cli --all                # everything, in order

Every stage is resumable: discovery checkpoints to results/*.csv as it goes,
so interrupting it and re-running the same command picks up where it left
off instead of re-spending time on rows already done.
"""
import argparse
import csv
import json
import os
import time

import requests

from pipeline import corpus, discover as discover_mod, match, verify

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, os.pardir, "data")
RESULTS = os.path.join(HERE, os.pardir, "results")
CORPUS_CSV = os.path.join(DATA, "corpus.csv")


def load_corpus():
    with open(CORPUS_CSV, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def run_match_eval(n_queries):
    rows = load_corpus()
    print("building image-hash index for %d corpus entries..." % len(rows), flush=True)
    index = match.build_index(rows)
    print("%d images hashed successfully\n" % len(index), flush=True)

    print("running the degraded-query benchmark (%d queries)..." % n_queries, flush=True)
    results = match.evaluate(rows, index, n_queries=n_queries)
    pr = match.precision_recall(results)

    out = os.path.join(RESULTS, "match_evaluation.csv")
    os.makedirs(RESULTS, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["true_qid", "true_name", "matched_qid",
                                           "matched_name", "correct", "distance",
                                           "runner_up_distance"])
        w.writeheader()
        w.writerows(results)

    correct = sum(1 for r in results if r["correct"])
    print("\n--- image matching: %d queries ---" % len(results), flush=True)
    print("  correct top-1 match: %d (%.0f%%)" % (correct, 100 * correct / len(results)), flush=True)
    print("\n  threshold sweep (distance <= t accepted):", flush=True)
    print("  %6s %10s %10s %8s" % ("thresh", "accepted", "precision", "recall"), flush=True)
    for row in pr:
        p = "%.0f%%" % (100 * row["precision"]) if row["precision"] is not None else "-"
        print("  %6d %10d %10s %7.0f%%" % (row["threshold"], row["accepted"], p,
                                           100 * row["recall"]))
    print("\n  %s" % out, flush=True)
    return results, pr


def run_discover(n, mode):
    """mode: 'missing' (the real target population) or 'ground_truth'
    (entries that already have a declared website, used to measure
    precision objectively instead of only by hand-audit)."""
    rows = load_corpus()
    rows = [r for r in rows if bool(r["declared_website"]) == (mode == "ground_truth")]
    rows = rows[:n] if n else rows

    out = os.path.join(RESULTS, "discovery_%s.csv" % mode)
    done = set()
    if os.path.exists(out):
        done = {r["qid"] for r in csv.DictReader(open(out, encoding="utf-8"))}
    todo = [r for r in rows if r["qid"] not in done]
    print("%d rows selected, %d already done, %d to run\n" % (len(rows), len(done), len(todo)), flush=True)

    new = not os.path.exists(out)
    os.makedirs(RESULTS, exist_ok=True)
    fh = open(out, "a", newline="", encoding="utf-8")
    cols = ["qid", "name", "category", "declared_website", "found_website",
            "domain", "confidence", "email", "all_emails",
            "matches_declared", "delivery_status", "delivery_note"]
    w = csv.DictWriter(fh, fieldnames=cols)
    if new:
        w.writeheader()

    session = requests.Session()
    for i, r in enumerate(todo, 1):
        res = discover_mod.discover(r["name"], r.get("city", ""), session)
        matches_declared = ""
        if r["declared_website"] and res["website"]:
            from pipeline.discover import domain_of
            matches_declared = str(domain_of(r["declared_website"]) == res["domain"])
        d_status, d_note = ("", "")
        if res["email"]:
            d_status, d_note = verify.check(res["email"])
        row = {"qid": r["qid"], "name": r["name"], "category": r["category"],
               "declared_website": r["declared_website"],
               "found_website": res["website"], "domain": res["domain"],
               "confidence": res["confidence"], "email": res["email"],
               "all_emails": "; ".join(res["all_emails"]),
               "matches_declared": matches_declared,
               "delivery_status": d_status, "delivery_note": d_note}
        w.writerow(row)
        fh.flush()
        print("  [%3d/%3d] %-30s %-22s %-10s %s" % (
            i, len(todo), r["name"][:30], res["domain"] or "-", d_status or "-",
            res["email"] or res["confidence"][:30]))
        time.sleep(3.0)      # paced to avoid tripping DuckDuckGo's own rate limit
    fh.close()
    print("\n%s" % out, flush=True)
    summarize_discovery(out)


def summarize_discovery(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    n = len(rows)
    if not n:
        return
    with_gt = [r for r in rows if r["declared_website"]]
    found_site = sum(1 for r in rows if r["found_website"])
    found_email = sum(1 for r in rows if r["email"])
    correct_vs_gt = sum(1 for r in with_gt if r["matches_declared"] == "True")
    print("\n--- contact discovery: %d businesses ---" % n, flush=True)
    print("  website found: %d (%.0f%%)" % (found_site, 100 * found_site / n), flush=True)
    print("  email found  : %d (%.0f%%)" % (found_email, 100 * found_email / n), flush=True)
    if with_gt:
        print("\n  of %d with a KNOWN real website (ground truth):" % len(with_gt), flush=True)
        print("  pipeline found the SAME website: %d (%.0f%%)  <- real precision"
              % (correct_vs_gt, 100 * correct_vs_gt / len(with_gt)))
    delivered = [r for r in rows if r["delivery_status"]]
    if delivered:
        from collections import Counter
        c = Counter(r["delivery_status"] for r in delivered)
        print("\n  deliverability (%d emails checked):" % len(delivered), flush=True)
        for k, v in c.most_common():
            print("    %-14s %3d" % (k, v), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-corpus", action="store_true")
    ap.add_argument("--match-eval", type=int, default=0)
    ap.add_argument("--discover", type=int, default=0)
    ap.add_argument("--discover-ground-truth", action="store_true",
                    help="run discovery on entries that ALREADY have a declared website, to measure precision")
    args = ap.parse_args()

    if args.build_corpus:
        corpus.build()
    if args.match_eval:
        run_match_eval(args.match_eval)
    if args.discover:
        mode = "ground_truth" if args.discover_ground_truth else "missing"
        run_discover(args.discover, mode)


if __name__ == "__main__":
    main()
