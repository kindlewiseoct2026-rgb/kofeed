#!/usr/bin/env python3
"""
বাংলা/ইংরেজি পত্রিকার সাহিত্য-পাতা -> full-text RSS (KOReader News Downloader এর জন্য)
GitHub Actions এ চলে, docs/ ফোল্ডারে XML ফাইল বানায়:
  books.xml  : The Daily Star - Books & Literature
  slow.xml   : The Daily Star - Slow Reads
  bangla.xml : প্রথম আলো, সমকাল, কালের কণ্ঠ, যুগান্তর, আমার দেশ (সব একসাথে)
প্রতিটি আর্টিকেলের শিরোনামের আগে পত্রিকার নাম বসে।
"""
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from urllib.parse import urlparse, urljoin
from xml.sax.saxutils import escape

import requests
from bs4 import BeautifulSoup

OUT_DIR = os.environ.get("OUT_DIR", "docs")
BD = timezone(timedelta(hours=6))
DEBUG = os.environ.get("DEBUG", "1") == "1"


# ---------------------------------------------------------------- লিংক চেনার নিয়ম
def _last(path):
    return path.rstrip("/").rsplit("/", 1)[-1]


def rule_ds_books(p):
    return bool(re.match(r"^/culture/books-literature/[^/]+/[^/]+", p)) and bool(re.search(r"-\d{5,}$", _last(p)))


def rule_ds_slow(p):
    return p.startswith("/slow-reads/") and bool(re.search(r"-\d{5,}$", _last(p)))


def rule_prothomalo(p):
    segs = p.strip("/").split("/")
    if not (2 <= len(segs) <= 4):
        return False
    if segs[0] in {"topic", "author", "video", "photo", "search", "tag", "page", "archive", "english", "e-paper"}:
        return False
    last = segs[-1]
    return bool(re.fullmatch(r"[a-z0-9]{8,14}", last)) and bool(re.search(r"\d", last)) and bool(re.search(r"[a-z]", last))


def rule_samakal(p):
    return "kaler-kheya" in p and bool(re.search(r"\d{5,}", p)) and not p.startswith("/sub/")


def rule_kalerkantho(p):
    return p.startswith("/online/sahitya/") and bool(re.search(r"\d{5,}$", _last(p)))


def rule_jugantor(p):
    return p.startswith("/literature/") and bool(re.search(r"(^|-)\d{5,}$", _last(p)))


def rule_amardesh(p):
    return p.startswith("/literature/") and bool(re.fullmatch(r"amd[a-z0-9]{6,}", _last(p)))


# ---------------------------------------------------------------- সোর্স তালিকা
SOURCES = {
    "ds-books": dict(paper="The Daily Star", names=["The Daily Star"], host="thedailystar.net", rule=rule_ds_books,
                     pages=["https://www.thedailystar.net/culture/books-literature"], n=10),
    "ds-slow": dict(paper="The Daily Star", names=["The Daily Star"], host="thedailystar.net", rule=rule_ds_slow,
                    pages=["https://www.thedailystar.net/slow-reads"], n=10),
    "prothomalo": dict(paper="প্রথম আলো", names=["প্রথম আলো", "Prothom Alo", "Prothomalo"], host="prothomalo.com",
                       rule=rule_prothomalo, n=5,
                       pages=["https://www.prothomalo.com/fun",
                              "https://www.prothomalo.com/onnoalo",
                              "https://www.prothomalo.com/topic/%E0%A6%B8%E0%A6%BE%E0%A6%B9%E0%A6%BF%E0%A6%A4%E0%A7%8D%E0%A6%AF"]),
    "samakal": dict(paper="সমকাল", names=["সমকাল", "Samakal", "দৈনিক সমকাল"], host="samakal.com", rule=rule_samakal,
                    pages=["https://samakal.com/sub/kaler-kheya"], n=5),
    "kalerkantho": dict(paper="কালের কণ্ঠ", names=["কালের কণ্ঠ", "Kaler Kantho", "kalerkantho"], host="kalerkantho.com",
                        rule=rule_kalerkantho, pages=["https://www.kalerkantho.com/online/sahitya"], n=5),
    "jugantor": dict(paper="যুগান্তর", names=["যুগান্তর", "Jugantor"], host="jugantor.com", rule=rule_jugantor,
                     pages=["https://www.jugantor.com/literature"], n=5),
    "amardesh": dict(paper="আমার দেশ", names=["আমার দেশ", "Amar Desh", "Daily Amar Desh", "দৈনিক আমার দেশ"],
                     host="dailyamardesh.com", rule=rule_amardesh, pages=["https://www.dailyamardesh.com/literature"], n=5),
}

