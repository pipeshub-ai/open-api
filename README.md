# open-api
OpenAPI specs for the Pipeshub APIs 

## Versioned SDK docs

`.github/workflows/sdk-docs.yml` builds the SDKs tab of [docs.pipeshub.com](https://docs.pipeshub.com/sdks/overview) and opens a pull request in `pipeshub-ai/documentation`. For every release tag the three SDK repos share, it writes the spec that release was generated from (with Python, TypeScript and Go code samples from `speakeasy generate codeSamples`) and each SDK's README at that tag. Run it from the Actions tab, or locally:

```bash
python scripts/build_sdk_docs.py --sdks <dir with the three SDK clones> --open-api . --docs <documentation checkout>
```
