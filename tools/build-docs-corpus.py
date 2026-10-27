#!/usr/bin/env python3
"""build-docs-corpus.py — pack the OpenHarmony docs corpus for `oh docs update` (oh ADR-0109).

The canonical copy lives in `downsea/oh-docs-corpus` (`tools/`); oh-cli keeps none
(it moved here from oh-cli `scripts/build-docs-corpus.py`, oh #741). It is not shipped
with oh. It never publishes: it writes files into the directory you name, and the
`pack` workflow of this repository (`.github/workflows/pack.yml`) publishes them.

What a build does (the same steps as `oh docs update`'s gitcode fallback, so the two
routes produce one archive shape):

  1. resolve a gitcode `openharmony/docs` commit (default: `master` now) and its tree;
  2. walk `zh-cn` → `application-dev`, list the tree recursively in pages of 100;
  3. fetch every `.md` from `raw.gitcode.com` at that commit, 8 at a time (3 attempts,
     30 s timeout, `1 + attempt` s back-off), each checked against its git blob sha1;
  4. fetch `LICENSE` (CC BY 4.0, full text) from the same commit, write `NOTICE`
     (attribution + source commit);
  5. write `openharmony-zh-cn-<YYYYMMDD>-<commit8>.zip` — pages under `docs/`, plus
     `LICENSE` and `NOTICE` at the root, deflate-9, sorted, fixed timestamps — and
     `manifest.json`:

       {corpus, lang, source, commit, committed_at, documents, bytes, sha256, license, asset}

     `<YYYYMMDD>` is the date part of `committed_at` as gitcode writes it. That field
     set, the asset name and the zip layout are oh's consumer contract: never change
     them here alone (oh `src/docs_corpus/update.rs::check_release_manifest`).

Modes (standard library only; run it isolated, with directories as arguments):

    python3 -I tools/build-docs-corpus.py --self-test                # offline, no network
    python3 -I tools/build-docs-corpus.py --resolve [--commit SHA]   # 1 GET, prints JSON, writes nothing
        [--previous-manifest FILE --require-newer]
    python3 -I tools/build-docs-corpus.py --out DIR [--commit SHA]   # the build (~6,100 GETs)
        [--min-documents N] [--previous-manifest FILE] [--pages-tsv FILE]
    python3 -I tools/build-docs-corpus.py --verify DIR               # offline check of a built DIR
        [--pages-tsv FILE] [--min-documents N] [--previous-manifest FILE]
        [--expect-asset NAME] [--require-newer]

`--commit` takes 7-40 lowercase hex; the build always pins the full 40-hex sha gitcode
returns, and refuses an answer that does not start with the prefix asked for.
The document floor is max(--min-documents, ceil(0.9 x the previous manifest's
`documents`)): a gitcode listing that comes back short stops the build before the
page fetches, and `--verify` checks the same floor again on what was written.

The network goes through the environment's HTTPS_PROXY (urllib's ProxyHandler).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

API = "https://api.gitcode.com/api/v5"
RAW = "https://raw.gitcode.com"
REPO = "openharmony/docs"
SOURCE = "https://gitcode.com/openharmony/docs"
CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"
CC_BY_HEAD = b"Attribution 4.0 International"
PREFIX = "zh-cn/application-dev/"
PER_PAGE = 100
MAX_PAGES = 1000
ATTEMPTS = 3
GET_ATTEMPTS = 4
GET_TIMEOUT = 60
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEXPREFIX = re.compile(r"^[0-9a-f]{7,40}$")
MANIFEST_KEYS = {"corpus", "lang", "source", "commit", "committed_at", "documents", "bytes", "sha256", "license", "asset"}
FLOOR_RATIO = 0.9
# The consumer's limits (oh `src/docs_corpus/update.rs` MAX_DOCS_ZIP / MAX_OH_PAGES,
# `zipread.rs` MAX_ENTRIES / MAX_ENTRY_UNCOMPRESSED / MAX_TOTAL_UNCOMPRESSED at oh
# 001439b7). A pack past any of them would publish fine and fail on every user's
# machine, so `--verify` refuses it here.
OH_MAX_ZIP_BYTES = 256 * 1024 * 1024
OH_MAX_ENTRIES = 64_000
OH_MAX_ENTRY_BYTES = 4 * 1024 * 1024
OH_MAX_TOTAL_BYTES = 512 * 1024 * 1024


def die(msg: str) -> None:
    print(f"build-docs-corpus: {msg}", file=sys.stderr)
    sys.exit(1)


def git_blob_sha1(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def version_of(commit: str, committed_at: str) -> str:
    if not HEX40.match(commit):
        raise ValueError(f"not a 40-hex commit: {commit!r}")
    if not re.match(r"^\d{4}-\d{2}-\d{2}", committed_at):
        raise ValueError(f"not an ISO date: {committed_at!r}")
    return committed_at[:10].replace("-", "") + "-" + commit[:8]


def asset_of(version: str) -> str:
    return f"openharmony-zh-cn-{version}.zip"


def notice(commit: str, committed_at: str) -> str:
    # Byte-identical to `oh_notice` in oh's src/docs_corpus/update.rs; the self-test
    # pins the bytes (NOTICE_GOLDEN_SHA256) so a drift on this side goes red here.
    return (
        "OpenHarmony documentation, zh-cn/application-dev\n"
        "Copyright (c) OpenHarmony Project contributors (openharmony/docs)\n"
        f"Source: {SOURCE}/tree/{commit}/zh-cn/application-dev\n"
        f"Commit: {commit} ({committed_at})\n"
        "License: Creative Commons Attribution 4.0 International (CC BY 4.0), see LICENSE\n"
        f"         {CC_BY_URL}\n"
        "Changes: none to any page; the Markdown files are byte-identical to the source commit\n"
        "         and only repackaged (non-Markdown files such as images are not included).\n"
    )


def path_ok(p: str) -> bool:
    return (
        bool(p)
        and not p.startswith("/")
        and "\\" not in p
        and ":" not in p
        and "\0" not in p
        and all(seg not in ("", ".", "..") for seg in p.split("/"))
    )


def parse_time(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"no UTC offset in {s!r}")
    return t


def read_manifest(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        m = json.load(f)
    if not isinstance(m, dict):
        die(f"{path} is not a JSON object")
    return m


def floor_of(min_documents: int, previous: dict | None) -> int:
    """The fewest pages a pack may hold: max(N, ceil(0.9 x previous documents))."""
    floor = max(1, min_documents)
    if previous is not None:
        prev = previous.get("documents")
        if not isinstance(prev, int) or prev < 1:
            die(f"the previous manifest has no usable documents count: {prev!r}")
        floor = max(floor, math.ceil(FLOOR_RATIO * prev))
    return floor


def check_newer(commit: str, date: str, previous: dict | None, require: bool) -> bool | None:
    """Is (commit, date) newer than the previous manifest? None when there is none.

    `releases/latest` is the most recently created release, so publishing an older
    commit would turn every user's `oh docs update` back to older docs; `require`
    makes that a stop.
    """
    if previous is None:
        if require:
            die("--require-newer needs --previous-manifest")
        return None
    try:
        newer = parse_time(date) > parse_time(str(previous.get("committed_at", ""))) and commit != previous.get("commit")
    except ValueError as e:
        die(f"committed_at: {e}")
    if require and not newer:
        die(
            f"{commit[:8]} ({date}) is not newer than the latest release "
            f"{str(previous.get('commit'))[:8]} ({previous.get('committed_at')}); "
            "publishing it would turn releases/latest back to older docs"
        )
    return newer


class Http:
    """GET with the environment's proxy; `get(url) -> bytes`."""

    def __init__(self) -> None:
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler())

    def get(self, url: str) -> bytes:
        # Every request retries a transient failure: a read timeout surfaces as a bare
        # TimeoutError (not a URLError), and a GitHub runner abroad reaches gitcode's API
        # slowly — the first CI dry run (run 40469004197) died on one unretried timeout
        # while resolving the tree. A 4xx other than 429 is an answer, never retried.
        req = urllib.request.Request(url, headers={"User-Agent": "oh-docs-corpus build-docs-corpus"})
        for attempt in range(GET_ATTEMPTS):
            try:
                with self.opener.open(req, timeout=GET_TIMEOUT) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code != 429 and e.code < 500 or attempt == GET_ATTEMPTS - 1:
                    raise
            except (TimeoutError, ConnectionError, urllib.error.URLError):
                if attempt == GET_ATTEMPTS - 1:
                    raise
            time.sleep(2 * (1 + attempt))
        raise AssertionError("unreachable")


