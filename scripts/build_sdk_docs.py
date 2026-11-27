#!/usr/bin/env python3
"""Build the API reference of the Mintlify docs site (docs.pipeshub.com) from the PipesHub
OpenAPI spec, with the SDKs' examples on each endpoint page.

  api-reference/openapi.yaml   the public part of the PipesHub OpenAPI spec of the latest release.
                               Left out: operations only services can call (scopedToken auth) and
                               the ones that serve the in-app API docs. Every operation the SDKs
                               cover carries the latest SDK release's Python, TypeScript and Go
                               example (x-codeSamples), which Mintlify shows next to cURL.
  docs.json                    the endpoint groups of the "API reference" sidebar group, one per
                               service (x-pipeshub-nav module), in the in-app API docs' order.
  developer/api-reference.mdx  the list of services between the GENERATED markers, with how many
                               endpoints of each the SDKs cover.
The SDK guide (developer/sdks.mdx) is written by hand.

Every endpoint page has a Python, TypeScript and Go example next to Mintlify's cURL example
(x-codeSamples; docs.json api.examples.languages lists the four, and Mintlify shows no other):
  - where an SDK covers the endpoint, the SDK's example from the latest release;
  - elsewhere, a plain HTTP request in that language (http_examples.py), whose first line says the
    SDK does not cover the endpoint yet.
Endpoints the SDKs cover carry an "SDK" badge in the sidebar (x-mint.metadata.tag).

Code samples come from the SDK repos at the tag: Speakeasy writes every operation's example into
docs/sdks/*/README.md, marked
<!-- UsageSnippet language=... operationID=... method=... path=... -->. No Speakeasy CLI is needed.

Usage:
  build_sdk_docs.py --sdks DIR --docs DIR --spec FILE [--version v2.0.1]
DIR for --sdks holds pipeshub-sdk-{python,typescript,go} clones with tags; --version defaults to
the newest tag all three share. --spec is the pipeshub-ai spec at the release to document.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import yaml

import http_examples

# lang -> (SDK repo, display name)
LANGS = {
    "python": ("pipeshub-sdk-python", "Python"),
    "typescript": ("pipeshub-sdk-typescript", "TypeScript"),
    "go": ("pipeshub-sdk-go", "Go"),
}
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
# Every OpenAPI operation method; the order sets the order of a path's endpoints in the sidebar.
HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
API_GROUP = "API reference"
API_SPEC = "api-reference/openapi.yaml"
API_OVERVIEW = "developer/api-reference.mdx"
GENERATED = ("{/* GENERATED: services. build_sdk_docs.py rewrites this part; edit the script, not the page. */}",
             "{/* END GENERATED: services */}")
# Code panel languages, in tab order. Mintlify shows only these, x-codeSamples included, so the
# SDK languages must be listed; cURL is the only one it generates itself, since every operation
# has its own Python, TypeScript and Go example. Its generated examples in other languages are
# plain HTTP calls that would sit next to the SDK examples.
EXAMPLE_LANGUAGES = ["curl", *LANGS]
SDK_TAG = "SDK"  # sidebar badge on endpoints the SDKs cover
# Operations a user token cannot call, and the operations that serve the in-app docs UI.
SERVICE_ONLY_SCHEMES = {"scopedToken"}
DROP_TAGS = {"API Documentation"}
# x-pipeshub-nav icons (lucide names) -> Font Awesome names Mintlify knows.
ICONS = {"search": "magnifying-glass", "cpu": "microchip", "tool": "wrench", "layers": "layer-group",
         "mail": "envelope", "activity": "heart-pulse"}
SNIPPET_RE = re.compile(
    r'<!-- UsageSnippet language="(?P<lang>\w+)" operationID="(?P<op_id>[^"]+)" '
    r'method="(?P<method>\w+)" path="(?P<path>[^"]+)"[^>]*-->\s*```\w*\n(?P<code>.*?)\n```', re.S)
# The SDK call in a snippet: pipeshub.knowledge_base.create_knowledge_base( / s.KnowledgeBase.Create(
CALL_RE = {
    "python": re.compile(r"\bpipeshub\.(\w+)\.(\w+)\("),
    "typescript": re.compile(r"\bpipeshub\.(\w+)\.(\w+)\("),
    "go": re.compile(r"\bs\.(\w+)\.(\w+)\("),
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def semver(tag: str) -> tuple[int, ...]:
    return tuple(int(p) for p in tag.lstrip("v").split("."))


def latest_tag(sdks: Path) -> str:
    """The newest release tag all three SDK repos have."""
    tag_sets = [{t for t in git(sdks / repo, "tag").split() if TAG_RE.match(t)} for repo, _ in LANGS.values()]
    tags = set.intersection(*tag_sets)
    if not tags:
        raise SystemExit("the SDK repos share no release tag")
    return max(tags, key=semver)


def op_key(method: str, path: str) -> tuple[str, str]:
    return method.lower(), "/" + path.strip("/")


# --- SDK methods, from docs/sdks/*/README.md at a tag ----------------------------------------

def sdk_methods(sdks: Path, lang: str, tag: str) -> list[dict]:
    """Resources in README order, each with its methods: name, SDK call, operation and example."""
    repo = sdks / LANGS[lang][0]
    readme = git(repo, "show", f"{tag}:README.md")
    # The README's operations list gives the resource order; fall back to file order.
    order = re.findall(r"\(docs/sdks/(\w+)/README\.md\)", readme)
    files = [p for p in git(repo, "ls-tree", "-r", "--name-only", tag, "docs/sdks").split()
             if p.endswith("/README.md")]
    by_dir = {p.split("/")[2]: p for p in files}
    dirs = list(dict.fromkeys([d for d in order if d in by_dir] + sorted(by_dir)))
    resources = []
    for d in dirs:
        text = git(repo, "show", f"{tag}:{by_dir[d]}")
        title = re.search(r"^# (.+)$", text, re.M).group(1).strip()
        # Methods the resource's README lists (sections without a list entry are not methods).
        listed = set(re.findall(r"^\* \[(?:~~)?(\w+)(?:~~)?\]\(#\w+\)", text, re.M))
        methods = []
        for section in re.split(r"^## ", text, flags=re.M)[1:]:
            name = section.split("\n", 1)[0].strip()
            snip = SNIPPET_RE.search(section)
            if not snip or name not in listed:
                continue
            call = CALL_RE[lang].search(snip["code"])
            methods.append({
                "name": name,
                "call": f"{call.group(1)}.{call.group(2)}" if call else name,
                "op_id": snip["op_id"],
                "method": snip["method"],
                "path": snip["path"],
                "code": snip["code"].rstrip(),
            })
        if methods:
            resources.append({"title": title, "methods": methods})
    return resources


# --- API reference ---------------------------------------------------------------------------

def public_spec(spec: dict) -> tuple[int, int]:
    """Drop the operations a user cannot call. Returns (kept, dropped)."""
    kept = dropped = 0
    default_security = spec.get("security", [])
    for path, item in list(spec["paths"].items()):
        for method in [m for m in item if m in HTTP_METHODS]:
            op = item[method]
            # Security requirements are alternatives and the schemes inside one are all needed, so
            # an operation is service-only when every alternative needs a service-only scheme. An
            # empty alternative ({}) means anyone may call it.
            reqs = op.get("security", default_security)
            service_only = bool(reqs) and all(SERVICE_ONLY_SCHEMES & set(r) for r in reqs)
            if service_only or DROP_TAGS & set(op.get("tags", [])):
                del item[method]
                dropped += 1
            else:
                kept += 1
        if not any(m in item for m in HTTP_METHODS):
            del spec["paths"][path]
    used = {t for item in spec["paths"].values() for m in HTTP_METHODS if m in item for t in item[m].get("tags", [])}
    spec["tags"] = [t for t in spec.get("tags", []) if t["name"] in used]
    return kept, dropped


def absolute_servers(spec: dict) -> None:
    """Give every server URL a scheme. The spec writes "{instance_url}/api/v1" (a host name with no
    scheme) and "/" for the root endpoints; the in-app docs fill those in, but Mintlify needs a full
    URL or it shows no request example. The root server only belongs to the operations that name it."""
    def fix(server: dict) -> dict:
        url = server["url"]
        if url.startswith("/"):
            url = "{instance_url}" + url.rstrip("/")
        if "://" not in url:
            url = "https://" + url
        variables = server.get("variables") or {}
        if "{instance_url}" in url:
            variables = {**variables, "instance_url": {
                "default": variables.get("instance_url", default_var).get("default", "app.pipeshub.com"),
                "description": "Host name of your PipesHub instance, with an optional port. Example: pipeshub.example.com"}}
        return {**server, "url": url, **({"variables": variables} if variables else {})}

    top = spec.get("servers", [])
    api = [s for s in top if s["url"].rstrip("/").endswith("/api/v1")] or top[:1]
    default_var = {"default": "app.pipeshub.com"}
    for s in api:
        default_var = s.get("variables", {}).get("instance_url", default_var)
    spec["servers"] = [fix(s) for s in api]
    for item in spec["paths"].values():
        for node in [item, *(item[m] for m in HTTP_METHODS if m in item)]:
            if "servers" in node:
                node["servers"] = [fix(s) for s in node["servers"]]


def add_code_samples(spec: dict, methods: dict[str, list[dict]]) -> dict[str, int]:
    """methods: lang -> resources (sdk_methods). Adds each method's example to its operation."""
    ops = {op_key(m, p): item[m] for p, item in spec["paths"].items() for m in HTTP_METHODS if m in item}
    counts = {}
    for lang, resources in methods.items():
        name = LANGS[lang][1]
        n = 0
        for res in resources:
            for meth in res["methods"]:
                op = ops.get(op_key(meth["method"], meth["path"]))
                if op is None or any(s["lang"] == lang for s in op.get("x-codeSamples", [])):
                    continue
                op.setdefault("x-codeSamples", []).append({"lang": lang, "label": name, "source": meth["code"]})
                n += 1
        counts[name] = n
    return counts


