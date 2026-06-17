# Deploy

How to ship a change to **trusslabs.org**.

## Setup

Deploys go to a Cloudflare Pages project named `truss-labs` via **direct upload** (no Git integration). The only thing you need locally is wrangler, which is already a transitive dep via `npx`.

One-time: make sure wrangler has a valid session.

```
npx wrangler whoami
```

Should print `Ilteris@trusslabs.org's Account` (id `cc69571ee644368f643c793858087255`). If not, run `npx wrangler login` and follow the browser prompt.

## Deploy

From this directory (`~/Code/truss-labs/www/`):

```
npm run build
npx wrangler pages deploy dist --project-name truss-labs
```

That's it. Wrangler prints the preview URL (something like `https://<hash>.truss-labs.pages.dev`) and then the production alias if you're deploying to the production branch.

Production domain: <https://trusslabs.org>

## Canonical domains

Use these as the visible public URLs:

- <https://trusslabs.org/> — main site
- <https://trusslabs.org/docs/> — docs
- <https://trusslabs.org/sandbox> — interactive policy sandbox

Alias hostnames should redirect to canonical URLs:

- `www.trusslabs.org/*` → `trusslabs.org/*`
- `docs.trusslabs.org/*` → `trusslabs.org/docs/*`

DNS only maps hostnames to services. It cannot map `docs.trusslabs.org` directly
to `/docs/`; use Cloudflare Redirect Rules for that path mapping.

## Verify

Three quick checks after a deploy:

1. **Content**: `curl -s https://trusslabs.org | grep -o "<title>[^<]*"` — should show the current title.
2. **Status**: `curl -sI https://trusslabs.org | head -1` — expect `HTTP/2 200`.
3. **Cache**: Cloudflare Pages responses include a `cf-ray` and `cf-cache-status` header. `DYNAMIC` or `MISS` is normal on first request.

If the site looks stale, it's almost always browser cache — hard reload or `curl -s "https://trusslabs.org/?t=$(date +%s)"` to bypass.

## Rollback

Every deploy gets a unique preview URL and stays retrievable in the Cloudflare dashboard under **Pages → truss-labs → Deployments**. To roll back:

1. Go to the dashboard
2. Find the previous good deployment
3. Click "Rollback to this deployment"

There is no CLI rollback.

## Gotchas

- **Email links get rewritten.** Cloudflare's email-obfuscation feature replaces `mailto:` with `/cdn-cgi/l/email-protection#...`. This is on by default and fine — it decodes client-side via an injected script. If you need raw `mailto:` (e.g. RSS feed), disable **Email Address Obfuscation** under Cloudflare Scrape Shield settings for the zone.
- **DNS is delegated to Cloudflare.** Nameservers are `jule.ns.cloudflare.com` and `watson.ns.cloudflare.com`. Don't change DNS at the registrar; change it in the Cloudflare DNS dashboard. (The zone was moved between Cloudflare accounts on 2026-05-10; the Pages project lives in the same `Ilteris@trusslabs.org` account as the zone.)
- **`.pages.dev` project domain** is `truss-labs.pages.dev`. (An earlier duplicate project in the `Ilteris@gmail.com` account used `truss-labs-2on.pages.dev`; that project is now superseded and can be deleted.)
- **Wrangler caches the account ID per-project** in `node_modules/.cache/wrangler/wrangler-account.json`. If a deploy fails with `Authentication error [code: 10000]` pointing at the wrong account, `rm -rf node_modules/.cache/wrangler` and retry.
- **The `dist/` directory is the entire site.** Anything not in `dist/` after `npm run build` will not be on the live site. If you drop a file in `public/`, Astro copies it to `dist/` on build.

## Why not Git-connected?

Cloudflare Pages also supports GitHub integration (push to `main` → auto-build → auto-deploy). This isn't wired up because:

- The repo at `~/Code/truss-labs/` currently has no remote.
- For a solo founder and a small static site, direct upload is simpler — no CI secrets, no build minutes, no webhook debugging.

Task `401` in the Sovereign Registry tracks switching to Git integration if/when it becomes worth the setup cost.