def get_json(http, url: str):
    return json.loads(http.get(url))


def resolve_commit(http, api: str, commit: str | None):
    # Always the list endpoint, `sha=<ref>` first: gitcode's single-commit answer
    # (`commits/<sha>`) carries no `commit.tree` (measured on oh-vm 2026-10-27), so a
    # pinned `--commit` resolved through it never got a tree. The list endpoint takes
    # a branch, a full sha or a prefix and answers with the tree (same date).
    ref = commit or "master"
    try:
        lst = get_json(http, f"{api}/repos/{REPO}/commits?sha={ref}&per_page=1")
    except OSError as e:  # urllib's HTTPError / URLError are OSErrors
        die(f"gitcode could not resolve {ref}: {e}")
    if not lst:
        die(f"gitcode returned no commits for {ref}")
    c = lst[0]
    sha = c.get("sha", "")
    tree = c.get("commit", {}).get("tree", {}).get("sha", "")
    date = c.get("commit", {}).get("committer", {}).get("date", "")
    if not HEX40.match(sha) or not HEX40.match(tree):
        die(f"gitcode commit answer has no usable sha / tree: {sha!r} {tree!r}")
    if commit and not sha.startswith(commit):
        die(f"asked gitcode for commit {commit}, it answered {sha}")
    return sha, tree, date


