"""
discover.py — given a business name and location, find its real website and
a contact email on it. No paid API: search runs against DuckDuckGo's HTML
endpoint, which needs no key and no account.

Every rule below exists because an earlier, cruder version of it produced a
specific wrong answer. They're kept as comments because the failure is the
point — a plausible-looking email is worse than none, since it sends outreach
to the wrong place.
"""
import codecs
import re
import time
import urllib.parse

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# Directories, map/booking platforms, and social networks: a search result
# landing here is never the business's own site, no matter how well the name
# matches — a generic-sounding name can rank a directory above the real site.
AGGREGATORS = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "tiktok.com", "pinterest.com", "yelp.com", "tripadvisor.com",
    "google.com", "maps.google.com", "bing.com", "wikipedia.org",
    "opentable.com", "resy.com", "doordash.com", "ubereats.com", "grubhub.com",
    "booking.com", "expedia.com", "hotels.com", "tripadvisor.co.uk",
    "yellowpages.com", "mapquest.com", "foursquare.com", "zomato.com",
    "eventbrite.com", "cvent.com",
    # blog/personal-site HOSTS: a fan post or review living on someone's
    # free blog can still contain a distinctive word from the business
    # name, which is how "Pat's Hubba Hubba" (a real restaurant) matched
    # phubba.wordpress.com (an unrelated blog) before this existed. The
    # domain-echo rule alone isn't enough when the host is this generic.
    "wordpress.com", "blogspot.com", "tumblr.com", "medium.com",
    "substack.com", "wixsite.com", "weebly.com", "blogger.com",
}

STOP = {"the", "a", "an", "at", "in", "on", "of", "and", "for", "by",
        "restaurant", "cafe", "hotel", "museum", "inn", "house", "co",
        "llc", "inc", "bar", "grill", "kitchen", "room", "center", "centre"}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Addresses that were real matches in the HTML but belong to someone other
# than the business: a font license comment, a site-builder's own support
# line, a template placeholder.
JUNK_LOCAL = ("sentry", "wixpress", "noreply", "no-reply", "mailer-daemon",
              "postmaster", "webmaster", "admin@squarespace", "support@wix")
JUNK_DOMAIN = ("example.com", "domain.com", "yourdomain.com", "mysite.com",
              "mystore.com", "sentry.io", "wixpress.com")


def domain_of(url):
    d = urllib.parse.urlparse(url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def tokens_of(name):
    return [w for w in re.findall(r"[a-z0-9]+", (name or "").lower())
            if w not in STOP and len(w) > 2]


def search_ddg(query, session, tries=3):
    """DuckDuckGo's no-JS HTML endpoint. Returns a list of result URLs in
    the order DuckDuckGo ranked them.

    Needs no key or account, which is why this project defaults to it — but
    "no key" does not mean "no limit." Sustained use (this project hit it
    during its own testing) gets a 403 for a while. That is a genuine,
    worth-documenting limitation of the zero-cost default, not a bug: back
    off hard and let it recover rather than hammer it, and expect a live
    run against many businesses to need real pacing, not instant results.
    """
    for attempt in range(tries):
        try:
            r = session.post("https://html.duckduckgo.com/html/", data={"q": query},
                             headers={"User-Agent": UA}, timeout=20)
            if r.status_code == 403:
                time.sleep(30 * (attempt + 1))
                continue
            if r.status_code != 200:
                time.sleep(3)
                continue
            urls = []
            for m in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)"', r.text):
                u = m.group(1)
                if "uddg=" in u:
                    u = urllib.parse.unquote(urllib.parse.parse_qs(
                        urllib.parse.urlparse(u).query).get("uddg", [""])[0])
                if u.startswith("http"):
                    urls.append(u)
            return urls
        except requests.RequestException:
            time.sleep(3)
    return []


def find_website(name, city, session):
    """-> (url, domain, how_confident).

    Accepts a candidate ONLY when the domain itself echoes a distinctive word
    from the business name. A weaker rule — "the name's words appear
    somewhere on the page" — was tried first and failed: a generic name
    ("Downtown Cafe") matches almost any local competitor's page too, and a
    national chain's page often outranks the one real small business sharing
    its generic name. The domain-echo rule is stricter but was the only one
    that held up under a real audit.
    """
    tok = tokens_of(name)
    if not tok:
        return None, "", "name has no distinctive word"
    q = '"%s" %s official site' % (name, city or "")
    urls = search_ddg(q, session)
    for u in urls:
        d = domain_of(u)
        if not d or any(d == a or d.endswith("." + a) for a in AGGREGATORS):
            continue
        bare = re.sub(r"[^a-z0-9]", "", d.split(".")[0])
        for t in tok:
            if len(t) >= 4 and t in bare:
                return u, d, "domain carries '%s'" % t
    return None, "", "no candidate's domain echoed the name"


def strip_code(html_text):
    """Remove <style> and <script> before looking for emails — a font
    licence embedded in a <style> block ("Copyright ... DBA Astigmatic
    (astigma@astigmatic.com)") was returned as a business's contact email
    before this existed."""
    t = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", html_text or "")
    return re.sub(r"(?is)<script[^>]*>.*?</script>", " ", t)


def tidy_email(e):
    """URL-decode a mailto href, and undo whole-address ROT13 — its tell is
    a ".pbz" top-level domain, since no such TLD exists and rot13("pbz")
    is "com"."""
    e = urllib.parse.unquote(e).strip().strip(".,;:<>\"'()[]").lower()
    if e.endswith(".pbz"):
        rot = codecs.encode(e, "rot13")
        if re.match(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.(com|net|org|co|io)$", rot):
            return rot
    return e


def pick_best(emails, name, domain):
    """Rank candidates instead of picking the alphabetically-first one — an
    alphabetical pick is how a font foundry's address once beat the actual
    site owner's email for a business named with an early-alphabet word."""
    tok = tokens_of(name)

    def score(e):
        local, _, d = e.partition("@")
        s = 0
        if domain and domain in d:
            s -= 3
        if local in ("info", "hello", "contact", "hi", "admin"):
            s += 2       # a generic mailbox is a fallback, not a first choice
        return (s, e)
    return sorted(emails, key=score)[0] if emails else ""


def emails_on_site(url, session):
    found = {}
    base = url.rstrip("/")
    pages = [url] + [base + p for p in ("/contact", "/contact-us", "/about")]
    for p in pages[:4]:
        try:
            r = session.get(p, headers={"User-Agent": UA}, timeout=15)
            if r.status_code >= 400:
                continue
            for e in set(EMAIL_RE.findall(strip_code(r.text))):
                el = tidy_email(e)
                if (5 < len(el) < 60
                        and not any(j in el for j in JUNK_LOCAL)
                        and not any(el.endswith(j) or j in el for j in JUNK_DOMAIN)):
                    found.setdefault(el, p)
        except requests.RequestException:
            pass
        time.sleep(0.4)
        if found:
            break
    return found


def discover(name, city, session=None):
    """Full stage: name + city -> (website, domain, confidence, email,
    all_emails_found)."""
    session = session or requests.Session()
    url, domain, conf = find_website(name, city, session)
    if not url:
        return {"website": "", "domain": "", "confidence": conf,
                "email": "", "all_emails": []}
    emails = emails_on_site(url, session)
    best = pick_best(list(emails), name, domain)
    return {"website": url, "domain": domain, "confidence": conf,
            "email": best, "all_emails": sorted(emails)}
