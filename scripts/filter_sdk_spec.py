#!/usr/bin/env python3
"""Filter an OpenAPI spec down to operations exposed in the SDK.

Rules:
  * Keep only operations marked `x-pipeshub-sdk: true`.
  * Drop everything else (operations with `x-pipeshub-sdk: false` or no marker).
  * Remove paths left with no operations.
  * Remove unused components (schemas, parameters, requestBodies, responses,
    headers, examples, links, callbacks) via transitive `$ref` closure.
  * Remove top-level tags no remaining operation references.
  * Strip the `x-pipeshub-sdk` marker from the output.
  * Strip `Set-Cookie` from every response, and all headers from error (non-2xx)
    responses, so they do not change what an SDK method returns (see
    `strip_cookie_headers` and `strip_error_response_headers`).
"""
from __future__ import annotations

import argparse
import copy
import sys
from typing import Any

import yaml

HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}
SDK_MARKER = "x-pipeshub-sdk"
COMPONENT_GROUPS = (
    "schemas",
    "parameters",
    "requestBodies",
    "responses",
    "headers",
    "examples",
    "links",
    "callbacks",
)

# Operations whose error-response headers were already in the released SDKs (v2.0.x), so their
# methods already return a { headers, result } wrapper. They keep those headers: removing them
# would change the return type of a released method. Remove an entry only in a major release.
KEEP_ERROR_HEADERS = frozenset(
    {
        "oauthUserInfo",
        "getKnowledgeHubRootNodes",
        "getKnowledgeHubChildNodes",
    }
)


def filter_operations(spec: dict) -> tuple[int, int]:
    """Drop operations not marked `x-pipeshub-sdk: true`. Returns (kept, dropped)."""
    kept = dropped = 0
    paths = spec.get("paths") or {}
    for path, path_item in list(paths.items()):
        if not isinstance(path_item, dict):
            continue
        for method in list(path_item):
            if method.lower() not in HTTP_METHODS:
                continue
            op = path_item[method]
            if not isinstance(op, dict):
                continue
            if op.get(SDK_MARKER) is True:
                op.pop(SDK_MARKER, None)
                kept += 1
            else:
                del path_item[method]
                dropped += 1
        if not any(k.lower() in HTTP_METHODS for k in path_item):
            del paths[path]
    return kept, dropped


def _is_success(status: Any) -> bool:
    return str(status).startswith("2")


def _resolve_response(spec: dict, response: Any) -> Any:
    """Follow a `#/components/responses/...` $ref; return anything else as is."""
    if isinstance(response, dict) and isinstance(response.get("$ref"), str):
        prefix = "#/components/responses/"
        ref = response["$ref"]
        if ref.startswith(prefix):
            target = ((spec.get("components") or {}).get("responses") or {}).get(ref[len(prefix) :])
            if isinstance(target, dict):
                return target
    return response


