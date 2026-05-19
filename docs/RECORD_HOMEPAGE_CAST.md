# Recording the homepage asciinema cast

The homepage `Show me` section embeds an asciinema cast at
`www/public/demo/truss-exec-wrap.cast`. This doc is the recipe for
re-recording it so the cast matches the rewritten narrative
(audit-proxy wrap of an agent CLI, not the legacy trap/translate
pipe).

The current cast file is a placeholder copy of the old
`artifact_3_unix_pipe.cast` and should be replaced.

## Setup before recording

```bash
# 1. Make sure asciinema is installed
brew install asciinema    # or: pip install asciinema

# 2. Make sure truss is on PATH and the venv is warmed up
truss --help

# 3. Make sure GEMINI_API_KEY is exported (or sourced from ~/.gemini/.env)
echo "key present: ${GEMINI_API_KEY:+yes}"

# 4. Kill any stale proxy so the cast captures a clean boot
truss kill

# 5. Optional: widen the terminal to ~120 cols and use a readable theme;
#    the cast is replayed at 0.7x in the player, so don't speed-type
```

## The recording session

```bash
# Start the recording. -i 1 trims pauses longer than 1s for tighter playback.
asciinema rec -i 1 -t "Truss exec: wrap, block, redact, verify" \
  www/public/demo/truss-exec-wrap.cast
```

Then run this sequence inside the recording — pause briefly between
each block so the cast has narrative pacing:

### Beat 1: install + wrap

```bash
# (assume install already done; if you want to record the install,
# uncomment the curl line — adds about 30s of bootstrap output)
# curl -sSL https://trusslabs.org/install.sh | bash

truss exec -- gemini-cli
```

### Beat 2: block on prompt PHI (inside the wrapped CLI)

Type at the gemini-cli prompt:

```
Patient lives at 1234 Maple Ave, Concord CA. Summarize the case note.
```

The model never sees the prompt; the CLI prints the truss block
message inline. Wait a beat for the audience to read it.

### Beat 3: redact on response (same session)

Type:

```
Write one line exactly in this format and nothing else: "DOB: 03/14/1972, condition: hypertension"
```

Output appears as `[redacted], condition: hypertension`.

### Beat 4: multi-turn continuity (still same session)

Type:

```
What medical condition did you mention?
```

The model answers normally (e.g. `hypertension`) — proving the
swap-table keeps the model's own context unbroken while the user
keeps seeing the redacted form.

Exit gemini-cli (Ctrl-C or `/exit`).

### Beat 5: verify the ledger

```bash
ls -t ~/.truss/ledger/receipts/$(date -u +%F)/ | head -3
truss verify ~/.truss/ledger/receipts
```

### Stop recording

```bash
exit       # or Ctrl-D — closes asciinema rec
```

## After recording

- Inspect the cast in a player to confirm timing is fine and no
  secrets leaked: `asciinema play www/public/demo/truss-exec-wrap.cast`
- If anything sensitive made it in (real PHI, real key in env output),
  re-record. The cast is text-only but it IS public when shipped.
- The homepage already references `/demo/truss-exec-wrap.cast` — just
  overwrite the file and rebuild the site.
- Speed and theme are set in `www/src/pages/index.astro`:
  `speed: 0.7, theme: 'asciinema'`.

## Optional: replace the install.sh tarball reference

The current install.sh in `www/public/install.sh` still points at
`truss-primitives.tar.gz` and bootstraps the v0.2.3-era primitives
layout. If you want the homepage snippet's `curl | bash` to install
a `truss` binary that actually has the `exec` subcommand, that
install script needs a refresh too — out of scope for the cast
recording, but worth tracking.
