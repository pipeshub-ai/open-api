"""Plain HTTP request examples in Python (requests), TypeScript (fetch) and Go (net/http) for the
endpoints an SDK does not cover yet, so every endpoint page has an example in each SDK language.

Example values follow Mintlify's own request examples (the ones its cURL example shows): a
schema's example, default or first enum value, else "<string>", 123, true and so on. Path
parameters stay as {name} in the URL, as in the cURL example; required query and header
parameters are filled in, array query parameters per their style and explode settings.
"""
from __future__ import annotations

import json

NOTE = "Not in the {sdk} SDK yet: plain HTTP request."  # short enough for the code panel
STRING_FORMATS = {
    "byte": "aSDinaTvuI8gbWludGxpZnk=", "base64": "aSDinaTvuI8gbWludGxpZnk=", "date": "2023-12-25",
    "date-time": "2023-11-07T05:31:56Z", "email": "jsmith@example.com",
    "uuid": "3c90c3cc-0d44-4b50-8888-8dd25736052a", "ipv4": "127.0.0.1", "ipv6": "2606:4700:3108::ac42:2835",
}
BODY_TYPES = ("application/json", "application/x-www-form-urlencoded", "multipart/form-data")
FILE = "<file>"


def resolve(spec: dict, node: dict, seen: frozenset = frozenset()) -> tuple[dict, frozenset]:
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if ref in seen:
            return {}, seen
        seen = seen | {ref}
        target = spec
        for part in ref.lstrip("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        node = target
    return node, seen


def _merge_all_of(spec: dict, schema: dict, seen: frozenset) -> dict:
    """allOf parts merged in order, the schema's own properties last."""
    merged = {k: v for k, v in schema.items() if k not in ("allOf", "properties")}
    props: dict = {}
    for part in schema["allOf"]:
        part, _ = resolve(spec, part, seen)
        if "allOf" in part:
            part = _merge_all_of(spec, part, seen)
        props.update(part.get("properties", {}))
        merged["required"] = [*merged.get("required", []), *part.get("required", [])]
        for k, v in part.items():
            if k != "properties":
                merged.setdefault(k, v)
    merged["properties"] = {**props, **schema.get("properties", {})}
    return merged


def _type(schema: dict) -> str | None:
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), None)
    if t is None and "properties" in schema:
        return "object"
    return t


def example(spec: dict, schema: dict, seen: frozenset = frozenset()):
    """An example value for a request schema, as Mintlify builds its request examples."""
    schema, seen = resolve(spec, schema, seen)
    if "allOf" in schema:
        schema = _merge_all_of(spec, schema, seen)
    for key in ("example", "default", "const"):
        if key in schema:
            return schema[key]
    if schema.get("examples"):
        ex = schema["examples"]
        return ex[0] if isinstance(ex, list) else next(iter(ex.values()))
    if schema.get("enum"):
        return schema["enum"][0]
    for key in ("oneOf", "anyOf"):
        if schema.get(key):
            options = [resolve(spec, o, seen)[0] for o in schema[key]]
            return example(spec, next((o for o in options if _type(o) != "null"), options[0]), seen)
    t = _type(schema)
    if t == "string":
        return STRING_FORMATS.get(str(schema.get("format", "")).lower(), "<string>")
    if t == "boolean":
        return True
    if t in ("number", "integer"):
        lo, hi = schema.get("minimum"), schema.get("maximum")
        n = (lo + hi) / 2 if lo is not None and hi is not None else lo + 1 if lo is not None \
            else (123 if hi is None or hi > 123 else hi - 1)
        return int(n) if t == "integer" else n
    if t == "object":
        return {k: example(spec, v, seen) for k, v in schema.get("properties", {}).items()
                if not resolve(spec, v, seen)[0].get("readOnly")}
    if t == "array":
        return [example(spec, schema["items"], seen)] if isinstance(schema.get("items"), dict) else []
    if t == "null":
        return None
    return {} if not t else "<unknown>"


def _is_file(spec: dict, schema: dict) -> bool:
    schema, _ = resolve(spec, schema)
    if _type(schema) == "array" and isinstance(schema.get("items"), dict):
        return _is_file(spec, schema["items"])
    return _type(schema) == "string" and (schema.get("format") == "binary" or "contentMediaType" in schema)