def resolve(http, commit: str | None, api: str = API) -> dict:
    """What a build of `commit` would be called, without building it."""
    sha, _tree, date = resolve_commit(http, api, commit)
    try:
        version = version_of(sha, date)
    except ValueError as e:
        die(str(e))
    asset = asset_of(version)
    return {"commit": sha, "committed_at": date, "version": version, "asset": asset, "tag": asset[: -len(".zip")]}


def child_tree(http, api: str, sha: str, name: str) -> str:
    for page in range(1, MAX_PAGES + 1):
        v = get_json(http, f"{api}/repos/{REPO}/git/trees/{sha}?per_page={PER_PAGE}&page={page}")
        tree = v.get("tree") or []
        for t in tree:
            if t.get("path") == name and t.get("type") == "tree" and HEX40.match(t.get("sha", "")):
                return t["sha"]
        if len(tree) < PER_PAGE:
            break
    die(f"tree {sha} has no {name!r}")
    return ""


def list_pages(http, api: str, sha: str, workers: int):
    """Every `.md` blob under tree `sha`: [(path, blob sha)], pages fetched `workers` at a time."""
    out: dict[str, str] = {}
    page = 1
    while page <= MAX_PAGES:
        batch = list(range(page, min(page + workers, MAX_PAGES + 1)))
        urls = [f"{api}/repos/{REPO}/git/trees/{sha}?recursive=1&per_page={PER_PAGE}&page={p}" for p in batch]

        def safe(u):
            try:
                return get_json(http, u), None
            except Exception as e:  # noqa: BLE001 — a page past the last one may not exist
                return None, e

        with cf.ThreadPoolExecutor(len(urls)) as ex:
            results = list(ex.map(safe, urls))
        last = False
        # In page order; the first short page is the last one, and a page past it may
        # fail without failing the listing (the same rule as oh's fallback route).
        for v, err in results:
            if err is not None:
                raise err
            tree = v.get("tree") or []
            for t in tree:
                p, s = t.get("path", ""), t.get("sha", "")
                if t.get("type") == "blob" and p.endswith(".md") and path_ok(p) and HEX40.match(s):
                    out.setdefault(p, s)
            if len(tree) < PER_PAGE:
                last = True
                break
        if last:
            break
        page += workers
    return sorted(out.items())