OUTPUTS = {
    "books": dict(title="The Daily Star - Books & Literature", link="https://www.thedailystar.net/culture/books-literature",
                  sources=["ds-books"]),
    "slow": dict(title="The Daily Star - Slow Reads", link="https://www.thedailystar.net/slow-reads", sources=["ds-slow"]),
    "bangla": dict(title="বাংলা সাহিত্য (প্রথম আলো, সমকাল, কালের কণ্ঠ, যুগান্তর, আমার দেশ)", link="https://www.prothomalo.com/",
                   sources=["prothomalo", "samakal", "kalerkantho", "jugantor", "amardesh"]),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "bn-BD,bn;q=0.9,en-US;q=0.8,en;q=0.7",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
_page_cache = {}


def log(*a):
    print(*a, flush=True)


def get(url, tries=3):
    if url in _page_cache:
        return _page_cache[url]
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 200:
                r.encoding = "utf-8"
                _page_cache[url] = r.text
                return r.text
            log(f"    HTTP {r.status_code} for {url}")
            if r.status_code in (403, 404, 410):
                break
        except requests.RequestException as e:
            log(f"    error {e} for {url}")
        time.sleep(2 * (i + 1))
    _page_cache[url] = ""
    return ""


# ---------------------------------------------------------------- লিংক সংগ্রহ
def raw_paths(html, host):
    t = html.replace("\\/", "/").replace("\\u002F", "/")
    out = []
    for m in re.finditer(r"https?://(?:www\.)?" + re.escape(host) + r"(/[^\s\"'<>\\)]*)", t):
        out.append(m.group(1))
    for m in re.finditer(r"[\"'](/[A-Za-z0-9_\-/%.]+)[\"']", t):
        out.append(m.group(1))
    return out


def get_links(src, page_url, limit):
    html = get(page_url)
    log(f"  listing {page_url}  ({len(html)} bytes)")
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    cands = []
    for a in soup.find_all("a", href=True):
        full = urljoin(page_url, a["href"].strip())
        p = urlparse(full)
        if p.netloc and src["host"] not in p.netloc:
            continue
        cands.append(p.path)
    cands += [x.split("?")[0].split("#")[0] for x in raw_paths(html, src["host"])]

    pu = urlparse(page_url)
    origin = f"{pu.scheme}://{pu.netloc}"
    links, seen = [], set()
    for path in cands:
        path = path.rstrip("/")
        if not path or path in seen:
            continue
        if src["rule"](path):
            seen.add(path)
            links.append(origin + path)
    log(f"  matched {len(links)} article links")
    if not links and DEBUG:
        sample = []
        for path in cands:
            if path and path not in sample and len(path) > 8:
                sample.append(path)
            if len(sample) >= 25:
                break
        log("  [debug] কোনো লিংক মেলেনি, নমুনা লিংক:")
        for s in sample:
            log("     ", s)
    return links[:limit]


# ---------------------------------------------------------------- আর্টিকেল পার্স
def abs_url(base, u):
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    return urljoin(base, u)


def meta(soup, prop):
    t = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
    return (t.get("content") or "").strip() if t else ""


def parse_date(soup, html):
    d = meta(soup, "article:published_time")
    if not d:
        m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html)
        d = m.group(1) if m else ""
    if d:
        try:
            dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BD)
            return dt
        except ValueError:
            pass
    m = re.search(r"Published\s*:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})", soup.get_text(" "))
    if m:
        try:
            return datetime.strptime(m.group(1), "%d %B %Y").replace(tzinfo=BD)
        except ValueError:
            pass
    return None


