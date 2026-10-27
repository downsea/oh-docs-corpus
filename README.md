# oh-docs-corpus

Release-only data repository for [oh](https://github.com/downsea/oh-cli)'s offline `docs.*` queries
(oh ADR-0109). Each release carries one documentation pack that `oh docs update --corpus openharmony`
downloads, verifies against `manifest.json` (sha256 + document count), and indexes locally.

## What is in a pack

- `openharmony-zh-cn-<date>-<commit8>.zip` — the Markdown files under `zh-cn/application-dev/` of
  [`openharmony/docs`](https://gitcode.com/openharmony/docs) at the commit named in the manifest, unmodified,
  plus `LICENSE` (CC BY 4.0) and `NOTICE` (attribution).
- `openharmony-zh-cn-<date>-<commit8>.zip.sha256` — `sha256sum -c` format (releases built by CI; the first,
  hand-published release has none).
- `manifest.json` — `{corpus, lang, source, commit, committed_at, documents, bytes, sha256, license, asset}`.

Packs are built by [`tools/build-docs-corpus.py`](tools/build-docs-corpus.py) (standard library only;
`--self-test` runs offline). Nothing else lives here.

## CI and releases

Packs are **built on a maintainer host** and **verified and published by CI**
([`.github/workflows/pack.yml`](.github/workflows/pack.yml)). CI does not build: a hosted runner cannot finish
the ~6,000 page fetches before gitcode throttles it. There is no push, PR or scheduled run.

1. The maintainer builds the pack locally, writes its `.sha256`, and uploads zip + `.sha256` + `manifest.json`
   as a **draft** release named `openharmony-zh-cn-<YYYYMMDD>-<commit8>` (a draft is never `releases/latest`).
2. The maintainer pushes a tag with exactly that name.
3. CI downloads the draft and lists gitcode's tree at the manifest's commit (~130 API requests, no page fetch).
   It then checks:
   - every page's git blob sha1 matches that tree, and both sides list the same pages;
   - the page count is at least the floor (≥ 5000 and ≥ 90% of the latest pack);
   - the pack is newer than `releases/latest`;
   - the manifest fields, sha256 and asset name match the tag, and the `.sha256` is present and well-formed.
4. Only when every check passes does CI publish the draft as the latest release and read the manifest back from
   the URL oh uses. Any failure leaves it a draft and states the reason.

| Event | Runs | Publishes |
|---|---|---|
| push of a tag named exactly `openharmony-zh-cn-<YYYYMMDD>-<commit8>` | verifies that draft | yes, if every check passes; an already-published release is a no-op |
| Actions → Run workflow (`workflow_dispatch`, optional `tag`; empty = latest) | the same verification | **no** |

The complete command sequence for a release is in [`CLAUDE.md`](CLAUDE.md) (Releasing). The rationale and the
three CI runs that changed the route are in [`docs/research/2026-10-27-ci-for-docs-packs.md`](docs/research/2026-10-27-ci-for-docs-packs.md).

## License and attribution

The documentation content is © the OpenHarmony project contributors, licensed under
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
It is redistributed here unmodified; the source commit is recorded in every pack's manifest.
The HarmonyOS vendor documentation is **not** redistributed here — oh downloads it on the user's machine.