def _text(value) -> str:
    """A form or query value as text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value if isinstance(value, str) else json.dumps(value)


def _query_pairs(name: str, value, param: dict) -> list[tuple[str, str]]:
    """A query parameter as (name, value) pairs, serialized per its OpenAPI style and explode
    (default form, exploded: ids=a&ids=b)."""
    if not isinstance(value, list):
        return [(name, _text(value))]
    style = param.get("style", "form")
    if style == "form" and param.get("explode", True):
        return [(name, _text(v)) for v in value]
    sep = {"spaceDelimited": " ", "pipeDelimited": "|"}.get(style, ",")
    return [(name, sep.join(_text(v) for v in value))]


def _grouped(pairs: list[tuple[str, str]]) -> dict:
    """(name, value) pairs -> {name: value}, or {name: [values]} for a repeated name."""
    out: dict = {}
    for k, v in pairs:
        out.setdefault(k, []).append(v)
    return {k: v[0] if len(v) == 1 else v for k, v in out.items()}


def request(spec: dict, path: str, method: str) -> dict:
    """What an example request to an operation sends: URL, query, headers and body."""
    item = spec["paths"][path]
    op = item[method]
    server = (op.get("servers") or item.get("servers") or spec["servers"])[0]
    base = server["url"]
    for name, var in (server.get("variables") or {}).items():
        base = base.replace("{" + name + "}", str(var.get("default", "")))
    params = {}
    for p in [*item.get("parameters", []), *op.get("parameters", [])]:
        p, _ = resolve(spec, p)
        params[(p["name"], p["in"])] = p
    query: list[tuple[str, str]] = []
    headers: dict[str, str] = {}
    for (name, where), p in params.items():
        if not p.get("required") or where not in ("query", "header"):
            continue
        value = p["example"] if "example" in p else example(spec, p.get("schema", {}))
        if where == "query":
            query += _query_pairs(name, value, p)
        else:
            headers[name] = _text(value)
    security = op.get("security", spec.get("security", []))
    if any(s for s in security):
        headers = {"Authorization": "Bearer <token>", **headers}

    body = None
    rb, _ = resolve(spec, op.get("requestBody") or {})
    content = rb.get("content") or {}
    kind = next((c for c in BODY_TYPES if c in content), next(iter(content), None))
    if kind:
        media = content[kind]
        if "example" in media:
            value = media["example"]
        elif media.get("examples"):
            value = resolve(spec, next(iter(media["examples"].values())))[0].get("value")
        else:
            value = example(spec, media.get("schema", {}))
        if kind == "multipart/form-data":
            props = resolve(spec, media.get("schema", {}))[0]
            if "allOf" in props:
                props = _merge_all_of(spec, props, frozenset())
            files = [k for k, v in props.get("properties", {}).items() if _is_file(spec, v)]
            fields = {k: _text(v) for k, v in (value or {}).items() if k not in files}
            body = {"kind": "multipart", "files": files, "fields": fields}
        elif kind == "application/x-www-form-urlencoded":
            body = {"kind": "form", "fields": {k: _text(v) for k, v in (value or {}).items()}}
        elif kind.split(";")[0].endswith("json"):  # application/json, application/merge-patch+json, ...
            body = {"kind": "json", "type": kind, "value": value}
        elif kind.startswith("text/"):
            body = {"kind": "text", "type": kind, "value": _text(value)}
        else:  # application/octet-stream, images, ...: send a file as is
            body = {"kind": "file", "type": kind}
    return {"method": method.upper(), "url": base.rstrip("/") + path, "query": query, "headers": headers, "body": body}


def _content_type(body: dict | None) -> dict[str, str]:
    """The Content-Type header an example sets itself: for a body the HTTP client does not label
    (text, a file, a JSON type other than application/json)."""
    if body and (body["kind"] in ("text", "file") or (body["kind"] == "json" and body["type"] != "application/json")):
        return {"Content-Type": body["type"]}
    return {}


# --- Python ---------------------------------------------------------------------------------------

REQUESTS_FUNCTIONS = {"get", "post", "put", "patch", "delete", "head", "options"}

def _py(value, indent: int = 0) -> str:
    pad, inner = " " * indent, " " * (indent + 4)
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{\n" + "".join(f"{inner}{json.dumps(k)}: {_py(v, indent + 4)},\n" for k, v in value.items()) + pad + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        return "[\n" + "".join(f"{inner}{_py(v, indent + 4)},\n" for v in value) + pad + "]"
    if value is True or value is False or value is None:
        return repr(value)
    return json.dumps(value, ensure_ascii=False)


def python(req: dict) -> str:
    lines = [f"# {NOTE.format(sdk='Python')}", "import requests", "", f"url = {json.dumps(req['url'])}", ""]
    args = ["url"]
    if req["query"]:
        lines += [f"params = {_py(_grouped(req['query']))}", ""]
        args.append("params=params")
    body = req["body"]
    headers = {**req["headers"], **_content_type(body)}
    if body and body["kind"] == "json":
        lines += [f"payload = {_py(body['value'])}", ""]
        args.append("json=payload")
    elif body and body["kind"] == "text":
        lines += [f"payload = {json.dumps(body['value'], ensure_ascii=False)}", ""]
        args.append("data=payload")
    elif body and body["kind"] == "file":
        lines += [f'payload = open("{FILE}", "rb")', ""]
        args.append("data=payload")
    elif body and body["fields"]:
        lines += [f"data = {_py(body['fields'])}", ""]
        args.append("data=data")
    if body and body["kind"] == "multipart" and body["files"]:
        lines += ["files = {" + ", ".join(f'{json.dumps(f)}: open("{FILE}", "rb")' for f in body["files"]) + "}", ""]
        args.append("files=files")
    if headers:
        lines += [f"headers = {_py(headers)}", ""]
        args.append("headers=headers")
    m = req["method"].lower()
    call = f"requests.{m}(" if m in REQUESTS_FUNCTIONS else f'requests.request("{req["method"]}", '
    lines += [f"response = {call}{', '.join(args)})", "", "print(response.text)"]
    return "\n".join(lines) + "\n"


# --- TypeScript -----------------------------------------------------------------------------------

def _ts(value, indent: int = 0) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False).replace("\n", "\n" + " " * indent)


def typescript(req: dict) -> str:
    lines = [f"// {NOTE.format(sdk='TypeScript')}"]
    body = req["body"]
    multipart = body and body["kind"] == "multipart"
    if (multipart and body["files"]) or (body and body["kind"] == "file"):
        lines += ['import { openAsBlob } from "node:fs";']
    lines.append("")
    url = json.dumps(req["url"])
    if req["query"]:
        names = [k for k, _ in req["query"]]
        # A repeated name needs the list-of-pairs form; an object keeps one value per name.
        if len(set(names)) < len(names):
            init = "[\n" + "".join(f"  [{json.dumps(k)}, {json.dumps(v, ensure_ascii=False)}],\n" for k, v in req["query"]) + "]"
        else:
            init = _ts(dict(req["query"]))
        lines += [f"const params = new URLSearchParams({init});", ""]
        url = "`" + req["url"] + "?${params}`"
    if multipart:
        lines.append("const form = new FormData();")
        lines += [f'form.append({json.dumps(f)}, await openAsBlob("{FILE}"), "{FILE}");' for f in body["files"]]
        lines += [f"form.append({json.dumps(k)}, {json.dumps(v)});" for k, v in body["fields"].items()]
        lines.append("")
    headers = {**req["headers"], **_content_type(body)}
    if body and body["kind"] == "json":
        headers.setdefault("Content-Type", "application/json")
    options = [f'  method: "{req["method"]}",']
    if headers:
        options.append(f"  headers: {_ts(headers, 2)},")
    if body and body["kind"] == "json":
        options.append(f"  body: JSON.stringify({_ts(body['value'], 2)}),")
    elif body and body["kind"] == "form":
        options.append(f"  body: new URLSearchParams({_ts(body['fields'], 2)}),")
    elif body and body["kind"] == "text":
        options.append(f"  body: {json.dumps(body['value'], ensure_ascii=False)},")
    elif body and body["kind"] == "file":
        options.append(f'  body: await openAsBlob("{FILE}"),')
    elif multipart:
        options.append("  body: form,")
    lines += [f"const response = await fetch({url}, {{", *options, "});", "", "console.log(await response.text());"]
    return "\n".join(lines) + "\n"


# --- Go -------------------------------------------------------------------------------------------

def go(req: dict) -> str:
    body = req["body"]
    kind = body["kind"] if body else None
    imports = {"fmt", "io", "net/http"}
    setup, body_arg = [], "nil"
    if kind == "json":
        text = json.dumps(body["value"], indent=2, ensure_ascii=False)
        literal = f"`{text}`" if "`" not in text else json.dumps(text)
        setup += [f"payload := strings.NewReader({literal})", ""]
        imports.add("strings")
        body_arg = "payload"
    elif kind == "form":
        setup.append("form := url.Values{}")
        setup += [f"form.Set({json.dumps(k)}, {json.dumps(v)})" for k, v in body["fields"].items()]
        setup.append("")
        imports |= {"net/url", "strings"}
        body_arg = "strings.NewReader(form.Encode())"
    elif kind == "multipart":
        imports |= {"bytes", "mime/multipart"}
        setup += ["var payload bytes.Buffer", "form := multipart.NewWriter(&payload)"]
        if body["files"]:
            imports.add("os")
        for f in body["files"]:
            part = [
                f'file, err := os.Open("{FILE}")',
                "if err != nil {", "\tpanic(err)", "}",
                "defer file.Close()",
                f'part, err := form.CreateFormFile({json.dumps(f)}, "{FILE}")',
                "if err != nil {", "\tpanic(err)", "}",
                "if _, err := io.Copy(part, file); err != nil {", "\tpanic(err)", "}",
            ]
            # One block per file field when there are several, so the variable names do not clash.
            setup += ["{", *("\t" + x for x in part), "}"] if len(body["files"]) > 1 else [*part, ""]
        setup += [f"form.WriteField({json.dumps(k)}, {json.dumps(v)})" for k, v in body["fields"].items()]
        setup += ["form.Close()", ""]
        body_arg = "&payload"
    elif kind == "text":
        setup += [f"payload := strings.NewReader({json.dumps(body['value'])})", ""]
        imports.add("strings")
        body_arg = "payload"
    elif kind == "file":
        setup += [f'file, err := os.Open("{FILE}")', "if err != nil {", "\tpanic(err)", "}", "defer file.Close()", ""]
        imports.add("os")
        body_arg = "file"
    if req["query"]:
        imports.add("net/url")

    main = [*setup, f'req, err := http.NewRequest("{req["method"]}", {json.dumps(req["url"])}, {body_arg})',
            "if err != nil {", "\tpanic(err)", "}"]
    if req["query"]:
        main.append("query := url.Values{}")
        main += [f"query.Add({json.dumps(k)}, {json.dumps(v)})" for k, v in req["query"]]
        main.append("req.URL.RawQuery = query.Encode()")
    main += [f"req.Header.Set({json.dumps(k)}, {json.dumps(v)})" for k, v in req["headers"].items()]
    if kind in ("json", "text", "file"):
        main.append(f'req.Header.Set("Content-Type", {json.dumps(body["type"])})')
    elif kind == "form":
        main.append('req.Header.Set("Content-Type", "application/x-www-form-urlencoded")')
    elif kind == "multipart":
        main.append('req.Header.Set("Content-Type", form.FormDataContentType())')
    main += ["", "res, err := http.DefaultClient.Do(req)", "if err != nil {", "\tpanic(err)", "}",
             "defer res.Body.Close()", "", "out, err := io.ReadAll(res.Body)", "if err != nil {", "\tpanic(err)", "}",
             "fmt.Println(string(out))"]

    std = sorted(imports)
    lines = [f"// {NOTE.format(sdk='Go')}", "package main", "", "import (", *(f'\t"{i}"' for i in std), ")", "",
             "func main() {"]
    for line in main:
        lines.append(("\t" + line.replace("\n", "\n\t")) if line else "")
    lines.append("}")
    return "\n".join(lines) + "\n"


GENERATORS = {"python": python, "typescript": typescript, "go": go}
