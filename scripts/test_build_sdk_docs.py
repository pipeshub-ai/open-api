#!/usr/bin/env python3
"""Self-checks for build_sdk_docs.py. Run: python scripts/test_build_sdk_docs.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_sdk_docs as b  # noqa: E402
import http_examples as h  # noqa: E402

# --- snippets ---------------------------------------------------------
SECTION = """<!-- UsageSnippet language="python" operationID="createKnowledgeBase" method="post" path="/knowledgeBase" -->
```python
with Pipeshub() as pipeshub:
    res = pipeshub.knowledge_base.create_knowledge_base(kb_name="x")
```
"""
m = b.SNIPPET_RE.search(SECTION)
assert (m["op_id"], m["method"], m["path"]) == ("createKnowledgeBase", "post", "/knowledgeBase")
assert b.CALL_RE["python"].search(m["code"]).groups() == ("knowledge_base", "create_knowledge_base")

resources = [{"title": "KnowledgeBase", "methods": [
    {"call": "knowledge_base.create_knowledge_base", "method": "post", "path": "/knowledgeBase/", "code": "x"},
    {"call": "knowledge_base.old", "method": "get", "path": "/gone", "code": "y"},
]}]

# --- API reference ---------------------------------------------------------------------------
spec = {
    "servers": [{"url": "https://{instance_url}/api/v1", "variables": {"instance_url": {"default": "app.pipeshub.com"}}}],
    "security": [{"bearerAuth": []}],
    "tags": [{"name": "Knowledge Base"}, {"name": "Internal Storage"}, {"name": "API Documentation"}],
    "x-pipeshub-nav": [{"name": "Data", "modules": [
        {"name": "Knowledge Base", "icon": "book", "description": "Knowledge bases", "tags": ["Knowledge Base"]},
        {"name": "Storage", "icon": "folder", "tags": ["Internal Storage"]}]}],
    "paths": {
        "/knowledgeBase": {"post": {"operationId": "createKnowledgeBase", "tags": ["Knowledge Base"]},
                           "get": {"operationId": "listKnowledgeBases", "tags": ["Knowledge Base"]}},
        "/document/internal/upload": {"post": {"operationId": "internalUpload", "tags": ["Internal Storage"],
                                               "security": [{"scopedToken": []}]}},
        "/docs": {"get": {"operationId": "getDocs", "tags": ["API Documentation"], "security": []}},
        "/health": {"get": {"operationId": "getHealth", "security": []}},
    },
}
assert b.public_spec(spec) == (3, 2)
assert "/document/internal/upload" not in spec["paths"] and "/docs" not in spec["paths"]
assert "/health" in spec["paths"]  # no auth at all is still public
assert [t["name"] for t in spec["tags"]] == ["Knowledge Base"]

counts = b.add_code_samples(spec, {"python": resources})
assert counts == {"Python": 1}  # trailing slash matches; /gone has no endpoint
assert spec["paths"]["/knowledgeBase"]["post"]["x-codeSamples"][0] == {"lang": "python", "label": "Python", "source": "x"}
assert b.add_http_examples(spec) == 3 + 3 + 2  # GET /knowledgeBase, /health: all three; POST: TypeScript and Go
samples = spec["paths"]["/knowledgeBase"]["post"]["x-codeSamples"]
assert [(s["lang"], s["label"]) for s in samples] == [("python", "Python"), ("typescript", "TypeScript"), ("go", "Go")]
assert samples[0]["source"] == "x" and samples[1]["source"].startswith("// Not in the TypeScript SDK yet")
assert "Authorization" not in spec["paths"]["/health"]["get"]["x-codeSamples"][0]["source"]  # security: []

urls = b.set_page_urls(spec)
assert urls[("post", "/knowledgeBase")] == "/api-reference/knowledge-base/create-knowledge-base"
assert urls[("get", "/health")] == "/api-reference/other/get-health"
assert b.endpoint_urls(spec) == urls

ts = [{"title": "KnowledgeBase", "methods": [
    {"call": "knowledgeBase.createKnowledgeBase", "method": "post", "path": "/knowledgeBase", "code": "t"}]}]
calls = b.sdk_calls(spec, {"python": resources, "typescript": ts})
assert calls == {("post", "/knowledgeBase"): {"python": "knowledge_base.create_knowledge_base",
                                               "typescript": "knowledgeBase.createKnowledgeBase"}}
assert b.mark_sdk_coverage(spec, calls) == 1
create, listing = spec["paths"]["/knowledgeBase"]["post"]["x-mint"], spec["paths"]["/knowledgeBase"]["get"]["x-mint"]
assert create["metadata"]["tag"] == "SDK" and create["href"].endswith("/create-knowledge-base")
assert "content" not in create and "tag" not in listing.get("metadata", {})

groups = b.api_groups(spec)  # one group per service, no area level
assert groups == [
    {"group": "Knowledge Base", "icon": "book", "pages": ["GET /knowledgeBase", "POST /knowledgeBase"]},
    {"group": "Other", "icon": "ellipsis", "pages": ["GET /health"]},
]

svc = b.services_mdx(spec)
assert svc.startswith("### Knowledge Base\n\nKnowledge bases.\n\n"
                      "[Knowledge Base](/api-reference/knowledge-base/list-knowledge-bases) "
                      "(2 endpoints, 1 in the [SDKs](/developer/sdks#what-the-sdks-cover))"), svc
assert "### Other" in svc and "(1 endpoint, 0 in the" in svc

import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as d:
    page = Path(d) / b.API_OVERVIEW
    page.parent.mkdir(parents=True)
    page.write_text(f"intro\n{b.GENERATED[0]}\nstale\n{b.GENERATED[1]}\nafter\n")
    b.write_generated(Path(d), b.API_OVERVIEW, b.GENERATED, "NEW\n")
    assert page.read_text() == f"intro\n{b.GENERATED[0]}\n\nNEW\n\n{b.GENERATED[1]}\nafter\n"
    (Path(d) / "docs.json").write_text(json.dumps({"navigation": {"groups": [
        {"group": "Developer", "pages": ["a"]},
        {"group": "API reference", "pages": ["developer/api-reference", {"group": "Old", "pages": ["GET /x"]}]}]}}))
    b.update_nav(Path(d), groups)
    config = json.loads((Path(d) / "docs.json").read_text())
    api = config["navigation"]["groups"][1]
    assert api["openapi"] == b.API_SPEC and api["pages"] == ["developer/api-reference", *groups]
    assert config["api"]["examples"]["languages"] == ["curl", "python", "typescript", "go"]

assert b._escape_text("a {b} <c> `<d>`") == "a \\{b\\} &lt;c> `<d>`"

srv = {"servers": [
    {"url": "{instance_url}/api/v1", "variables": {"instance_url": {"default": "app.pipeshub.com"}}},
    {"url": "{instance_url}", "description": "Root"}],
    "paths": {"/.well-known/jwks.json": {"get": {"servers": [{"url": "/"}]}},
              "/mcp": {"post": {"servers": [{"url": "{instance_url}", "variables": {"instance_url": {"default": "x"}}}]}}}}
b.absolute_servers(srv)
assert [(s["url"], s["variables"]["instance_url"]["default"]) for s in srv["servers"]] == [
    ("https://{instance_url}/api/v1", "app.pipeshub.com")]
jwks = srv["paths"]["/.well-known/jwks.json"]["get"]["servers"][0]
assert (jwks["url"], jwks["variables"]["instance_url"]["default"]) == ("https://{instance_url}", "app.pipeshub.com")
assert srv["paths"]["/mcp"]["post"]["servers"][0]["url"] == "https://{instance_url}"

assert b.slugify("OAuth Provider") == "oauth-provider" and b.slugify("getHealth") == "get-health"
assert b.slugify("listKBPermissions") == "list-kb-permissions" and b.slugify("Public URLs") == "public-urls"
assert b.semver("v1.10.0") > b.semver("v1.9.9")

# --- HTTP examples ---------------------------------------------------------------------------
hspec = {
    "servers": [{"url": "https://app.pipeshub.com/api/v1"}],
    "security": [{"bearerAuth": []}],
    "components": {"schemas": {
        "Base": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}, "id": {"type": "string", "readOnly": True}}},
        "Kb": {"allOf": [{"$ref": "#/components/schemas/Base"}, {"properties": {
            "size": {"type": "integer", "minimum": 1, "maximum": 9}, "kind": {"enum": ["a", "b"]},
            "when": {"type": "string", "format": "date-time"}, "tags": {"type": "array", "items": {"type": "string"}},
            "parent": {"oneOf": [{"type": "null"}, {"type": "boolean"}]}, "self": {"$ref": "#/components/schemas/Kb"}}}]}}},
    "paths": {
        "/kb/{kbId}": {"parameters": [{"name": "kbId", "in": "path", "required": True}],
                       "put": {"parameters": [{"name": "dryRun", "in": "query", "required": True, "schema": {"type": "boolean"}},
                                              {"name": "page", "in": "query", "schema": {"type": "integer"}}],
                               "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Kb"}}}}}},
        "/upload": {"post": {"security": [], "requestBody": {"content": {"multipart/form-data": {"schema": {
            "properties": {"file": {"type": "string", "format": "binary"}, "note": {"type": "string", "example": "hi"}}}}}}}},
    },
}
req = h.request(hspec, "/kb/{kbId}", "put")
assert req["url"] == "https://app.pipeshub.com/api/v1/kb/{kbId}" and req["query"] == {"dryRun": "true"}
assert req["headers"] == {"Authorization": "Bearer <token>"}
assert req["body"]["value"] == {"name": "<string>", "size": 5, "kind": "a", "when": "2023-11-07T05:31:56Z",
                                "tags": ["<string>"], "parent": True, "self": {}}
assert list(req["body"]["value"]) == ["name", "size", "kind", "when", "tags", "parent", "self"]
assert "payload = {" in h.python(req) and "params=params" in h.python(req)
up = h.request(hspec, "/upload", "post")
assert up["headers"] == {} and up["body"] == {"kind": "multipart", "files": ["file"], "fields": {"note": "hi"}}
assert 'form.append("file", await openAsBlob("<file>"), "<file>");' in h.typescript(up)
assert 'form.CreateFormFile("file", "<file>")' in h.go(up)

print("ok")