SKIP_ANCESTORS = ["footer", "nav", "header", "aside"]


def find_body(soup):
    """আর্টিকেল বডি খোঁজা।
    ১) যে এলিমেন্টের সরাসরি <p> সন্তানদের লেখা সবচেয়ে বেশি (Daily Star ধরনের পেজ)।
    ২) না হলে readability-র মতো স্কোর: প্রতিটি <p> তার বাবা, দাদা ও পরদাদাকে স্কোর দেয়
       (প্রথম আলোর মতো পেজ যেখানে প্রতিটি অনুচ্ছেদ আলাদা wrapper div এ থাকে)।"""
    paras = []
    for p in soup.find_all("p"):
        if p.find_parent(SKIP_ANCESTORS):
            continue
        txt = p.get_text(strip=True)
        if len(txt) >= 20:
            paras.append((p, len(txt)))
    if not paras:
        return None
    total = sum(n for _, n in paras)

    direct = {}
    for p, n in paras:
        e = direct.get(id(p.parent), (p.parent, 0))
        direct[id(p.parent)] = (p.parent, e[1] + n)
    best_d, best_dn = max(direct.values(), key=lambda x: x[1])
    if best_dn >= 0.5 * total:
        return best_d

    score = {}
    for p, n in paras:
        node = p.parent
        for w in (1.0, 0.5, 0.33):
            if node is None or node.name in ("body", "html", "[document]"):
                break
            e = score.get(id(node), (node, 0.0))
            score[id(node)] = (node, e[1] + n * w)
            node = node.parent
    if not score:
        return best_d
    return max(score.values(), key=lambda x: x[1])[0]


def clean_title(title, names):
    title = (title or "").strip()
    for sep in (" | ", " - ", " – ", " — ", " :: "):
        parts = title.split(sep)
        if len(parts) > 1 and any(n.lower() in parts[-1].lower() for n in names):
            title = sep.join(parts[:-1]).strip()
    return title


def parse_article(html, url, src):
    soup = BeautifulSoup(html, "html.parser")

    title = meta(soup, "og:title")
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
    title = clean_title(title, src["names"])
    image = meta(soup, "og:image")
    dt = parse_date(soup, html)

    body = find_body(soup)
    if body is None:
        return None

    # বাড়তি অংশ সরানো
    for t in body.find_all(["script", "style", "iframe", "noscript", "form", "button", "svg", "source"]):
        t.extract()
    for t in body.select('[class*="related"], [class*="share"], [class*="social"], [class*="advert"], '
                         '[class*="newsletter"], [class*="comment"], [class*="tag-list"]'):
        t.extract()
    for d in body.find_all("div", recursive=False):
        txt = d.get_text(" ", strip=True)
        if (not txt and not d.find("img")) or "trusted source" in txt.lower() or "Google News" in txt:
            d.extract()

    # lazy ছবি: span/div এ data-src আছে কিন্তু img নেই
    for w in body.find_all(["span", "div"], attrs={"data-src": True}):
        if not w.find("img"):
            img = soup.new_tag("img")
            img["src"] = abs_url(url, w["data-src"])
            w.append(img)

    for d in body.find_all("div"):
        if d.parent is None:
            continue
        txt = d.get_text(strip=True)
        if not d.find(True) and txt == "Image":
            d.extract()
        elif any(a.get_text(strip=True) == "Read more" for a in d.find_all("a")) and not d.find("p"):
            d.extract()
    for bq in body.find_all("blockquote"):
        if bq.find("h2"):
            bq.extract()
    for p in body.find_all("p"):
        if "Send your articles for" in p.get_text():
            p.extract()
    for pic in body.find_all("picture"):
        if not pic.find("img"):
            pic.extract()

    # ছবি ও লিংক ঠিক করা
    for img in body.find_all("img"):
        s = img.get("data-src") or img.get("data-original") or img.get("src") or ""
        if not s or s.startswith("data:"):
            img.extract()
            continue
        img["src"] = abs_url(url, s)
    for a in body.find_all("a", href=True):
        a["href"] = abs_url(url, a["href"])

    keep = {"href", "src", "alt", "dir"}
    for t in body.find_all(True):
        t.attrs = {k: v for k, v in t.attrs.items() if k in keep}

    for _ in range(3):  # খালি div মুছে ফেলা
        for d in body.find_all("div"):
            if d.parent is not None and not d.get_text(strip=True) and not d.find("img"):
                d.extract()

    content = "".join(str(c) for c in body.contents).strip()
    if len(re.sub(r"<[^>]+>", "", content)) < 60 or not title:
        return None
    return {"title": title, "image": image, "dt": dt, "content": content, "url": url, "paper": src["paper"]}