def fetch_pages(http, raw: str, commit: str, rows, workers: int, delay: float = 1.0):
    def one(row):
        path, sha = row
        url = f"{raw}/{REPO}/raw/{commit}/{urllib.parse.quote(PREFIX + path)}"
        err = ""
        for attempt in range(ATTEMPTS):
            try:
                b = http.get(url)
                if git_blob_sha1(b) == sha:
                    return path, b, None
                err = "git blob sha1 mismatch"
            except Exception as e:  # noqa: BLE001 — retried, then reported
                err = repr(e)[:120]
            time.sleep(delay * (1 + attempt))
        return path, None, err

    got: dict[str, bytes] = {}
    fails = []
    with cf.ThreadPoolExecutor(workers) as ex:
        for path, b, err in ex.map(one, rows):
            if b is None:
                fails.append((path, err))
            else:
                got[path] = b
    if fails:
        for p, e in fails[:10]:
            print(f"FAIL {p}: {e}", file=sys.stderr)
        die(f"{len(fails)} of {len(rows)} pages failed; nothing written")
    return got


def pack(pages: dict[str, bytes], license_text: bytes, commit: str, committed_at: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=False) as z:

        def add(name: str, data: bytes) -> None:
            zi = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data, compresslevel=9)

        add("LICENSE", license_text)
        add("NOTICE", notice(commit, committed_at).encode())
        for path in sorted(pages):
            add("docs/" + path, pages[path])
    return buf.getvalue()


def manifest(zip_bytes: bytes, documents: int, commit: str, committed_at: str) -> dict:
    version = version_of(commit, committed_at)
    return {
        "corpus": "openharmony",
        "lang": "zh-cn",
        "source": SOURCE,
        "commit": commit,
        "committed_at": committed_at,
        "documents": documents,
        "bytes": len(zip_bytes),
        "sha256": hashlib.sha256(zip_bytes).hexdigest(),
        "license": "CC-BY-4.0",
        "asset": asset_of(version),
    }


def build(
    http,
    out_dir: str,
    commit: str | None,
    workers: int,
    api: str = API,
    raw: str = RAW,
    delay: float = 1.0,
    min_documents: int = 1,
    pages_tsv: str | None = None,
) -> dict:
    t0 = time.time()
    sha, tree, date = resolve_commit(http, api, commit)
    zh = child_tree(http, api, tree, "zh-cn")
    app = child_tree(http, api, zh, "application-dev")
    rows = list_pages(http, api, app, workers)
    if not rows:
        die("no pages listed under zh-cn/application-dev")
    print(f"commit {sha} ({date}): {len(rows)} pages listed", file=sys.stderr)
    if len(rows) < min_documents:
        die(f"gitcode listed {len(rows)} pages, below the floor of {min_documents}; nothing fetched or written")
    lic = http.get(f"{raw}/{REPO}/raw/{sha}/LICENSE")
    if not lic.lstrip().startswith(CC_BY_HEAD):
        die("the upstream LICENSE is not the CC BY 4.0 text")
    pages = fetch_pages(http, raw, sha, rows, workers, delay)
    data = pack(pages, lic, sha, date)
    m = manifest(data, len(pages), sha, date)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, m["asset"]), "wb") as f:
        f.write(data)
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)
        f.write("\n")
    if pages_tsv:
        # `<blob sha1>\t<path under application-dev>`, one line per page, sorted —
        # the listing `--verify` re-checks every page of the written zip against.
        with open(pages_tsv, "w", encoding="utf-8") as f:
            for path, s in rows:
                f.write(f"{s}\t{path}\n")
    print(f"wrote {m['asset']} ({m['bytes']} B, {m['documents']} pages) + manifest.json in {time.time() - t0:.1f}s", file=sys.stderr)
    return m


# ---------------------------------------------------------------------------
# --verify: offline, what the publish step relies on
# ---------------------------------------------------------------------------


