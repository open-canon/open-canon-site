# CHANGELOG

<!-- version list -->

## v1.4.0 (2026-04-01)

### Bug Fixes

- Remove head.repo.fork check from preview/remove-preview job conditions
  ([`d53e57e`](https://github.com/open-canon/open-canon-site/commit/d53e57e581e278336ebd9ed4ef0cfb703b321a43))

- Use head.repo.fork check instead of full_name for robust re-run handling
  ([`7b05fdc`](https://github.com/open-canon/open-canon-site/commit/7b05fdc9cd638116c9bd580d92cab3971ceb9e2a))

- **ci**: Keep PR preview deployments rerun-safe
  ([`a1c5680`](https://github.com/open-canon/open-canon-site/commit/a1c5680c5229bb98f9cfa7b2eae92c53fd3290f4))

### Features

- Post PR comment with GitHub Pages preview link on each PR
  ([`641c4aa`](https://github.com/open-canon/open-canon-site/commit/641c4aa8783735f7726400b7c3e0e1f61b0d249e))


## v1.3.0 (2026-04-01)

### Features

- **css**: Use Palatino as primary serif font with fallbacks
  ([`03a5244`](https://github.com/open-canon/open-canon-site/commit/03a5244933aa86eb15cd4ba9833de40dd46578a4))


## v1.2.0 (2026-03-30)

### Continuous Integration

- Add fork guard and per-PR concurrency to preview jobs
  ([`6823d45`](https://github.com/open-canon/open-canon-site/commit/6823d459e88ab81c7b21b2da88a6d8e09747eaa5))

- Add PR preview deployment using rossjrw/pr-preview-action
  ([`04ec180`](https://github.com/open-canon/open-canon-site/commit/04ec18071184eb129fbc7ab37a2abe9d1dad57b1))

- Add weekly scheduled workflow to clean up stale PR previews
  ([`3b1cc69`](https://github.com/open-canon/open-canon-site/commit/3b1cc695f56de08d6bd817c7ffe58aeec6182c40))

### Features

- Standard Works
  ([`937967f`](https://github.com/open-canon/open-canon-site/commit/937967f2b7047d58e059abf8de189713c6201f47))


## v1.1.0 (2026-03-29)

### Bug Fixes

- Configure GitHub Pages to use GitHub Actions source to prevent Jekyll overwriting built site
  ([`d7c178d`](https://github.com/open-canon/open-canon-site/commit/d7c178d78fcbc02fd726a0ff7caddc483366f657))

- Move configure-pages to release job to prevent Jekyll overwriting site before source switch
  ([`792e1f5`](https://github.com/open-canon/open-canon-site/commit/792e1f50d7c8e45f856202a86a4bd32dbc2f9aa3))

### Features

- Add KJV Apocrypha
  ([`16b703d`](https://github.com/open-canon/open-canon-site/commit/16b703df50ae7ca62c9f7c11a56dbcccee4a0336))


## v1.0.0 (2026-03-29)

- Initial Release
