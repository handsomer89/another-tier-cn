# Another Tier — Chinese localized mirror

This repository contains a static snapshot of [anothertier.com](https://anothertier.com/), captured on 2026-09-24. The source dataset, rankings, layouts, public routes, scripts, styles, fonts, and image references are preserved. Chinese display names and workbook-backed UI/classification translations are applied while retaining English source values in routes and API-facing data.

- 326 rendered page routes, including character pages, `/free`, `/no-sa`, and the beta `/teams?beta=true` page.
- The original scripts, stylesheets, fonts, and site assets are included.
- The original public API and Cloudinary image CDN remain connected for client-side data and images, matching the source site's behavior.

GitHub Pages serves this repository at `/another-tier-cn/`; the mirrored styles, assets, and client router use that base path. To preview locally, run `python -m http.server 8000` from the repository's parent directory and open `http://localhost:8000/another-tier-cn/`.

## Chinese localization

Character names use the corrected mappings in `data/cn-names.json`. The 48 fixed UI strings and 152 translated terms in `data/cn-ui.json` and `data/cn-terms.json` cover page copy, tier filters, and character details, including personalities shared between filters and detail pages. English source values remain in site data, URLs, and API-facing fields. Character search accepts both English and Chinese names.

After updating the source snapshot or translation workbooks, refresh the mappings and localized page output with:

```sh
python3 scripts/import-cn-names.py /path/to/Another_Tier_Character_Forms_CN_corrected.xlsx
python3 scripts/import-cn-terms.py /path/to/Another_Tier_待精译术语_筛选与分类已翻译.xlsx
python3 scripts/localize-cn.py
python3 scripts/check-cn.py
```

The importers read the workbook's exact source/translation columns and skip blank translations. The localizer updates visible HTML copy and matching browser bundles, with category-aware term translations so labels such as personalities agree on the filter and character detail pages. Embedded source data and route slugs are left intact. The tome-name worksheet has no completed Chinese values, so tome names retain their current display until translations are supplied.

