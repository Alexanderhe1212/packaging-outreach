# Third-party notices

Project-owned code retains the root MIT license. Vendored components retain their own licenses and copyright; the root license does not relicense them.

- `userradar/third_party/theHarvester`: GPL-2.0 license text and pinned license retained. Only the vendored/local adapter subset is included; consult its source headers and README. It is not a permission to access restricted services.
- `userradar/third_party/extruct`: upstream LICENSE retained.
- `userradar/third_party/website_email_contact_scraper`: upstream MIT LICENSE retained.
- Windows builds bundle CPython under its included license and Python dependency wheels with their `.dist-info` license metadata. Runtime binary artifacts are build outputs, not credentials or customer data.

Source for the redistributed subset is included in this repository. No external provider API keys or private datasets are included. Build dependency hashes are recorded per build; never treat a root project license as covering every dependency.
