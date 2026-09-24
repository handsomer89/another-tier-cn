# Another Tier — English mirror

This repository contains a static snapshot of [anothertier.com](https://anothertier.com/), captured on 2026-09-24. The source dataset, rankings, layouts, public routes, scripts, styles, fonts, and image references are preserved. A Chinese display-name layer localizes character names while retaining their English source names.

- 326 rendered page routes, including character pages, `/free`, `/no-sa`, and the beta `/teams?beta=true` page.
- The original scripts, stylesheets, fonts, and site assets are included.
- The original public API and Cloudinary image CDN remain connected for client-side data and images, matching the source site's behavior.

GitHub Pages serves this repository at `/another-tier-cn/`; the mirrored styles, assets, and client router use that base path. To preview locally, run `python -m http.server 8000` from the repository's parent directory and open `http://localhost:8000/another-tier-cn/`.

## Chinese character names

Character names in the visible page UI use the corrected mappings in `data/cn-names.json`. English names remain in site data, URLs, and API-facing values. Character cards and pages display Chinese names, and character search accepts both English and Chinese names.

After updating the source snapshot or corrected name workbook, refresh the mapping and localized page output with:

```sh
python3 scripts/import-cn-names.py /path/to/Another_Tier_Character_Forms_CN_corrected.xlsx
python3 scripts/localize-cn.py
python3 scripts/check-cn.py
```

The importer reads the exact English/form and corrected Chinese columns; blank translation rows are skipped. The localizer patches the display and search bundles and updates only visible HTML names, image alt text, and character-page metadata. Embedded source data and route slugs are left intact.
