#!/usr/bin/env python3
"""Self-checks for build_sdk_docs.py. Run: python scripts/test_build_sdk_docs.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_sdk_docs as b  # noqa: E402

README = """# PipesHub Python SDK

Intro with `<inline>` code and a {brace}.

<!-- Start Table of Contents [toc] -->
## Table of Contents
- [x](#x)
<!-- End Table of Contents [toc] -->

## SDK Installation

> [!NOTE]
> **Policy**
>
> Upgrade soon.

```python
# not a heading
## not a section either
x = {"a": "<b>"}
```

</br>

See [examples](examples/) and [errors](#error-handling).

<details><summary>Less common errors (2)</summary>
<br />

* `X`: <YOUR_TOKEN>
</details>

## Available Resources and Operations

<details open>
<summary>Available methods</summary>
lots
</details>
"""

mdx = b.readme_to_mdx(README, "python", "v9.9.9")
assert mdx.startswith('---\ntitle: "Python SDK"'), mdx[:80]
assert "# PipesHub Python SDK" not in mdx  # H1 becomes the title
assert "Table of Contents" not in mdx
assert "<!--" not in mdx
assert "`<inline>`" in mdx and "a \\{brace\\}" in mdx  # inline code literal, prose escaped
assert '```python\n# not a heading\n## not a section either\nx = {"a": "<b>"}\n```' in mdx  # code untouched
assert "<Note>\n**Policy**\n\nUpgrade soon.\n</Note>" in mdx
assert "](https://github.com/pipeshub-ai/pipeshub-sdk-python/blob/v9.9.9/examples/)" in mdx
assert "](#error-handling)" in mdx
assert '<Accordion title="Less common errors (2)">' in mdx and "</Accordion>" in mdx
assert "&lt;YOUR_TOKEN>" in mdx and "</br>" not in mdx
assert "lots" not in mdx and "## Available Resources and Operations" in mdx

spec = {
    "paths": {"/a": {"post": {"responses": {"500": {"content": {"schema": {"$ref": "#/x"}}}}}}},
    "components": {"schemas": {"S": {"anyOf": [{"type": "string"}, {"type": "null"}]}}},
}
b.repair_spec(spec, "v0.0.0")
assert spec["paths"]["/a"]["post"]["responses"]["500"]["content"] == {"application/json": {"schema": {"$ref": "#/x"}}}
assert spec["components"]["schemas"]["S"] == {"anyOf": [{"type": "string"}], "nullable": True}

overlay = {"actions": [{"target": '$["paths"]["/a"]["post"]',
                        "update": {"x-codeSamples": [{"lang": "go", "label": "op", "source": "s"}]}}]}
assert b.add_samples(spec, overlay, "Go") == 1
assert spec["paths"]["/a"]["post"]["x-codeSamples"] == [{"lang": "go", "label": "Go", "source": "s"}]

assert b.semver("v1.10.0") > b.semver("v1.9.9")
print("ok")
