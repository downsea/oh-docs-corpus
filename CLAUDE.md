# CLAUDE.md
<!-- docs-check: tier=1 -->

Guidance for Claude Code working in this repository. Keep it short: entry index, hard
rules, gate. Detail lives in `docs/research/`.

## What this repo is

The **public, release-only data repository** behind `oh docs update --corpus openharmony`
(oh-cli ADR-0109, oh #741). Each release is one OpenHarmony documentation pack:
`openharmony-zh-cn-<YYYYMMDD>-<commit8>.zip` (the `.md` files under `zh-cn/application-dev/` of
gitcode `openharmony/docs` at one commit, plus `LICENSE` + `NOTICE`), its `.sha256`, and
`manifest.json`. The repo holds the packer (`tools/build-docs-corpus.py`, canonical copy;
the maintainer runs it on a developer host) and the workflow that verifies a draft and
publishes it (`.github/workflows/pack.yml`).

It is **not** oh's code (oh-cli is private and owns the consumer), **not** a mirror of the
vendor HarmonyOS docs (never redistributed — oh downloads those on the user's machine),
and **not** a consumer of `downsea/ci-workflows`' reusable workflows (a public repo cannot
call a private repo's reusable workflow; research `docs/research/2026-10-27-ci-for-docs-packs.md` §1).

## Hard rules

1. **Only data packs and the tools that build them.** No oh code, no vendor documentation.
2. **The consumer contract is frozen here**: manifest fields
   `{corpus, lang, source, commit, committed_at, documents, bytes, sha256, license, asset}`,
   the asset name rule, the zip layout (LICENSE, NOTICE, then sorted `docs/**.md`) and the
   NOTICE bytes. oh `src/docs_corpus/update.rs` (`check_release_manifest`, `oh_notice`) reads
   them; a change is a two-repo change (oh first, then here), never one-sided. The
   self-test pins the NOTICE bytes (`NOTICE_GOLDEN_SHA256`) and the field set.
3. **Zero secrets.** `GITHUB_TOKEN` publishes this repo's own releases. Never add
   `SIBLING_TOKEN` or any PAT; never `set -x`.
4. **Family CI rules apply** (ci-workflows `CLAUDE.md` hard rules 4/5/7/8/9/10, CONTRACT §6):
   `ubuntu-22.04` only; `persist-credentials: false`; no pipeline whose reader can exit
   first; `contents: read` at the top, `contents: write` only on the job that reads a draft
   and promotes it; any artifact `retention-days: 1`; `workflow_dispatch` never publishes.
5. **Published releases are immutable.** Never `--clobber`, never re-upload; a bad pack is
   superseded by a newer commit's pack. Never publish a commit older than `releases/latest`.
   A *draft* that failed verification may be deleted and re-uploaded (it was never public).
6. **Build on a developer host, never in CI; never in `/tmp`** (tmpfs) — use
   `~/.cache/oh-docs-corpus-ci/`. A hosted runner cannot finish the ~6,000 raw fetches
   (gitcode throttles it with 418; research §9). CI only verifies against gitcode's tree.
7. **Vendor-neutral (owner ruling 2026-10-27).** No file, commit message or release note
   names the platform vendor: not its company name (any language or abbreviation), not its
   own-brand products and services (the official IDE, the developer console, the app store,
   the system assistant), not device marketing names. Write "the platform", "the official
   IDE", "the vendor CLI"; name a device by model code. HarmonyOS / OpenHarmony / 鸿蒙 are
   fine. **Exempt, verbatim only:** identifiers carried byte for byte — URLs, host names,
   npm package names, bundle names — with no prose around them naming the vendor.

## Build & Test (the local gate)

```bash
actionlint                                             # zero findings
uv run --with pyyaml python -c 'import glob,yaml;[yaml.safe_load(open(f)) for f in glob.glob(".github/**/*.yml",recursive=True)]'
python3 -I tools/build-docs-corpus.py --self-test      # offline; must also pass on Python 3.10 (ubuntu-22.04)
```

## Releasing

Build locally → upload as a **draft** release → push a tag that is **literally** the pack
name → CI (`pack.yml`) verifies the draft against gitcode's tree (every page's blob sha1,
floor, newer-than-latest, manifest, sidecar) and only then makes it the latest release; any
failure leaves it a draft. Draft first, tag second (the tag is the trigger). The full
command sequence is research `2026-10-27-ci-for-docs-packs.md` §7; checks §4, idempotency §5.

```bash
W=~/.cache/oh-docs-corpus-ci && mkdir -p "$W" && git pull --ff-only
curl -fsSL -o "$W/latest.json" https://github.com/downsea/oh-docs-corpus/releases/latest/download/manifest.json
eval "$(python3 -I tools/build-docs-corpus.py --resolve --shell --previous-manifest "$W/latest.json" --require-newer)"
python3 -I tools/build-docs-corpus.py --out "$W/$TAG" --commit "$COMMIT" --min-documents 5000 --previous-manifest "$W/latest.json"
(cd "$W/$TAG" && sha256sum "$ASSET" > "$ASSET.sha256")
python3 -I tools/build-docs-corpus.py --verify "$W/$TAG" --against-gitcode --require-sidecar --min-documents 5000 \
  --expect-asset "$ASSET" --previous-manifest "$W/latest.json" --require-newer       # what CI will run
gh release create "$TAG" -R downsea/oh-docs-corpus --draft --title "$TAG (draft)" --notes draft \
  "$W/$TAG/$ASSET" "$W/$TAG/$ASSET.sha256" "$W/$TAG/manifest.json"
git tag -a "$TAG" -m "$TAG" && git push origin "$TAG"                                 # = verify + publish
gh workflow run pack.yml -R downsea/oh-docs-corpus [-f tag=<name>]                     # = verify only
```

## Cross-repo

| Concern | Owner |
|---|---|
| the consumer (`oh docs update`), ADR-0109, #741 | oh-cli (private) |
| family CI rules, CONTRACT, CREDENTIALS | ci-workflows (private) |
| packer, workflow, releases | this repo |

A gap in a sibling is filed in the sibling's tracker, not worked around here.

## Commit style

Conventional commits: `feat(pack): …`, `fix(tools): …`, `docs: …`. No attribution footers
unless asked.
