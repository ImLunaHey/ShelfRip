# shelfrip.com

The one-page website at https://shelfrip.com. Plain HTML, no build step.

Hosted on Cloudflare Pages, connected to this repo: production branch `main`, build command empty,
build output directory `site`. Every push to `main` that changes `site/` redeploys it.

Update `softwareVersion` in the JSON-LD block of `index.html` and `lastmod` in `sitemap.xml` with
each release. The screenshots in `img/` are `docs/*.png` scaled to 1600 px wide as WebP.