def verify(
    out_dir: str,
    pages_tsv: str | None = None,
    min_documents: int = 1,
    previous: dict | None = None,
    expect_asset: str | None = None,
    require_newer: bool = False,
) -> dict:
    """Re-check a built directory end to end; die on the first failure, else a report."""
    m = read_manifest(os.path.join(out_dir, "manifest.json"))
    if set(m) != MANIFEST_KEYS:
        die(f"manifest fields are {sorted(m)}, the contract is {sorted(MANIFEST_KEYS)}")
    fixed = {"corpus": "openharmony", "lang": "zh-cn", "source": SOURCE, "license": "CC-BY-4.0"}
    for k, v in fixed.items():
        if m[k] != v:
            die(f"manifest {k} is {m[k]!r}, expected {v!r}")
    commit, date = m["commit"], m["committed_at"]
    try:
        version = version_of(commit, date)
        parse_time(date)
    except ValueError as e:
        die(f"manifest commit / committed_at: {e}")
    asset = asset_of(version)
    if m["asset"] != asset:
        die(f"manifest asset is {m['asset']!r}, the name rule gives {asset!r}")
    if expect_asset is not None and asset != expect_asset:
        die(f"the pack is {asset!r}, expected {expect_asset!r}")
    present = set(os.listdir(out_dir))
    allowed = {"manifest.json", asset, asset + ".sha256"}
    if not {"manifest.json", asset} <= present or present - allowed:
        die(f"{out_dir} holds {sorted(present)}; expected manifest.json, {asset} and optionally {asset}.sha256")
    with open(os.path.join(out_dir, asset), "rb") as f:
        data = f.read()
    digest = hashlib.sha256(data).hexdigest()
    if not isinstance(m["bytes"], int) or len(data) != m["bytes"] or digest != m["sha256"]:
        die(f"{asset} is {len(data)} B / sha256 {digest}; the manifest says {m['bytes']} / {m['sha256']}")
    if len(data) > OH_MAX_ZIP_BYTES:
        die(f"{asset} is {len(data)} B, past oh's {OH_MAX_ZIP_BYTES} B limit")
    sidecar = os.path.join(out_dir, asset + ".sha256")
    if os.path.exists(sidecar):
        with open(sidecar, "rb") as f:
            got = f.read()
        if got != f"{digest}  {asset}\n".encode():
            die(f"{asset}.sha256 is not '<hash>  <file>\\n' for this asset: {got[:200]!r}")

    z = zipfile.ZipFile(io.BytesIO(data))
    bad = z.testzip()
    if bad is not None:
        die(f"CRC check failed on {bad!r}")
    infos = z.infolist()
    names = [i.filename for i in infos]
    if len(infos) > OH_MAX_ENTRIES:
        die(f"{len(infos)} entries, past oh's {OH_MAX_ENTRIES}")
    if names[:2] != ["LICENSE", "NOTICE"]:
        die(f"the archive must start with LICENSE, NOTICE; it starts with {names[:2]}")
    if len(set(names)) != len(names):
        die("the archive has duplicate entries")
    total = 0
    for i in infos:
        total += i.file_size
        if i.compress_type != zipfile.ZIP_DEFLATED or i.flag_bits & 0x08:
            die(f"{i.filename!r} is not plain deflate without a data descriptor")
        if i.file_size > OH_MAX_ENTRY_BYTES:
            die(f"{i.filename!r} unpacks to {i.file_size} B, past oh's {OH_MAX_ENTRY_BYTES}")
    if total > OH_MAX_TOTAL_BYTES:
        die(f"the archive unpacks to {total} B, past oh's {OH_MAX_TOTAL_BYTES}")
    docs = names[2:]
    if docs != sorted(docs):
        die("pages are not in sorted order")
    for n in docs:
        if not (n.startswith("docs/") and n.endswith(".md") and path_ok(n[len("docs/"):])):
            die(f"unexpected entry {n!r}")
    if len(docs) != m["documents"]:
        die(f"the archive holds {len(docs)} pages, the manifest says {m['documents']}")
    if z.read("NOTICE") != notice(commit, date).encode():
        die("NOTICE is not the attribution text for this commit")
    if not z.read("LICENSE").lstrip().startswith(CC_BY_HEAD):
        die("LICENSE is not the CC BY 4.0 text")

    checked = 0
    if pages_tsv is not None:
        want: dict[str, str] = {}
        with open(pages_tsv, encoding="utf-8") as f:
            for line in f:
                s, _, p = line.rstrip("\n").partition("\t")
                if not HEX40.match(s) or not p or p in want:
                    die(f"bad pages-tsv line {line!r}")
                want[p] = s
        have = {n[len("docs/"):] for n in docs}
        if set(want) != have:
            die(f"pages-tsv and the archive disagree: {len(set(want) - have)} listed but missing, {len(have - set(want))} extra")
        for n in docs:
            if git_blob_sha1(z.read(n)) != want[n[len("docs/"):]]:
                die(f"{n!r} does not match its git blob sha1")
            checked += 1

    floor = floor_of(min_documents, previous)
    if m["documents"] < floor:
        die(f"{m['documents']} pages is below the floor of {floor} (min {min_documents}, {FLOOR_RATIO:.0%} of the previous pack)")
    newer = check_newer(commit, date, previous, require_newer)
    return {
        "asset": asset,
        "tag": asset[: -len(".zip")],
        "commit": commit,
        "committed_at": date,
        "documents": m["documents"],
        "bytes": m["bytes"],
        "sha256": digest,
        "floor": floor,
        "blob_sha1_checked": checked,
        "newer_than_previous": newer,
    }