def _operations(spec: dict):
    """Yield every operation object under `paths`."""
    for path_item in (spec.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.lower() in HTTP_METHODS and isinstance(op, dict):
                yield op


def _drop_headers(spec: dict, responses: dict, status: Any, drop) -> bool:
    """Remove the headers `drop(name)` selects from one response. Returns True if any went.

    A $ref'd response is replaced by an inline copy; the shared component is left as it is.
    """
    resolved = _resolve_response(spec, responses[status])
    headers = resolved.get("headers") if isinstance(resolved, dict) else None
    if not isinstance(headers, dict) or not any(drop(name) for name in headers):
        return False
    inline = copy.deepcopy(resolved)
    kept = {name: h for name, h in headers.items() if not drop(name)}
    if kept:
        inline["headers"] = copy.deepcopy(kept)
    else:
        del inline["headers"]
    responses[status] = inline
    return True


def strip_cookie_headers(spec: dict) -> int:
    """Drop `Set-Cookie` from every response. Returns how many responses changed.

    A cookie is the browser session's transport; an SDK client signs in with a bearer token
    and keeps no cookie jar. Declared on a success response, `Set-Cookie` would still make
    Speakeasy wrap the method's return value (see `strip_error_response_headers`), as it would
    for refreshToken, which returned its body directly in v2.0.x.
    """
    changed = 0
    for op in _operations(spec):
        responses = op.get("responses")
        if not isinstance(responses, dict):
            continue
        for status in list(responses):
            if _drop_headers(spec, responses, status, lambda name: name.lower() == "set-cookie"):
                changed += 1
    return changed


def strip_error_response_headers(spec: dict) -> int:
    """Drop the headers of error (non-2xx) responses. Returns how many responses changed.

    Speakeasy turns a method's return value into a { headers, result } wrapper when any of the
    operation's responses, an error response included, declares a header. A `Retry-After` on a
    503 then changes the return type of a method that never returns that 503's body, and breaks
    callers and the hand-written integrations in the SDK repos. An error response is raised as
    an exception, which still carries the raw HTTP response and its headers.

    Skipped: operations whose success response declares headers (they return the wrapper
    anyway) and the operations in KEEP_ERROR_HEADERS. A $ref'd response that declares headers
    is replaced by an inline copy without them; the shared component is left as it is.
    """
    changed = 0
    for op in _operations(spec):
        responses = op.get("responses")
        if not isinstance(responses, dict) or op.get("operationId") in KEEP_ERROR_HEADERS:
            continue
        if any(
            _is_success(status) and (_resolve_response(spec, r) or {}).get("headers")
            for status, r in responses.items()
        ):
            continue
        for status in list(responses):
            if not _is_success(status) and _drop_headers(spec, responses, status, lambda _: True):
                changed += 1
    return changed


def _collect_refs(node: Any, refs: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                refs.add(v)
            else:
                _collect_refs(v, refs)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, refs)


def used_components(spec: dict) -> dict[str, set[str]]:
    """Transitive closure of components reachable from `paths`."""
    components = spec.get("components") or {}
    used: dict[str, set[str]] = {g: set() for g in COMPONENT_GROUPS}

    seed: set[str] = set()
    _collect_refs(spec.get("paths") or {}, seed)

    queue = list(seed)
    while queue:
        ref = queue.pop()
        if not ref.startswith("#/components/"):
            continue
        parts = ref[len("#/components/") :].split("/", 1)
        if len(parts) != 2:
            continue
        group, name = parts
        if group not in used or name in used[group]:
            continue
        used[group].add(name)
        body = (components.get(group) or {}).get(name)
        if body is None:
            continue
        sub: set[str] = set()
        _collect_refs(body, sub)
        queue.extend(sub)
    return used


def prune_components(spec: dict, used: dict[str, set[str]]) -> int:
    """Drop component entries not in `used`. Returns number removed."""
    removed = 0
    components = spec.get("components")
    if not isinstance(components, dict):
        return 0
    for group in COMPONENT_GROUPS:
        bucket = components.get(group)
        if not isinstance(bucket, dict):
            continue
        for name in list(bucket):
            if name not in used[group]:
                del bucket[name]
                removed += 1
        if not bucket:
            del components[group]
    if not components:
        del spec["components"]
    return removed


def prune_tags(spec: dict) -> int:
    """Drop top-level tags not referenced by any remaining operation."""
    tags = spec.get("tags")
    if not isinstance(tags, list):
        return 0
    used_tags: set[str] = set()
    for path_item in (spec.get("paths") or {}).values():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
                continue
            for t in op.get("tags") or []:
                if isinstance(t, str):
                    used_tags.add(t)
    kept = [t for t in tags if isinstance(t, dict) and t.get("name") in used_tags]
    removed = len(tags) - len(kept)
    if kept:
        spec["tags"] = kept
    else:
        spec.pop("tags", None)
    return removed


def _str_representer(dumper: yaml.Dumper, data: str):
    """Use literal block scalars for multi-line strings so descriptions stay readable."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Input OpenAPI YAML file")
    parser.add_argument("output", help="Output OpenAPI YAML file")
    args = parser.parse_args()

    with open(args.input) as f:
        spec = yaml.safe_load(f)

    if not isinstance(spec, dict):
        print(f"error: {args.input} did not parse to a YAML mapping", file=sys.stderr)
        return 1

    kept, dropped = filter_operations(spec)
    cookies_stripped = strip_cookie_headers(spec)
    headers_stripped = strip_error_response_headers(spec)
    components_removed = prune_components(spec, used_components(spec))
    tags_removed = prune_tags(spec)

    yaml.add_representer(str, _str_representer, Dumper=yaml.SafeDumper)
    with open(args.output, "w") as f:
        yaml.safe_dump(
            spec,
            f,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
            width=1000,
        )

    print(
        f"filter_sdk_spec: kept={kept} dropped={dropped} "
        f"components_removed={components_removed} tags_removed={tags_removed} "
        f"cookie_headers_stripped={cookies_stripped} error_headers_stripped={headers_stripped}",
        file=sys.stderr,
    )
    if kept == 0:
        print(
            "warning: no operations marked x-pipeshub-sdk: true — output spec has no paths",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
