"""MkDocs hook: each page says what it is, who publishes it, and when it changed.

Two gaps an audit of the site found. Every page shared one hand-written
block describing the software — stuck at version 0.7.2 for months — so an
engine comparing it to the visible text read each page as incoherent. And no
page carried a date, which loses by default to any dated source.

Each page now gets its own structured data: a TechArticle (or the type its
front matter names in ``schema_type``) with its title, description, URL and
the dates of its *source* file in git, linked to one publisher, one website
and the software, whose version is read from ``pyproject.toml``. The last
change date is also shown at the foot of the page.

``robots.txt`` and ``llms.txt`` write ``{site_url}`` for the site's address,
filled in here from ``mkdocs.yml``, so moving the site is one line.

After the build, every page is checked as a crawler will receive it: a page
without its block, with a block that does not parse, or missing a field,
fails the build. So does a robots or llms file not pointing at the site.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from mkdocs.exceptions import PluginError

ROOT = Path(__file__).resolve().parent.parent
ORG = "https://roomi-fields.com/#organization"
REQUIRED = ("@type", "headline", "description", "url", "dateModified",
            "publisher", "isPartOf", "about")
FILLED = ("robots.txt", "llms.txt")
# Built pages that are not documentation.
EXEMPT = {"404.html"}

_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _git_date(src: Path, first: bool = False) -> str | None:
    args = ["git", "log", "--format=%cs"]
    if first:
        args += ["--follow", "--diff-filter=A"]
    else:
        args += ["-1"]
    try:
        out = subprocess.run(args + ["--", str(src)], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return None
    return (out[-1] if first else out[0]) if out else None


def _version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version = "([^"]+)"', text, re.M).group(1)


def _site_nodes(site: str, description: str) -> list[dict]:
    return [
        {
            "@type": "Organization", "@id": ORG,
            "name": "roomi-fields", "url": "https://roomi-fields.com",
            "founder": {"@type": "Person", "name": "Romain Peyrichou",
                        "url": "https://github.com/roomi-fields"},
            "sameAs": ["https://github.com/roomi-fields"],
        },
        {
            "@type": "WebSite", "@id": f"{site}#website",
            "url": site, "name": "RTFM documentation", "inLanguage": "en",
            "publisher": {"@id": ORG},
        },
        {
            "@type": "SoftwareApplication", "@id": f"{site}#software",
            "name": "RTFM", "alternateName": "rtfm-ai",
            "description": description,
            "applicationCategory": "DeveloperApplication",
            "operatingSystem": "Linux, macOS, Windows",
            "softwareVersion": _version(),
            "license": "https://opensource.org/licenses/MIT",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "downloadUrl": "https://pypi.org/project/rtfm-ai/",
            "codeRepository": "https://github.com/roomi-fields/rtfm",
            "programmingLanguage": "Python",
            "publisher": {"@id": ORG},
        },
    ]


def on_page_content(content, page, config, files):
    src = Path(config["docs_dir"]) / page.file.src_path
    modified = _git_date(src)
    page.meta["_modified"] = modified
    page.meta["_published"] = _git_date(src, first=True)
    if modified:
        content += (f'\n<aside class="md-source-file"><small>Last updated: '
                    f'<time datetime="{modified}">{modified}</time></small></aside>')
    return content


def on_post_page(output, page, config):
    site = config["site_url"]
    node = {
        "@type": page.meta.get("schema_type", "TechArticle"),
        "@id": f"{page.canonical_url}#page",
        "headline": page.meta.get("title") or page.title,
        "description": " ".join(str(page.meta.get("description", "")).split()),
        "url": page.canonical_url,
        "inLanguage": "en",
        "dateModified": page.meta.get("_modified"),
        "datePublished": page.meta.get("_published"),
        "publisher": {"@id": ORG},
        "isPartOf": {"@id": f"{site}#website"},
        "about": {"@id": f"{site}#software"},
    }
    node = {k: v for k, v in node.items() if v}
    graph = {"@context": "https://schema.org",
             "@graph": _site_nodes(site, config["site_description"].strip()) + [node]}
    block = ('<script type="application/ld+json">'
             + json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
             + "</script>")
    return output.replace("</head>", block + "\n</head>", 1)


def on_post_build(config):
    site_dir = Path(config["site_dir"])
    problems = []
    for name in FILLED:
        path = site_dir / name
        text = path.read_text(encoding="utf-8").replace("{site_url}", config["site_url"])
        path.write_text(text, encoding="utf-8")
        if config["site_url"] not in text:
            problems.append(f"{name}: does not point at {config['site_url']}")

    checked = 0
    for page in sorted(site_dir.rglob("*.html")):
        rel = page.relative_to(site_dir).as_posix()
        if rel in EXEMPT:
            continue
        text = page.read_text(encoding="utf-8")
        if 'http-equiv="refresh"' in text:
            continue                       # a redirect stub, not a page
        blocks = _LD.findall(text)
        if not blocks:
            problems.append(f"{rel}: no structured data")
            continue
        try:
            graph = json.loads(blocks[-1])
        except json.JSONDecodeError as exc:
            problems.append(f"{rel}: structured data does not parse — {exc}")
            continue
        own = graph.get("@graph", [{}])[-1]
        missing = [f for f in REQUIRED if not own.get(f)]
        if missing:
            problems.append(f"{rel}: page block lacks {', '.join(missing)}")
        checked += 1
    if problems:
        raise PluginError("Pages a crawler would misread:\n  " + "\n  ".join(problems))
    print(f"INFO    -  Structured data checked on {checked} pages")
