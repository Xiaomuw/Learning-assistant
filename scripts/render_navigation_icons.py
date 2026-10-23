"""Render reviewed Lucide SVG sources into both clients' navigation PNG assets.

Development-only prerequisite: CairoSVG==2.8.2 (no application dependency).
"""

import hashlib
import json
from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "third_party/navigation-icons"
DESTINATIONS = [ROOT / "frontend/public/weapp-icons", ROOT / "frontend-weapp/src/assets/icons"]
ICONS = {"chat": "message-circle", "practice": "notebook-pen",
         "dashboard": "chart-column", "profile": "user-round"}
COLORS = {"": "#6B7280", "-active": "#1F2937"}
UPSTREAM = "e28426a871f575b694e8403c6444afccaa404e54"


def main() -> None:
    notice = (
        "Learning Assistant navigation icon notices\n\n"
        f"Source: https://github.com/lucide-icons/lucide/tree/{UPSTREAM}/icons\n"
        "Lucide 0.475.0. Original SVG paths retained. PNG variants modified by\n"
        "Learning Assistant maintainers on 2026-10-23: color replacement and\n"
        "rasterization to 81x81 transparent PNG. These assets retain upstream\n"
        "licenses; the project Apache-2.0 license does not replace them.\n\n"
        + (SOURCE / "LUCIDE-LICENSE").read_text() + "\n"
        + (SOURCE / "FEATHER-LICENSE").read_text()
    )
    manifest = {"upstream_commit": UPSTREAM, "lucide_version": "0.475.0",
                "renderer": "CairoSVG " + cairosvg.__version__, "size": [81, 81],
                "licenses": ["ISC", "MIT (Feather portions)"], "icons": []}
    for name, source_name in ICONS.items():
        source = (SOURCE / (source_name + ".svg")).read_bytes()
        for suffix, color in COLORS.items():
            png = cairosvg.svg2png(bytestring=source.replace(b"currentColor", color.encode()),
                                  output_width=81, output_height=81)
            filename = name + suffix + ".png"
            for destination in DESTINATIONS:
                destination.mkdir(parents=True, exist_ok=True)
                (destination / filename).write_bytes(png)
            manifest["icons"].append({"file": filename, "source": source_name + ".svg",
                                      "source_sha256": hashlib.sha256(source).hexdigest(),
                                      "png_sha256": hashlib.sha256(png).hexdigest(), "color": color})
    for destination in DESTINATIONS:
        (destination / "NOTICE.txt").write_text(notice)
    (SOURCE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
