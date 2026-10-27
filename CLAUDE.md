# CLAUDE.md
<!-- docs-check: tier=1 -->

Guidance for Claude Code working in this repository. Keep it short: entry index, hard
rules, gate. Detail lives in `docs/research/`.

## What this repo is

The **public, release-only data repository** behind `oh docs update --corpus openharmony`
(oh-cli ADR-0109, oh #741). Each release is one OpenHarmony documentation pack:
`openharmony-zh-cn-<YYYYMMDD>-<commit8>.zip` (the `.md` files under `zh-cn/application-dev/` of
gitcode `openharmony/docs` at one commit, plus `LICENSE` + `NOTICE`), its `.sha256`, and
`manifest.json`. The repo holds the packer (`tools/build-docs-corpus.py`, canonical copy)
and the workflow that publishes (`.github/workflows/pack.yml`).

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
   first; `contents: read` everywhere except the `publish` job; artifacts
   `retention-days: 1`; `workflow_dispatch` never publishes.
5. **Published releases are immutable.** Never `--clobber`, never re-upload; a bad pack is
   superseded by a newer commit's pack. Never publish a commit older than `releases/latest`.
6. **Never run a real build in `/tmp`** (tmpfs). Use `~/.cache/oh-docs-corpus-ci/`.

## Build & Test (the local gate)

```bash
actionlint                                             # zero findings
uv run --with pyyaml python -c 'import glob,yaml;[yaml.safe_load(open(f)) for f in glob.glob(".github/**/*.yml",recursive=True)]'
python3 -I tools/build-docs-corpus.py --self-test      # offline; must also pass on Python 3.10 (ubuntu-22.04)
```

## Releasing

Push a tag that is **literally** the pack name; CI builds, verifies and publishes. Full
procedure, checks and idempotency table: research `2026-10-27-ci-for-docs-packs.md` §4–§7.

```bash
python3 -I tools/build-docs-corpus.py --resolve        # prints the tag for master now (or --commit <hex>)
git tag -a <tag> -m <tag> && git push origin <tag>     # = publish
gh workflow run pack.yml -R downsea/oh-docs-corpus     # = dry run only (owed after a workflow / script change)
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
