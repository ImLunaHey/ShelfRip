# shelfrip.com

The one-page website at https://shelfrip.com. Plain HTML, no build step.

Hosted on GitHub Pages: `.github/workflows/site.yml` publishes this folder whenever it changes on
`main` (Settings › Pages › Source: GitHub Actions). `CNAME` holds the custom domain. The domain's DNS
is at Squarespace: four A records for `@` (185.199.108.153, 185.199.109.153, 185.199.110.153,
185.199.111.153) and a CNAME for `www` to `shelfrip.github.io`. The MX records for email are untouched.

Update `softwareVersion` in the JSON-LD block of `index.html` and `lastmod` in `sitemap.xml` with
each release. The screenshots in `img/` are `docs/*.png` scaled to 1600 px wide as WebP.
