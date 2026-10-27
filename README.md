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

[`.github/workflows/pack.yml`](.github/workflows/pack.yml) builds and publishes packs. There is no push,
PR or scheduled run.

| Event | Runs | Publishes |
|---|---|---|
| push of a tag named exactly `openharmony-zh-cn-<YYYYMMDD>-<commit8>` | yes | yes, if the name matches the gitcode commit, the pack is newer than `releases/latest`, and every check passes |
| Actions → Run workflow (`workflow_dispatch`, optional `commit`) | yes | **no** — builds, verifies, keeps a 1-day artifact |

```bash
python3 -I tools/build-docs-corpus.py --resolve          # the tag name for gitcode master now (--commit <hex> to pin)
git tag -a <name> -m <name> && git push origin <name>    # publish
```

Before publishing, the workflow runs the offline self-test and checks the page count against a floor
(≥ 5000 and ≥ 90% of the latest pack). It re-checks every page's git blob sha1 after unzipping, checks the
manifest against the asset name rule, and writes and checks the `.sha256`. The release is created as a draft
and made the latest one only after every asset has uploaded. A tag whose release is already published is
a no-op. Rationale: [`docs/research/2026-10-27-ci-for-docs-packs.md`](docs/research/2026-10-27-ci-for-docs-packs.md).

## License and attribution

The documentation content is © the OpenHarmony project contributors, licensed under
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
It is redistributed here unmodified; the source commit is recorded in every pack's manifest.
The HarmonyOS vendor documentation is **not** redistributed here — oh downloads it on the user's machine.
