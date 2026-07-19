from pathlib import Path

from PIL import Image
from PyQt6 import QtCore, QtGui, QtSvg


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_DIR = ROOT / "assets" / "resources"
SOURCE = RESOURCE_DIR / "app.svg"
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256)
FLATCAM_SIZES = (16, 24, 32, 48, 128, 256)


def render_svg(size):
    renderer = QtSvg.QSvgRenderer(str(SOURCE))
    if not renderer.isValid():
        raise RuntimeError("Invalid SVG source: %s" % SOURCE)

    image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def save_pngs():
    targets = (RESOURCE_DIR, RESOURCE_DIR / "dark_resources")
    for size in PNG_SIZES:
        image = render_svg(size)
        for target in targets:
            output = target / ("app%d.png" % size)
            if not image.save(str(output), "PNG"):
                raise RuntimeError("Could not save %s" % output)

    for size in FLATCAM_SIZES:
        image = render_svg(size)
        for target in targets:
            output = target / ("flatcam_icon%d.png" % size)
            if not image.save(str(output), "PNG"):
                raise RuntimeError("Could not save %s" % output)

    linux_icon = render_svg(256)
    if not linux_icon.save(str(ROOT / "assets" / "linux" / "icon.png"), "PNG"):
        raise RuntimeError("Could not save Linux icon")


def save_icos():
    ico_sizes = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))
    source = Image.open(RESOURCE_DIR / "app256.png").convert("RGBA")
    targets = (RESOURCE_DIR, RESOURCE_DIR / "dark_resources")
    for target in targets:
        source.save(target / "flatcam_icon256.ico", format="ICO", sizes=ico_sizes)
        for size in (16, 32, 48):
            source.save(
                target / ("flatcam_icon%d.ico" % size),
                format="ICO",
                sizes=tuple(item for item in ico_sizes if item[0] <= size)
            )


if __name__ == "__main__":
    save_pngs()
    save_icos()
