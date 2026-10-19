"""Render the canonical SVG into native icons without changing its design.

Run with the Ethoscore environment: python tools/build_branding.py.
Pillow is a build-only dependency; Qt SVG is already an application dependency.
The SVG logo uses outlined glyphs so it remains portable without installed fonts.
"""

from pathlib import Path
import sys

from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/branding"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
RENDER_SIZE = 1024
WORDMARK_FONT = "Segoe UI"


def outlined_text(text: str, x: float, y: float, size: int, color: str) -> str:
    """Convert the wordmark into SVG paths for font-independent rendering."""
    font = QFont(WORDMARK_FONT)
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.DemiBold)
    path = QPainterPath()
    path.addText(x, y, font, text)
    commands = []
    index = 0
    while index < path.elementCount():
        element = path.elementAt(index)
        if element.isMoveTo():
            commands.append(f"M{element.x:.3f} {element.y:.3f}")
        elif element.isLineTo():
            commands.append(f"L{element.x:.3f} {element.y:.3f}")
        else:
            control = path.elementAt(index + 1)
            end = path.elementAt(index + 2)
            commands.append(f"C{element.x:.3f} {element.y:.3f} {control.x:.3f} {control.y:.3f} {end.x:.3f} {end.y:.3f}")
            index += 2
        index += 1
    return f'<path fill="{color}" d="{" ".join(commands)}"/>'


def render_svg(source: Path, destination: Path, width: int, height: int) -> None:
    """Rasterize with transparent corners using the same SVG engine as the app."""
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError(f"Invalid SVG: {source}")
    bitmap = QImage(width, height, QImage.Format.Format_ARGB32)
    bitmap.fill(0)
    painter = QPainter(bitmap)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    if not bitmap.save(str(destination)):
        raise OSError(f"Cannot save {destination}")


def main() -> None:
    """Create Windows ICO, macOS ICNS, PNG and portable outlined SVG logos."""
    app = QApplication.instance() or QApplication(sys.argv)
    # Offscreen Windows Qt may not discover fonts, so register the source font.
    font_file = Path("C:/Windows/Fonts/seguisb.ttf")
    if font_file.exists():
        QFontDatabase.addApplicationFont(str(font_file))
    icon = ASSETS / "ethoscore-icon.svg"
    render_svg(icon, ASSETS / "ethoscore-icon.png", RENDER_SIZE, RENDER_SIZE)
    with Image.open(ASSETS / "ethoscore-icon.png") as bitmap:
        bitmap.save(ASSETS / "ethoscore-icon.ico", sizes=[(n, n) for n in ICON_SIZES])
        bitmap.save(ASSETS / "ethoscore-icon.icns")
    # Reuse the actual icon geometry; never redraw a slightly different logo mark.
    source = icon.read_text(encoding="utf-8")
    geometry = source[source.index('  <rect'):source.rindex('</svg>')]
    for suffix, color in (("", "#142D3B"), ("-light", "#EFFAF7")):
        logo = ('<svg xmlns="http://www.w3.org/2000/svg" width="1030" height="256" '
                'viewBox="0 0 1030 256" role="img" aria-label="Ethoscore">\n'
                '<title>Ethoscore</title>\n<g transform="scale(.5)">\n' + geometry + '</g>\n' +
                outlined_text("ethoscore", 290, 169, 136, color) + '\n</svg>\n')
        target = ASSETS / f"ethoscore-logo{suffix}.svg"
        target.write_text(logo, encoding="utf-8")
        render_svg(target, ASSETS / f"ethoscore-logo{suffix}.png", 1030, 256)
    print(f"Brand assets generated in {ASSETS}")


if __name__ == "__main__":
    main()
