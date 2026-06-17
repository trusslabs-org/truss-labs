# Truss release process

This document is the release checklist for the public Truss CLI and demo surfaces.
It exists because the CLI, installer, tarballs, static site, and demo VM can drift
unless they are verified as one release unit.

## Release surfaces

- `primitives/scripts/truss.py` — CLI source and `truss --version`.
- `pyproject.toml` — package metadata.
- `www/public/install.sh` — public installer served from `trusslabs.org/install.sh`.
- `www/public/demo/truss-primitives.tar.gz` — generic latest tarball.
- `www/public/demo/truss-primitives-vX.Y.Z.tar.gz` — versioned tarball.
- `www/src/pages/docs/index.astro` — CLI manual.
- `www/src/pages/sandbox.astro` — interactive browser sandbox.

## Canonical domains

The visible URLs should stay simple:

- `https://trusslabs.org/` — canonical main site.
- `https://trusslabs.org/docs/` — canonical docs.
- `https://trusslabs.org/sandbox` — canonical interactive sandbox.

Alias hostnames should redirect to the canonical URLs:

- `https://www.trusslabs.org/*` → `https://trusslabs.org/*`
- `https://docs.trusslabs.org/*` → `https://trusslabs.org/docs/*`

Use Cloudflare Redirect Rules for these aliases. DNS can point a hostname to a
service, but it cannot point a hostname to a path like `/docs/`; the path mapping
has to happen as an HTTP redirect.

## Pre-release checks

Run from the repo root:

```bash
VERSION="$(python3 primitives/scripts/truss.py --version | awk '{print $2}')"
grep -q "version = \"$VERSION\"" pyproject.toml
grep -q "VERSION=\"$VERSION\"" www/public/install.sh
grep -q "VERSION=\"$VERSION\"" build-tarball.sh
```

Search for stale CLI grammar:

```bash
rg "truss verify|truss translate|truss analyze|truss exec|0\\.3\\.0|0\\.1\\.0" \
  README.md docs examples www/src www/public/install.sh build-tarball.sh pyproject.toml primitives/scripts \
  -g '!*.cast'
```

Expected remaining hits are compatibility/deprecation strings in source only.

## Build artifacts

```bash
./build-tarball.sh
```

The builder must produce both:

- `www/public/demo/truss-primitives.tar.gz`
- `www/public/demo/truss-primitives-v${VERSION}.tar.gz`

## Local artifact verification

Run a fresh extraction check:

```bash
tmpdir="$(mktemp -d)"
tar -xzf www/public/demo/truss-primitives.tar.gz -C "$tmpdir" --strip-components=1
"$tmpdir/truss" --version
"$tmpdir/truss" receipt verify "$tmpdir/examples/receipts"
"$tmpdir/truss" trap clear >/dev/null
"$tmpdir/truss" trap add --on ON_RETRY --action ACTION_HALT >/dev/null
cat "$tmpdir/hooks.jsonl" \
  | "$tmpdir/truss" trace translate \
  | "$tmpdir/truss" trace analyze --json --flag FLAG_CIRCULAR_REASONING \
  | "$tmpdir/truss" trap run
"$tmpdir/truss" trap clear >/dev/null
"$tmpdir/truss" proxy exec --policy "$tmpdir/examples/policies/phi_block_address_in_external_prompt.yaml" --port 8126 -- /usr/bin/true
rm -rf "$tmpdir"
```

Run repo tests:

```bash
python3 -m unittest discover -s primitives/audit/tests -p 'test_*.py'
bash primitives/scripts/test_pipe_compose.sh
bash primitives/scripts/test_translate_pipe.sh
```

## Deploy `trusslabs.org`

From `www/`:

```bash
npm run build
npx wrangler pages deploy dist --project-name truss-labs
```

## Deploy `demo.trusslabs.org`

Re-run the GCP update flow in `examples/deploy/gcp/README.md` section
"Updating the code". The demo VM must serve `examples/demo.html` from this repo,
not a hand-edited copy.

## Post-deploy verification

Check the static site:

```bash
curl -fsSL https://trusslabs.org/install.sh | grep 'VERSION="'
curl -fsSL https://trusslabs.org/docs/ | rg 'truss proxy exec|hash-verifiable|not signed'
curl -fsSL https://trusslabs.org/ | rg 'truss proxy exec|truss receipt verify|truss trace translate'
```

Check both tarball URLs:

```bash
for url in \
  https://trusslabs.org/demo/truss-primitives.tar.gz \
  "https://trusslabs.org/demo/truss-primitives-v${VERSION}.tar.gz"
do
  tmpdir="$(mktemp -d)"
  curl -fsSL "$url" -o "$tmpdir/truss.tgz"
  tar -xzf "$tmpdir/truss.tgz" -C "$tmpdir" --strip-components=1
  "$tmpdir/truss" --version
  "$tmpdir/truss" receipt verify "$tmpdir/examples/receipts"
  rm -rf "$tmpdir"
done
```

Check the sandbox:

```bash
curl -fsSL https://trusslabs.org/sandbox | grep -o "<title>[^<]*"
```

Check docs routing:

```bash
curl -fsSL https://trusslabs.org/docs/ >/dev/null
```

`docs.trusslabs.org` is an alias, not the canonical docs route. If that subdomain
is enabled, it should redirect to `https://trusslabs.org/docs/`.

## Automation target

The durable target is a single `release` command that performs the pre-release
checks, builds artifacts, verifies fresh extractions, builds the site, deploys
Pages, refreshes the demo VM, and runs post-deploy checks. Until that exists,
this document is the release gate.
