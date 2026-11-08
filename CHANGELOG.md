# CHANGELOG

<!-- version list -->

## v1.13.0 (2026-11-08)

### Bug Fixes

- **scrapers**: Validate the full page sequence in the Kebra Nagast index
  ([`d9192a6`](https://github.com/open-canon/open-canon-site/commit/d9192a61f75f12f679b6a2f5e9354c7e495b9bb8))

### Features

- **osis**: Add generated kebra-nagast.xml
  ([`d84ed76`](https://github.com/open-canon/open-canon-site/commit/d84ed76a70aa7c1b1f89cc008ab1ff64d744413b))

- **scrapers**: Add Kebra Nagast scraper (Budge translation)
  ([`13a0229`](https://github.com/open-canon/open-canon-site/commit/13a02299e48f5be1d58f0bec8d03fc996133526f))

### Testing

- **scrapers**: Expect the index validation error for a truncated Kebra Nagast index
  ([`98894d9`](https://github.com/open-canon/open-canon-site/commit/98894d99ad8edea5c1bf89ffec514f7bea09a2a5))


## v1.12.0 (2026-11-08)

### Bug Fixes

- **scrapers**: Drop FBE plate cross-references from verses
  ([`b10696a`](https://github.com/open-canon/open-canon-site/commit/b10696a557624ea24139ea6dd1bb885ca9e8ff2d))

- **scrapers**: Handle lettered verses and section headings in 1 Enoch
  ([`a4fdac7`](https://github.com/open-canon/open-canon-site/commit/a4fdac7374f8d131c0e166f3f321861eed58f462))

- **scrapers**: Keep FBE chapter summaries and image captions out of verses
  ([`d376543`](https://github.com/open-canon/open-canon-site/commit/d376543cf08d29825bd08a332e3a97446caec255))

- **scrapers**: Keep proclamation bylines and colophons in the chapter
  ([`887dde0`](https://github.com/open-canon/open-canon-site/commit/887dde02da6480d7b80c8d3e7ee8f07f2acadefd))

- **scrapers**: Parse every 1 Enoch verse and render superscripts
  ([`d24ef57`](https://github.com/open-canon/open-canon-site/commit/d24ef57e3cc17fcf2f297af8ab5ad8a503dbbb6e))

- **scrapers**: Treat the 1980 dateline as front matter, not a verse
  ([`ec21ee1`](https://github.com/open-canon/open-canon-site/commit/ec21ee146b22387a58df6c9f1ce5af97776e0c62))

### Documentation

- List the lds-proclamations scraper in the README
  ([`06b4818`](https://github.com/open-canon/open-canon-site/commit/06b4818d7cd0cc9dbb6ac390a8d21c6f85b8627f))

### Features

- **scrapers**: Scrape the 1980, 1995 and 2020 LDS proclamations
  ([`7c89fc0`](https://github.com/open-canon/open-canon-site/commit/7c89fc0dae3877fdd93a3c844969eaced1b1debc))


## v1.11.0 (2026-11-08)

### Bug Fixes

- **scrapers**: Do not treat "p." inside a word as a page marker
  ([`3b2917a`](https://github.com/open-canon/open-canon-site/commit/3b2917a52f54d15414dd07d50b9c9b320f43a93b))

- **scrapers**: Keep top-level italics/bold in Jubilees footnotes
  ([`9101454`](https://github.com/open-canon/open-canon-site/commit/91014541c6392e8e0d4a46e348ffc742e9334a18))

- **scrapers**: Treat a missing class as empty in LDS extract_markup
  ([`780e09d`](https://github.com/open-canon/open-canon-site/commit/780e09db14d8f066a1cf80a55030892b0c1d8984))

### Code Style

- **scrapers**: Ruff format churchofjesuschrist
  ([`06d6eb2`](https://github.com/open-canon/open-canon-site/commit/06d6eb2d14e59a411eb7b2c1dffe3e0a3914a9f5))

- **scrapers**: Ruff format sacred-texts
  ([`88849a5`](https://github.com/open-canon/open-canon-site/commit/88849a5956e902d12f02f90aace963afaf9ba9f7))

### Documentation

- **scrapers**: Document lds-standard-works functions and attributes
  ([`4e795d8`](https://github.com/open-canon/open-canon-site/commit/4e795d80e9ab3f380b773148c25a8c3a7bc3a4a1))

- **scrapers**: Document sacred-texts functions and attributes
  ([`6168930`](https://github.com/open-canon/open-canon-site/commit/61689304c15f6f581188ae03f7339833e725c43d))

### Features

- **scrapers**: Wire lds-standard-works into open-canon-scrape
  ([`f63db15`](https://github.com/open-canon/open-canon-site/commit/f63db15fbda49e0cc171646bbe66241beda5840f))

- **scrapers**: Wire sacred-texts scrapers into open-canon-scrape
  ([`150016b`](https://github.com/open-canon/open-canon-site/commit/150016bdfe0d0ab5350d0c33e3f9f560266bd352))

### Refactoring

- **scrapers**: Import churchofjesuschrist sources verbatim
  ([`8843246`](https://github.com/open-canon/open-canon-site/commit/88432466533fb0515a615a612979de0a2eb1e789))

- **scrapers**: Import sacred-texts sources verbatim
  ([`44321ba`](https://github.com/open-canon/open-canon-site/commit/44321ba8875e8d127fdbcf5bd4f8210da3b8429d))

### Testing

- **scrapers**: Unit-test lds-standard-works functions
  ([`d69b86f`](https://github.com/open-canon/open-canon-site/commit/d69b86f9175ec73fc5c3deae56373edc298add27))

- **scrapers**: Unit-test sacred-texts functions
  ([`6aaf5e6`](https://github.com/open-canon/open-canon-site/commit/6aaf5e67a078bdf435d0447782cdb532d03d59e8))


## v1.10.0 (2026-11-08)

### Code Style

- **scrapers**: Ruff format churchofjesuschrist
  ([`139f2cb`](https://github.com/open-canon/open-canon-site/commit/139f2cbebc368e8f81a716e45b3b01b0098f3fe3))

- **scrapers**: Ruff format sacred-texts
  ([`83b5189`](https://github.com/open-canon/open-canon-site/commit/83b51893d1710f3f85bbca5124ea3204c04ee0a6))

### Documentation

- **scrapers**: Document lds-standard-works functions and attributes
  ([`d8a1135`](https://github.com/open-canon/open-canon-site/commit/d8a11356eefc853bd650d32898166e65ffc8d4c4))

- **scrapers**: Document sacred-texts functions and attributes
  ([`8ed1784`](https://github.com/open-canon/open-canon-site/commit/8ed17842ce9fb2043ff424931af4665e1986a4a0))

### Features

- **scrapers**: Wire lds-standard-works into open-canon-scrape
  ([`9a54f60`](https://github.com/open-canon/open-canon-site/commit/9a54f604b8144606df4ade5558873439346ccaff))

- **scrapers**: Wire sacred-texts scrapers into open-canon-scrape
  ([`85a8945`](https://github.com/open-canon/open-canon-site/commit/85a8945fc21106b27a0e87fb7021dd33cc226a1f))

### Refactoring

- **scrapers**: Import churchofjesuschrist sources verbatim
  ([`42859db`](https://github.com/open-canon/open-canon-site/commit/42859dbdabb1006c8f2cef83063d80810cfa755c))

- **scrapers**: Import sacred-texts sources verbatim
  ([`fad41e4`](https://github.com/open-canon/open-canon-site/commit/fad41e461928d97bc992912b8d9b40d6d3cf567d))

### Testing

- **scrapers**: Unit-test lds-standard-works functions
  ([`7f2a561`](https://github.com/open-canon/open-canon-site/commit/7f2a5613338d815e3ff0ed13f985d09a403348d0))

- **scrapers**: Unit-test sacred-texts functions
  ([`168d4f2`](https://github.com/open-canon/open-canon-site/commit/168d4f2397ef580252e762ea28e3e7d7702badb9))


## v1.9.0 (2026-11-08)

### Bug Fixes

- **scrapers**: Harden cache paths and page-marker parsing
  ([`65f44ec`](https://github.com/open-canon/open-canon-site/commit/65f44ecc01fcd6269e1a12fd643b453b73be4355))

- **scrapers**: Honor --cache-dir and write UTF-8 in kjv-apocrypha
  ([`7667829`](https://github.com/open-canon/open-canon-site/commit/766782970bd66ec0a6d1aaac088b34b8420b3344))

### Code Style

- **scrapers**: Ruff format kjv-apocrypha
  ([`f8a5531`](https://github.com/open-canon/open-canon-site/commit/f8a553168cf567e9020fb3ec2db3fa68a752f29f))

### Documentation

- **scrapers**: Document framework functions and attributes
  ([`d029b1f`](https://github.com/open-canon/open-canon-site/commit/d029b1f56e6f05788b8ee7f5e5adaac9c7792e51))

- **scrapers**: Document kjv-apocrypha functions and attributes
  ([`2b81f1f`](https://github.com/open-canon/open-canon-site/commit/2b81f1fde9da510627aa7ed4b758dc39f66b1fdd))

### Features

- **scrapers**: Add open-canon-scrape CLI framework
  ([`abc1e05`](https://github.com/open-canon/open-canon-site/commit/abc1e05bd1c049cb196cbd3327409ffbd9be0694))

- **scrapers**: Wire kjv-apocrypha into open-canon-scrape
  ([`e945795`](https://github.com/open-canon/open-canon-site/commit/e945795a4930aa43ab95f1c121c9b1406d635d93))

### Refactoring

- **scrapers**: Import kjv-apocrypha sources verbatim
  ([`1108249`](https://github.com/open-canon/open-canon-site/commit/110824916cb67bc8f8949787a0bc232707c51623))

### Testing

- **scrapers**: Unit-test framework functions
  ([`8e98270`](https://github.com/open-canon/open-canon-site/commit/8e9827032b9bce17f6e755474c3eabaab1517bc3))

- **scrapers**: Unit-test kjv-apocrypha functions
  ([`2d91b81`](https://github.com/open-canon/open-canon-site/commit/2d91b819ab46b44c93a653eb1c2e74cb2e9e1044))


## v1.8.0 (2026-04-06)

### Features

- Publish CHANGELOG as changelog.html and add footer link
  ([`4795ff3`](https://github.com/open-canon/open-canon-site/commit/4795ff3ca8be41dd9c3a5205af06213806e67896))


## v1.7.0 (2026-04-06)

### Features

- Add Vita Adae et Evae
  ([`b00d8d7`](https://github.com/open-canon/open-canon-site/commit/b00d8d7db28c2c92b7592d50fa09c194fea942b4))


## v1.6.0 (2026-04-06)

### Bug Fixes

- Correcty parse chapters and verses when a book's OsisID has multiple components.
  ([`eb4b399`](https://github.com/open-canon/open-canon-site/commit/eb4b399665698ac931ab25273fc5a8dca3de6de6))

### Chores

- 1 Enoch fix
  ([`1660a7b`](https://github.com/open-canon/open-canon-site/commit/1660a7b2e1df80572e0767c7d1922af64bb15e30))

- Update texts
  ([`dcbac79`](https://github.com/open-canon/open-canon-site/commit/dcbac790ea6516b90114b273455bb1df6e375273))

- Use consolidated Adam and Eve
  ([`6ae670d`](https://github.com/open-canon/open-canon-site/commit/6ae670de56597d1037d98b7d3443fbeac7608cba))

### Features

- Add Forgotten Books of Eden
  ([`5b4642c`](https://github.com/open-canon/open-canon-site/commit/5b4642cc869c5daa6c1474ef2e2b6f522d1f7d5b))


## v1.5.1 (2026-04-05)


## v1.5.0 (2026-04-05)

### Chores

- Add KJV apocryphra to collection
  ([`dd8eb17`](https://github.com/open-canon/open-canon-site/commit/dd8eb172a8d8de942ed19bc56958d40f754aea0d))

- Always build PR preview
  ([`e03970a`](https://github.com/open-canon/open-canon-site/commit/e03970a932d4553cbbeb612653503376947cd557))

### Features

- Works inside a collection remain ordered
  ([`65dad8d`](https://github.com/open-canon/open-canon-site/commit/65dad8de21c18d97f992c16097887b6964ff1ac7))

- **library**: Add sidebar collections, fix Apocrypha name, allow multi-collection docs
  ([`544bf2d`](https://github.com/open-canon/open-canon-site/commit/544bf2dc6ab71fbd789d66767ca9a9239fa837d7))

- **library**: Group documents into collapsible collections with JSON config
  ([`39a2fa5`](https://github.com/open-canon/open-canon-site/commit/39a2fa518c89c0a562dd3970943f4c8340fa3107))


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
