# The Nookku logo

Nookku comes from the Tamil word நோக்கு, "to observe". In the logo, the two o's of "nookku" are two eyes. They look right, toward the agent, which is the direction of a message in the [data flow](../../architecture.md#data-flow).

| File | Use |
|---|---|
| `nookku-wordmark.svg`, `nookku-wordmark-dark.svg` | The wordmark. The README header uses it. |
| `nookku-mark.svg`, `nookku-mark-dark.svg` | The two eyes only, for small places. |
| `nookku-icon.svg`, `nookku-icon-512.png` | The two eyes on a rounded square, for an avatar or a plugin icon. |
| `nookku-social.png` | The GitHub social preview, 1280 × 640. |

Use the `-dark` files on a dark background.

| Colour | Value | Use |
|---|---|---|
| Ink | `#12203a` | Letters on a light background, and the icon background |
| Paper | `#f3f6fa` | Letters on a dark background |
| Marigold | `#d9822b` | The pupils |

The letters are monoline paths, so each SVG shows the same in each viewer, with no font.

To draw the SVG files again, run `python docs/assets/logo/make.py`. I rendered the two PNG files from the SVG files with headless Chrome. The text in `nookku-social.png` is the tagline, the first sentence of the description in the [README](../../../README.md). It uses the system font.
