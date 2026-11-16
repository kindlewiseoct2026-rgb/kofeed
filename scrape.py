#!/usr/bin/env python3
"""
The Daily Star -> full-text RSS (for KOReader News Downloader).
GitHub Actions এ চলে, docs/books.xml ও docs/slow.xml বানায়।
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

BASE = "https://www.thedailystar.net"
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "10"))
OUT_DIR = os.environ.get("OUT_DIR", "docs")
BD = timezone(timedelta(hours=6))

FEEDS = {
    "books": {
        "title": "The Daily Star - Books & Literature",
        "url": BASE + "/culture/books-literature",
        "pattern": re.compile(r"^/culture/books-literature/[^/?#\s]+/[^/?#\s]+"),
    },
    "slow": {
        "title": "The Daily Star - Slow Reads",
        "url": BASE + "/slow-reads",
        "pattern": re.compile(r"^/slow-reads/[^?#\s]+"),
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def get(url, tries=3):
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r.text
            print(f"  HTTP {r.status_code} for {url}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  error {e} for {url}", file=sys.stderr)
        time.sleep(2 * (i + 1))
    return ""


def abs_url(u):
    u = (u or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    return urljoin(BASE + "/", u)


def get_links(feed):
    html = get(feed["url"])
    soup = BeautifulSoup(html, "html.parser")
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        p = urlparse(a["href"].strip())
        if p.netloc and "thedailystar.net" not in p.netloc:
            continue
        path = p.path.rstrip("/")
        if not path or not feed["pattern"].match(path):
            continue
        if not re.search(r"-\d{5,}$", path.rsplit("/", 1)[-1]):
            continue  # শুধু আসল আর্টিকেল (শেষে আইডি থাকে)
        if path not in seen:
            seen.add(path)
            links.append(BASE + path)
    return links


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


def find_body(soup):
    """যে এলিমেন্টের সরাসরি <p> সন্তানদের লেখা সবচেয়ে বেশি সেটাই আর্টিকেল বডি।"""
    best, best_len = None, 0
    for tag in soup.find_all(True):
        if tag.name in ("footer", "nav", "header", "aside"):
            continue
        if tag.find_parent(["footer", "nav", "header", "aside"]):
            continue
        n = sum(len(p.get_text(strip=True)) for p in tag.find_all("p", recursive=False))
        if n > best_len:
            best, best_len = tag, n
    return best


def parse_article(html, url):
    soup = BeautifulSoup(html, "html.parser")

    title = meta(soup, "og:title")
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
    title = re.sub(r"\s*\|\s*The Daily Star\s*$", "", title, flags=re.I).strip()
    image = meta(soup, "og:image")
    dt = parse_date(soup, html)

    body = find_body(soup)
    if body is None:
        return None

    # বাড়তি অংশ সরানো
    for t in body.find_all(["script", "style", "iframe", "noscript", "form", "button", "svg", "source"]):
        t.extract()
    for d in body.find_all("div", recursive=False):
        txt = d.get_text(" ", strip=True)
        if (not txt and not d.find("img")) or "trusted source" in txt.lower() or "Google News" in txt:
            d.extract()

    # lazy ছবি: span/div এ data-src আছে কিন্তু img নেই
    for w in body.find_all(["span", "div"], attrs={"data-src": True}):
        if not w.find("img"):
            img = soup.new_tag("img")
            img["src"] = abs_url(w["data-src"])
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
        src = img.get("data-src") or img.get("data-original") or img.get("src") or ""
        if not src or src.startswith("data:"):
            img.extract()
            continue
        img["src"] = abs_url(src)
    for a in body.find_all("a", href=True):
        a["href"] = abs_url(a["href"])

    # অপ্রয়োজনীয় অ্যাট্রিবিউট বাদ
    keep = {"href", "src", "alt", "dir"}
    for t in body.find_all(True):
        t.attrs = {k: v for k, v in t.attrs.items() if k in keep}

    for _ in range(3):  # খালি div মুছে ফেলা
        for d in body.find_all("div"):
            if d.parent is not None and not d.get_text(strip=True) and not d.find("img"):
                d.extract()

    content = "".join(str(c) for c in body.contents).strip()

    if len(re.sub(r"<[^>]+>", "", content)) < 100:
        return None
    return {"title": title, "image": image, "dt": dt, "content": content, "url": url}


def cdata(s):
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def build_rss(feed, items):
    now = datetime.now(BD)
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">',
        "<channel>",
        f"<title>{escape(feed['title'])}</title>",
        f"<link>{escape(feed['url'])}</link>",
        f"<description>{escape(feed['title'])} (full articles)</description>",
        "<language>en</language>",
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>",
    ]
    for i, a in enumerate(items):
        dt = a["dt"] or (now - timedelta(minutes=i))
        body = a["content"]
        if a["image"] and "<img" not in body:
            body = f'<p><img src="{escape(a["image"])}" /></p>' + body
        out += [
            "<item>",
            f"<title>{escape(a['title'])}</title>",
            f"<link>{escape(a['url'])}</link>",
            f'<guid isPermaLink="true">{escape(a["url"])}</guid>',
            f"<pubDate>{format_datetime(dt)}</pubDate>",
            f"<description>{cdata(body)}</description>",
            f"<content:encoded>{cdata(body)}</content:encoded>",
            "</item>",
        ]
    out += ["</channel>", "</rss>", ""]
    return "\n".join(out)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    ok = 0
    for key, feed in FEEDS.items():
        print(f"[{key}] listing {feed['url']}")
        links = get_links(feed)[:MAX_ITEMS]
        print(f"[{key}] {len(links)} links")
        items = []
        for u in links:
            time.sleep(1)
            html = get(u)
            if not html:
                continue
            a = parse_article(html, u)
            if a and a["title"]:
                items.append(a)
                print(f"  ok: {a['title'][:70]}")
            else:
                print(f"  skipped (no body): {u}", file=sys.stderr)
        if items:
            with open(os.path.join(OUT_DIR, f"{key}.xml"), "w", encoding="utf-8") as f:
                f.write(build_rss(feed, items))
            ok += 1
        else:
            print(f"[{key}] no items, keeping old file", file=sys.stderr)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