def add_http_examples(spec: dict) -> int:
    """Give every operation an example in each SDK language: where an SDK does not cover it, a plain
    HTTP request in that language, which says the SDK does not cover it yet. Returns how many."""
    n = 0
    order = list(LANGS)
    for path, item in spec["paths"].items():
        for m in HTTP_METHODS:
            if m not in item:
                continue
            op = item[m]
            samples = op.setdefault("x-codeSamples", [])
            have = {s["lang"] for s in samples}
            req = None
            for lang in LANGS:
                if lang not in have:
                    req = req or http_examples.request(spec, path, m)
                    samples.append({"lang": lang, "label": LANGS[lang][1], "source": http_examples.GENERATORS[lang](req)})
                    n += 1
            samples.sort(key=lambda s: order.index(s["lang"]) if s["lang"] in order else len(order))
    return n


def sdk_calls(spec: dict, methods: dict[str, list[dict]]) -> dict[tuple[str, str], dict[str, str]]:
    """(method, path) of each operation in the spec -> {lang: SDK call}, for the operations the SDKs cover."""
    ops = {op_key(m, p) for p, item in spec["paths"].items() for m in HTTP_METHODS if m in item}
    calls: dict[tuple[str, str], dict[str, str]] = {}
    for lang, resources in methods.items():
        for res in resources:
            for meth in res["methods"]:
                key = op_key(meth["method"], meth["path"])
                if key in ops:
                    calls.setdefault(key, {}).setdefault(lang, meth["call"])
    return calls


