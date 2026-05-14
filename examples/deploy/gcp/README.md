# GCP demo — `demo.trusslabs.org`

This directory provisions the audit-proxy demo on a GCP Compute Engine VM
fronted by a Cloudflare Tunnel. The VM has zero inbound ports open;
Cloudflare proxies traffic through an outbound `cloudflared` tunnel.

The architecture choice: GCP for the VM, Cloudflare Tunnel for ingress.
No inbound ports on the VM — all traffic flows out through `cloudflared`.

## Prerequisites

- `gcloud` authenticated (`gcloud auth login`) and a project selected
  (`gcloud config set project <PROJECT>`)
- `trusslabs.org` on Cloudflare (it is)
- A working `GEMINI_API_KEY` — read from `~/.gemini/.env` by the steps below
- `tar`, `ssh`, `scp` locally

Pick a project for the demo. You can use your existing one or create a fresh
`truss-labs-demo` project (recommended for billing isolation).

```bash
export PROJECT=truss-labs-demo            # or your existing project ID
export ZONE=us-east1-b
export INSTANCE=truss-demo
```

## 1. Create the VM

```bash
gcloud compute instances create "$INSTANCE" \
  --project="$PROJECT" --zone="$ZONE" \
  --machine-type=e2-small \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --tags=truss-demo
```

No firewall rule for port 80 / 443 is needed — the tunnel handles ingress.
The default GCP firewall allows outbound, which is all `cloudflared` needs.

## 2. Ship the code and run `provision.sh`

From the repo root on your laptop:

```bash
# tarball the working tree (skip caches/git/macOS metadata)
# COPYFILE_DISABLE=1 prevents BSD tar from embedding AppleDouble (._*) files
# which the policy loader would otherwise try to parse as YAML.
COPYFILE_DISABLE=1 tar -C "$(git rev-parse --show-toplevel)" \
    --exclude='.git' --exclude='__pycache__' --exclude='.venv' \
    --exclude='.DS_Store' --exclude='._*' \
    -czf /tmp/truss.tar.gz .

# stage the env file (sourced from your ~/.gemini/.env)
set -a; source ~/.gemini/.env; set +a
umask 077
cat > /tmp/truss-env-staging <<EOF
GEMINI_API_KEY=$GEMINI_API_KEY
EOF

# scp both up
gcloud compute scp /tmp/truss.tar.gz /tmp/truss-env-staging \
  "$INSTANCE":/tmp/ --project="$PROJECT" --zone="$ZONE"

# clean local copies
rm /tmp/truss.tar.gz /tmp/truss-env-staging

# run the provisioner
gcloud compute ssh "$INSTANCE" --project="$PROJECT" --zone="$ZONE" \
  --command='sudo bash -s' <<'REMOTE'
set -e
mkdir -p /opt/truss/truss-labs-staging
tar -xzf /tmp/truss.tar.gz -C /opt/truss/truss-labs-staging
bash /opt/truss/truss-labs-staging/examples/deploy/gcp/provision.sh \
  /tmp/truss.tar.gz /tmp/truss-env-staging
rm -rf /opt/truss/truss-labs-staging
REMOTE
```

If `provision.sh` exits 0 it has already curl'd `/healthz` — you should see
the JSON status in your terminal.

## 3. Set up the Cloudflare Tunnel

There are two ways. Use **3a** unless you specifically want CLI control.

### 3a. Web (Zero Trust dashboard) — recommended

1. Go to the Cloudflare Zero Trust dashboard
   <https://one.dash.cloudflare.com> → **Networks → Tunnels → Create a tunnel**.
2. Pick **Cloudflared**, name it `truss-demo`, save.
3. The dashboard shows an install command — `sudo cloudflared service install <TOKEN>`.
   SSH into the VM and run it:

   ```bash
   gcloud compute ssh "$INSTANCE" --project="$PROJECT" --zone="$ZONE"
   # on the VM:
   curl -L --output cloudflared.deb \
     https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared.deb
   sudo cloudflared service install <TOKEN>     # paste the dashboard token
   sudo systemctl status cloudflared            # should say "active (running)"
   ```

