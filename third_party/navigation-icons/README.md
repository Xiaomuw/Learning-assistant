# Navigation icon provenance

The eight PNG variants in each client's icon directory are generated from four
unmodified Lucide 0.475.0 SVG files at upstream commit
`e28426a871f575b694e8403c6444afccaa404e54`. Their upstream paths are `icons/` plus
the SVG filenames in this directory. The manifest records source/output hashes.

| Application role | Upstream SVG |
| --- | --- |
| Chat | message-circle.svg |
| Practice | notebook-pen.svg |
| Learning dashboard | chart-column.svg |
| Profile | user-round.svg |

`LUCIDE-LICENSE` is the unmodified upstream ISC license, including its Feather
copyright attribution. `FEATHER-LICENSE` preserves the upstream MIT license from
https://github.com/feathericons/feather/blob/v4.29.2/LICENSE. Both texts are copied
into each client's NOTICE.txt. The Apache-2.0 project license does not relicense
these assets. Changes are limited to color substitution and 81x81 rasterization.

Regenerate from the repository root in an optional development environment:

```bash
python -m venv /tmp/la-icon-renderer
/tmp/la-icon-renderer/bin/pip install CairoSVG==2.8.2
/tmp/la-icon-renderer/bin/python scripts/render_navigation_icons.py
python -m unittest discover -s scripts/tests -p 'test_navigation_assets.py' -v
```

The SVGs are the editable sources. Cairo/native rendering-library differences may
change PNG byte hashes; review regenerated images and manifest together. No new
runtime dependency is required to build either client from the committed assets.

The Web public directory includes NOTICE.txt. Taro explicitly copies it into its
built assets; check the final WeChat upload package separately during device
acceptance. Existing filenames, navigation routes and selected/unselected colors
are retained, but the icon artwork changes visibly.

These files replace 16 current PNG files whose source evidence was unavailable.
No old PNG is re-licensed by this replacement, and historical Git objects are not
removed. Historical assets, other screenshots and third-party content still need
their own review.