def mark_sdk_coverage(spec: dict, calls: dict[tuple[str, str], dict[str, str]]) -> int:
    """Put an SDK badge in the sidebar on the endpoints the SDKs cover. Returns how many."""
    covered = 0
    for path, item in spec["paths"].items():
        for m in HTTP_METHODS:
            if m not in item:
                continue
            mint = item[m].setdefault("x-mint", {})
            mint.pop("content", None)
            if calls.get(op_key(m, path)):
                covered += 1
                mint.setdefault("metadata", {})["tag"] = SDK_TAG
            else:
                mint.get("metadata", {}).pop("tag", None)
    return covered


def slugify(text: str) -> str:
    """createKnowledgeBase / "Knowledge Base" -> create-knowledge-base / knowledge-base"""
    text = re.sub(r"([A-Z]{2,})([A-Z][a-z]{2,})", r"\1-\2", text)  # listKBPermissions -> list-KB-Permissions
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def set_page_urls(spec: dict) -> dict[tuple[str, str], str]:
    """Give every endpoint page a URL built from its tag and operationId (x-mint.href), not from
    its summary, so rewording a summary does not move the page. Returns (method, path) -> URL."""
    urls = {}
    for path, item in spec["paths"].items():
        for m in HTTP_METHODS:
            if m not in item:
                continue
            op = item[m]
            tag = (op.get("tags") or ["other"])[0]
            url = f"/{Path(API_SPEC).parent}/{slugify(tag)}/{slugify(op.get('operationId') or f'{m} {path}')}"
            op.setdefault("x-mint", {})["href"] = url
            urls[op_key(m, path)] = url
    if len(set(urls.values())) != len(urls):
        raise SystemExit("two endpoints would share a URL; their operationIds collide")
    return urls


