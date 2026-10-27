# oh-docs-corpus

Release-only data repository for [oh](https://github.com/downsea/oh-cli)'s offline `docs.*` queries
(oh ADR-0109). Each release carries one documentation pack that `oh docs update --corpus openharmony`
downloads, verifies against `manifest.json` (sha256 + document count), and indexes locally.

## What is in a pack

- `openharmony-zh-cn-<date>-<commit8>.zip` — the Markdown files under `zh-cn/application-dev/` of
  [`openharmony/docs`](https://gitcode.com/openharmony/docs) at the commit named in the manifest, unmodified,
  plus `LICENSE` (CC BY 4.0) and `NOTICE` (attribution).
- `manifest.json` — `{corpus, lang, source, commit, committed_at, documents, bytes, sha256, license}`.

Packs are built by `scripts/build-docs-corpus.py` in the oh repository. Nothing else lives here.

## License and attribution

The documentation content is © the OpenHarmony project contributors, licensed under
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
It is redistributed here unmodified; the source commit is recorded in every pack's manifest.
The HarmonyOS vendor documentation is **not** redistributed here — oh downloads it on the user's machine.
