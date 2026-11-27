# open-api
OpenAPI specs for the Pipeshub APIs 

## API reference and SDK docs

`.github/workflows/sdk-docs.yml` builds the **API reference** of [docs.pipeshub.com](https://docs.pipeshub.com) and opens a pull request in `pipeshub-ai/documentation`: the public endpoints of the latest `pipeshub-ai` release's spec, one sidebar group per service, with the Python, TypeScript and Go example of the latest SDK release on each endpoint the SDKs cover. Service-to-service endpoints are left out. The list of services on `developer/api-reference.mdx` is generated too.

Every endpoint page has Python, TypeScript and Go examples next to cURL. Where the SDKs cover the endpoint, they are the SDKs' examples and the endpoint has an **SDK** badge in the sidebar; elsewhere they are plain HTTP requests (`scripts/http_examples.py`) whose first line says the SDK doesn't cover the endpoint yet. The per-service counts on `developer/api-reference.mdx` are generated from the same data. The SDK guide (`developer/sdks.mdx`) is written by hand.

The code samples come from each SDK repo's `docs/sdks/*/README.md`, so no Speakeasy key is needed. It runs daily, on an `sdk-release` repository dispatch, or from the Actions tab. Locally:

```bash
python scripts/build_sdk_docs.py --sdks <dir with the three SDK clones> --docs <documentation checkout> \
  --spec <pipeshub-ai pipeshub-openapi.yaml at a release>
```