def endpoint_urls(spec: dict) -> dict[tuple[str, str], str]:
    return {op_key(m, p): item[m]["x-mint"]["href"]
            for p, item in spec["paths"].items() for m in HTTP_METHODS if m in item and "x-mint" in item[m]}


def _pages_by_tag(spec: dict) -> dict[str, list[tuple[str, str]]]:
    """tag -> [(method, path)] in spec order."""
    pages: dict[str, list[tuple[str, str]]] = {}
    for path, item in spec["paths"].items():
        for m in HTTP_METHODS:
            if m in item:
                pages.setdefault((item[m].get("tags") or ["Other"])[0], []).append((m, path))
    return pages


def services(spec: dict) -> list[dict]:
    """x-pipeshub-nav modules that have public endpoints, in order, plus "Other" for unlisted tags:
    [{name, icon, description, tags: [(tag, [(method, path)])]}]"""
    pages = _pages_by_tag(spec)
    out, placed = [], set()
    for area in spec.get("x-pipeshub-nav", []):
        for module in area["modules"]:
            tags = [t for t in module["tags"] if t in pages]
            placed.update(tags)
            if tags:
                out.append({"name": module["name"], "icon": ICONS.get(module.get("icon"), module.get("icon")),
                            "description": module.get("description", ""), "tags": [(t, pages[t]) for t in tags]})
    rest = [t for t in pages if t not in placed]
    if rest:
        out.append({"name": "Other", "icon": "ellipsis", "description": "", "tags": [(t, pages[t]) for t in rest]})
    return out


def api_groups(spec: dict) -> list[dict]:
    """Sidebar: one collapsible group per service; a service with several tags gets a group per tag."""
    def endpoints(ops):
        return [f"{m.upper()} {p}" for m, p in ops]
    groups = []
    for svc in services(spec):
        if len(svc["tags"]) == 1 and svc["tags"][0][0] == svc["name"]:
            pages = endpoints(svc["tags"][0][1])
        else:
            pages = [{"group": t, "pages": endpoints(ops)} for t, ops in svc["tags"]]
        groups.append({"group": svc["name"], "icon": svc["icon"], "pages": pages})
    return groups


def _is_covered(spec: dict, op: tuple[str, str]) -> bool:
    m, path = op
    return spec["paths"][path][m].get("x-mint", {}).get("metadata", {}).get("tag") == SDK_TAG


def services_mdx(spec: dict) -> str:
    """The services list on the API reference overview: a heading per service (its anchor is what
    old links redirect to), its description, and a link to the first endpoint of each section."""
    urls = endpoint_urls(spec)
    out = []
    for svc in services(spec):
        n = sum(len(ops) for _, ops in svc["tags"])
        c = sum(1 for _, ops in svc["tags"] for op in ops if _is_covered(spec, op))
        out.append(f"### {svc['name']}\n")
        if svc["description"]:
            desc = svc["description"].strip()
            out.append(f"\n{_escape_text(desc if desc.endswith('.') else desc + '.')}\n")
        links = " · ".join(f"[{_escape_text(t)}]({urls[op_key(*ops[0])]})" for t, ops in svc["tags"])
        out.append(f"\n{links} ({n} endpoint{'s' if n != 1 else ''}, {c} in the [SDKs](/developer/sdks#what-the-sdks-cover))\n\n")
    return "".join(out).rstrip() + "\n"


ALLOWED_TAGS = re.compile(r"<(?!/?(?:Accordion|Note|Tip|Info|Warning|br)\b)")