# ---------------------------------------------------------------- RSS তৈরি
def cdata(s):
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def build_rss(out_cfg, items):
    now = datetime.now(BD)
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        "<channel>",
        f"<title>{escape(out_cfg['title'])}</title>",
        f"<link>{escape(out_cfg['link'])}</link>",
        f"<description>{escape(out_cfg['title'])} (full articles)</description>",
        "<language>bn</language>",
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>",
    ]
    for i, a in enumerate(items):
        dt = a["dt"] or (now - timedelta(minutes=i))
        body = a["content"]
        if a["image"] and "<img" not in body:
            body = f'<p><img src="{escape(a["image"])}" /></p>' + body
        full_title = f"{a['paper']} – {a['title']}"
        out += [
            "<item>",
            f"<title>{escape(full_title)}</title>",
            f"<link>{escape(a['url'])}</link>",
            f'<guid isPermaLink="true">{escape(a["url"])}</guid>',
            f"<pubDate>{format_datetime(dt)}</pubDate>",
            f"<description>{cdata(body)}</description>",
            f"<content:encoded>{cdata(body)}</content:encoded>",
            "</item>",
        ]
    out += ["</channel>", "</rss>", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- মেইন
def collect(src_key):
    src = SOURCES[src_key]
    log(f"[{src_key}] {src['paper']}")
    urls, seen = [], set()
    for page in src["pages"]:
        for u in get_links(src, page, src["n"]):
            if u not in seen:
                seen.add(u)
                urls.append(u)
    items = []
    for u in urls:
        time.sleep(1)
        html = get(u)
        if not html:
            continue
        a = parse_article(html, u, src)
        if a:
            items.append(a)
            log(f"    ok: {a['title'][:60]}")
        else:
            log(f"    skipped (no body): {u}")
    log(f"[{src_key}] {len(items)} articles")
    return items


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    ok = 0
    for out_key, cfg in OUTPUTS.items():
        per_source = [collect(k) for k in cfg["sources"]]
        # সোর্সগুলো ঘুরিয়ে ঘুরিয়ে সাজানো, যাতে limit দিলেও সব পত্রিকা থেকে কিছু কিছু আসে
        items = []
        for i in range(max((len(x) for x in per_source), default=0)):
            for lst in per_source:
                if i < len(lst):
                    items.append(lst[i])
        if items:
            with open(os.path.join(OUT_DIR, f"{out_key}.xml"), "w", encoding="utf-8") as f:
                f.write(build_rss(cfg, items))
            log(f"==> {out_key}.xml written ({len(items)} items)")
            ok += 1
        else:
            log(f"==> {out_key}: no items, keeping old file")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