4. Back in the dashboard, **Public Hostname → Add a public hostname**:
   - Subdomain: `demo`
   - Domain: `trusslabs.org`
   - Service: **HTTP** + `localhost:8000`
5. Save. Cloudflare auto-creates the `demo.trusslabs.org` CNAME.

### 3b. CLI (alternative)

If you'd rather drive everything from the shell:

```bash
# on your laptop — opens a browser for cert.pem
cloudflared login

# create the tunnel and route DNS
cloudflared tunnel create truss-demo
TUNNEL_UUID=$(cloudflared tunnel list | awk '/truss-demo/ {print $1}')
cloudflared tunnel route dns "$TUNNEL_UUID" demo.trusslabs.org

# scp the credentials + config to the VM
gcloud compute scp ~/.cloudflared/${TUNNEL_UUID}.json \
  "$INSTANCE":/tmp/tunnel-creds.json --project="$PROJECT" --zone="$ZONE"

gcloud compute ssh "$INSTANCE" --project="$PROJECT" --zone="$ZONE" --command="
  set -e
  curl -L --output cloudflared.deb \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
  sudo dpkg -i cloudflared.deb
  sudo mkdir -p /etc/cloudflared
  sudo mv /tmp/tunnel-creds.json /etc/cloudflared/${TUNNEL_UUID}.json
  sudo sed 's|TUNNEL_UUID|${TUNNEL_UUID}|g' \
    /opt/truss/truss-labs/examples/deploy/gcp/cloudflared.config.example.yml \
    | sudo tee /etc/cloudflared/config.yml > /dev/null
  sudo cloudflared service install
  sudo systemctl status cloudflared
"
```

## 4. Smoke-test from outside

```bash
curl -s https://demo.trusslabs.org/healthz | jq
# expect: {"status":"ok","policy_set_version":"...","policy_count":2,"model_id":"gemini-3-flash-preview"}

curl -s -X POST https://demo.trusslabs.org/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Patient lives at 1234 Main St.","actor":{"user_id":"smoke@truss.local"}}' | jq
# expect: verdict=blocked + the configured block_message
```

Then open `examples/demo.html` in a browser, change the `endpoint`
field to `https://demo.trusslabs.org/v1/chat`, and walk through the
three sample prompts.

## 5. (Optional) gate it behind SSO

If you want to share the URL inside a CISO's org without leaving it open:

1. Cloudflare Zero Trust dashboard → **Access → Applications → Add an application → Self-hosted**
2. Subdomain: `demo`, domain: `trusslabs.org`
3. Add a policy — e.g. emails ending in the CISO's domain, or a one-time PIN

This works on top of the tunnel without touching the VM.

## Updating the code

Re-run section 2 (tarball + scp + provision.sh). `provision.sh` is
idempotent: it refreshes the code in `/opt/truss/truss-labs`, reinstalls
deps if needed, and restarts `truss-audit-proxy.service`. Receipts in
`/var/truss/receipts` are preserved.

## Tearing it down

```bash
gcloud compute instances delete "$INSTANCE" --project="$PROJECT" --zone="$ZONE"
# in CF Zero Trust dashboard: delete the tunnel + the public hostname
```

## Troubleshooting

| symptom | check |
|---|---|
| `provision.sh` fails on `pip install` | check internet egress on the VM (`curl https://pypi.org`) |
| `truss-audit-proxy` won't start | `sudo journalctl -u truss-audit-proxy -n 100` |
| `/healthz` returns 200 locally but `demo.trusslabs.org` 502s | `sudo systemctl status cloudflared`; tunnel may not be routing to `localhost:8000` |
| Receipts aren't appearing | `ls /var/truss/receipts/$(date -u +%Y-%m-%d)/` and check unit's `ReadWritePaths` |
| Demo page CORS error | the proxy enables permissive CORS by default; if you're behind Cloudflare Access, the SSO challenge can confuse `fetch()` from `file://` — load `demo.html` from a server instead |