def _escape_text(text: str) -> str:
    """Plain text -> MDX-safe text: no JSX tags, no expressions."""
    out = []
    for i, piece in enumerate(re.split(r"(`[^`\n]*`)", text)):
        out.append(piece if i % 2 else ALLOWED_TAGS.sub("&lt;", piece).replace("{", "\\{").replace("}", "\\}"))
    return "".join(out)


def write_generated(docs: Path, page_path: str, markers: tuple[str, str], text: str) -> None:
    """Replace the part of a hand-written page between its GENERATED markers."""
    path = docs / page_path
    page = path.read_text()
    begin, end = markers
    if page.count(begin) != 1 or page.count(end) != 1:
        raise SystemExit(f"{page_path} needs the GENERATED markers once each:\n{begin}\n{end}")
    head, rest = page.split(begin)
    _, tail = rest.split(end)
    path.write_text(f"{head}{begin}\n\n{text}\n{end}{tail}")


# --- docs.json ------------------------------------------------------------------------------

def _find_group(node, name: str) -> dict | None:
    if isinstance(node, dict):
        if node.get("group") == name:
            return node
        children = [c for k in ("groups", "pages", "tabs", "anchors", "dropdowns", "versions") for c in node.get(k, [])]
    elif isinstance(node, list):
        children = node
    else:
        return None
    return next((g for g in (_find_group(c, name) for c in children) if g), None)


def _has_endpoints(node) -> bool:
    if isinstance(node, str):
        return node.split(" ", 1)[0].lower() in HTTP_METHODS
    if isinstance(node, dict):
        return any(_has_endpoints(p) for p in node.get("pages", []))
    return False


def update_nav(docs: Path, groups: list[dict]) -> None:
    path = docs / "docs.json"
    config = json.loads(path.read_text())
    group = _find_group(config["navigation"], API_GROUP)
    if group is None:
        raise SystemExit(f'docs.json has no "{API_GROUP}" group; add it once by hand')
    group["openapi"] = API_SPEC
    # Hand-written pages (the overview) stay first; the endpoint groups are rebuilt.
    group["pages"] = [p for p in group.get("pages", []) if not _has_endpoints(p)] + groups
    config.setdefault("api", {}).setdefault("examples", {})["languages"] = EXAMPLE_LANGUAGES
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")


class _BlockDumper(yaml.SafeDumper):
    pass


_BlockDumper.add_representer(
    str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sdks", type=Path, required=True)
    ap.add_argument("--docs", type=Path, required=True)
    ap.add_argument("--spec", type=Path, required=True, help="pipeshub-ai OpenAPI spec of the release to document")
    ap.add_argument("--version", default="", help="SDK release tag; default: the newest tag all three SDKs share")
    args = ap.parse_args()

    tag = args.version or latest_tag(args.sdks)
    if not TAG_RE.match(tag):
        raise SystemExit(f"not a release tag: {tag!r}")
    methods = {lang: sdk_methods(args.sdks, lang, tag) for lang in LANGS}

    spec = yaml.safe_load(args.spec.read_text())
    kept, dropped = public_spec(spec)
    absolute_servers(spec)
    samples = add_code_samples(spec, methods)
    http = add_http_examples(spec)
    urls = set_page_urls(spec)
    calls = sdk_calls(spec, methods)
    covered = mark_sdk_coverage(spec, calls)
    spec_file = args.docs / API_SPEC
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_text(yaml.dump(spec, Dumper=_BlockDumper, sort_keys=False, allow_unicode=True, width=10_000))
    update_nav(args.docs, api_groups(spec))
    write_generated(args.docs, API_OVERVIEW, GENERATED, services_mdx(spec))
    print(f"API reference: {kept} operations ({dropped} service-only left out), {covered} in the SDKs")
    missing = [f"{m['call']} ({m['method'].upper()} {m['path']})" for r in methods["python"] for m in r["methods"]
               if op_key(m["method"], m["path"]) not in urls]
    print(f"SDK samples: {tag}, " + ", ".join(f"{n} {c}" for n, c in samples.items())
          + f"; {len(missing)} SDK methods have no public endpoint page; {http} HTTP examples where an SDK has none")
    for m in missing:
        print(f"  no endpoint page: {m}")

if __name__ == "__main__":
    main()