# ---------------------------------------------------------------------------
# --self-test: offline, a synthetic gitcode in memory
# ---------------------------------------------------------------------------

# sha256 of notice(SELF_TEST_COMMIT, SELF_TEST_DATE). The NOTICE bytes are a contract
# with oh (`oh_notice`, pinned on that side by oh `src/docs_corpus/update/tests.rs`);
# changing the text needs the same change there, then this constant.
NOTICE_GOLDEN_SHA256 = "f8699c0c003a126bc7f1df8af39c586d0c7dca5cb05b22129e06b84185ddb86e"


class FakeHttp:
    def __init__(self, routes: dict[str, bytes]) -> None:
        self.routes = routes
        self.seen: list[str] = []

    def get(self, url: str) -> bytes:
        self.seen.append(url)
        if url not in self.routes:
            raise OSError(f"404 {url}")
        return self.routes[url]


def expect_die(fn, what: str) -> None:
    try:
        fn()
    except SystemExit as e:
        assert e.code == 1, (what, e.code)
    else:
        raise AssertionError(f"{what} must fail")


SELF_TEST_COMMIT = "5a7da946d26bf00d2011e61a5e57cc9a02f4859a"
SELF_TEST_DATE = "2026-10-27T12:41:11+08:00"


def self_test() -> int:
    commit, date = SELF_TEST_COMMIT, SELF_TEST_DATE
    root_t, zh_t, app_t = "1" * 40, "2" * 40, "3" * 40
    pages = {
        "task-management/continuous-task.md": "# 合成页面\n\n## 约束\n合成。\n".encode(),
        "ui/布局 演示.md": "# 合成 UI\n".encode(),
    }
    j = lambda v: json.dumps(v).encode()  # noqa: E731
    head = {"sha": commit, "commit": {"tree": {"sha": root_t}, "committer": {"date": date}}}
    routes = {
        f"{API}/repos/{REPO}/commits?sha=master&per_page=1": j([head]),
        f"{API}/repos/{REPO}/commits?sha={commit[:8]}&per_page=1": j([head]),
        f"{API}/repos/{REPO}/commits?sha={commit}&per_page=1": j([head]),
        # The single-commit answer has no tree (as gitcode's); resolving must not use it.
        f"{API}/repos/{REPO}/commits/{commit}": j({"sha": commit, "commit": {"committer": {"date": date}}}),
        f"{API}/repos/{REPO}/git/trees/{root_t}?per_page=100&page=1": j({"tree": [{"type": "tree", "path": "zh-cn", "sha": zh_t}]}),
        f"{API}/repos/{REPO}/git/trees/{zh_t}?per_page=100&page=1": j({"tree": [{"type": "tree", "path": "application-dev", "sha": app_t}]}),
        f"{RAW}/{REPO}/raw/{commit}/LICENSE": b"Attribution 4.0 International\n\nsynthetic\n",
    }
    entries = [{"type": "tree", "path": "ui", "sha": "4" * 40}, {"type": "blob", "path": "figures/x.png", "sha": "5" * 40}]
    for p, b in pages.items():
        entries.append({"type": "blob", "path": p, "sha": git_blob_sha1(b)})
        routes[f"{RAW}/{REPO}/raw/{commit}/{urllib.parse.quote(PREFIX + p)}"] = b
    entries.append({"type": "blob", "path": "../evil.md", "sha": "6" * 40})
    # Only page 1 exists: pages 2..8 of the batch 404, which must not fail the listing.
    routes[f"{API}/repos/{REPO}/git/trees/{app_t}?recursive=1&per_page=100&page=1"] = j({"tree": entries})

    assert git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert version_of(commit, date) == "20261027-5a7da946"
    assert asset_of("20261027-5a7da946") == "openharmony-zh-cn-20261027-5a7da946.zip"
    assert hashlib.sha256(notice(commit, date).encode()).hexdigest() == NOTICE_GOLDEN_SHA256, "NOTICE drifted from oh"
    for bad in ("", "/a", "a/../b", "a//b", "c:x", "a\\b"):
        assert not path_ok(bad), bad
    assert floor_of(1, None) == 1 and floor_of(5000, {"documents": 5964}) == 5368 and floor_of(6000, {"documents": 10}) == 6000

    # --resolve: master and a commit prefix name the same pack; a wrong prefix is refused.
    r = resolve(FakeHttp(routes), None)
    assert r == resolve(FakeHttp(routes), commit[:8]), r
    assert r["tag"] == "openharmony-zh-cn-20261027-5a7da946" and r["commit"] == commit, r
    wrong = dict(routes)
    wrong[f"{API}/repos/{REPO}/commits?sha=deadbeef&per_page=1"] = j([head])
    expect_die(lambda: resolve(FakeHttp(wrong), "deadbeef"), "a commit answer for another prefix")

    with tempfile.TemporaryDirectory() as d:
        out, tsv = os.path.join(d, "out"), os.path.join(d, "pages.tsv")
        http = FakeHttp(routes)
        m = build(http, out, None, 8, delay=0.0, pages_tsv=tsv)
        assert m["documents"] == 2, m
        assert set(m) == MANIFEST_KEYS
        data = open(os.path.join(out, m["asset"]), "rb").read()
        assert hashlib.sha256(data).hexdigest() == m["sha256"] and len(data) == m["bytes"]
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        assert names[:2] == ["LICENSE", "NOTICE"], names
        assert "docs/ui/布局 演示.md" in names and not any("png" in n or "evil" in n for n in names), names
        assert z.read("NOTICE").decode() == notice(commit, date)
        assert all(i.compress_type == zipfile.ZIP_DEFLATED and i.flag_bits & 0x08 == 0 for i in z.infolist())
        assert len(open(tsv, encoding="utf-8").read().splitlines()) == 2
        # Deterministic: a second build (from a commit prefix) is byte-identical.
        m2 = build(FakeHttp(routes), os.path.join(d, "again"), commit[:8], 8, delay=0.0)
        assert m2 == m
        # A tampered page fails the whole build and writes nothing.
        bad = dict(routes)
        bad[f"{RAW}/{REPO}/raw/{commit}/{urllib.parse.quote(PREFIX + 'ui/布局 演示.md')}"] = b"tampered"
        expect_die(lambda: build(FakeHttp(bad), os.path.join(d, "bad"), None, 8, delay=0.0), "a tampered page")
        assert not os.path.exists(os.path.join(d, "bad"))
        # A listing below the floor stops before any page is fetched.
        short = FakeHttp(routes)
        expect_die(lambda: build(short, os.path.join(d, "short"), None, 8, delay=0.0, min_documents=3), "a short listing")
        assert not any(u.startswith(RAW) for u in short.seen) and not os.path.exists(os.path.join(d, "short"))

        # --verify: green on the build, with the sidecar the workflow writes.
        with open(os.path.join(out, m["asset"] + ".sha256"), "w", encoding="utf-8") as f:
            f.write(f"{m['sha256']}  {m['asset']}\n")
        older = {"commit": "a" * 40, "committed_at": "2026-10-20T09:00:00+08:00", "documents": 2}
        rep = verify(out, tsv, previous=older, expect_asset=m["asset"], require_newer=True)
        assert rep["blob_sha1_checked"] == 2 and rep["newer_than_previous"] is True and rep["floor"] == 2, rep
        # ... and red on every way the publish step could be fooled.
        expect_die(lambda: verify(out, expect_asset="openharmony-zh-cn-20261027-00000000.zip"), "a tag / pack mismatch")
        expect_die(lambda: verify(out, min_documents=3), "a pack below the absolute floor")
        expect_die(lambda: verify(out, previous={**older, "documents": 3}), "a pack below 90% of the previous")
        expect_die(lambda: verify(out, previous=m, require_newer=True), "re-publishing the latest commit")
        expect_die(lambda: verify(out, previous={**older, "committed_at": "2026-10-28T00:00:00+08:00"}, require_newer=True), "an older commit")
        expect_die(lambda: verify(out, require_newer=True), "--require-newer without a previous manifest")
        with open(tsv, "a", encoding="utf-8") as f:
            f.write(f"{'7' * 40}\tmissing.md\n")
        expect_die(lambda: verify(out, tsv), "a listed page missing from the archive")
        with open(os.path.join(out, m["asset"] + ".sha256"), "w", encoding="utf-8") as f:
            f.write(f"{m['sha256']} {m['asset']}\n")  # one space: not sha256sum -c format
        expect_die(lambda: verify(out), "a malformed sidecar")
        os.remove(os.path.join(out, m["asset"] + ".sha256"))
        with open(os.path.join(out, "stray.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        expect_die(lambda: verify(out), "a stray file in the pack directory")
        os.remove(os.path.join(out, "stray.txt"))
        mm = dict(m, documents=3)
        with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(mm, f)
        expect_die(lambda: verify(out), "a manifest whose count disagrees with the archive")
        with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(dict(m, extra=1), f)
        expect_die(lambda: verify(out), "a manifest with a field outside the contract")
        with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(m, f)
        with open(os.path.join(out, m["asset"]), "wb") as f:
            f.write(data[:-1] + bytes([data[-1] ^ 1]))
        expect_die(lambda: verify(out), "a corrupted archive")
    print("self-test: ok")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true", help="offline self-check, no network")
    mode.add_argument("--resolve", action="store_true", help="print the commit / version / asset / tag a build would get, as JSON")
    mode.add_argument("--verify", metavar="DIR", help="offline check of a built directory; prints a JSON report")
    ap.add_argument("--out", help="build: output directory (created); the zip and manifest.json land here")
    ap.add_argument("--commit", help="gitcode openharmony/docs commit (7-40 lowercase hex); default master now")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--min-documents", type=int, default=1, help="absolute page floor (build and verify)")
    ap.add_argument("--previous-manifest", metavar="FILE", help="the latest release's manifest.json: floor = 90%% of its count; --require-newer compares against it")
    ap.add_argument("--pages-tsv", metavar="FILE", help="build: write '<blob sha1>\\t<path>' per page; verify: re-check every page against it")
    ap.add_argument("--expect-asset", metavar="NAME", help="verify: the asset name the pack must have")
    ap.add_argument("--require-newer", action="store_true", help="resolve / verify: refuse a commit not newer than --previous-manifest")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.commit and not HEXPREFIX.match(a.commit):
        ap.error("--commit must be 7-40 lowercase hex")
    previous = read_manifest(a.previous_manifest) if a.previous_manifest else None
    if a.resolve:
        r = resolve(Http(), a.commit)
        r["newer_than_previous"] = check_newer(r["commit"], r["committed_at"], previous, a.require_newer)
        print(json.dumps(r, ensure_ascii=False))
        return 0
    if a.verify:
        rep = verify(a.verify, a.pages_tsv, a.min_documents, previous, a.expect_asset, a.require_newer)
        print(json.dumps(rep, ensure_ascii=False))
        return 0
    if not a.out:
        ap.error("--out is required (or --self-test / --resolve / --verify)")
    build(
        Http(),
        os.path.abspath(os.path.expanduser(a.out)),
        a.commit,
        max(1, a.concurrency),
        min_documents=floor_of(a.min_documents, previous),
        pages_tsv=a.pages_tsv,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
