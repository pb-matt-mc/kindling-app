"""Excel export with each listing's first photo embedded in its row.

The photos go inside the file itself, so they keep working anywhere and nothing on the server has to be public.
"""
import io

from . import config
from .log import log

THUMB_PX = 110  # longest side of the embedded photo
ROW_PT = 86     # row height in points, fits the photo with a little air


class XlsxUnavailable(Exception):
    pass


def _thumb(photo_path):
    """Local /img/... path -> small JPEG bytes, or None if the file is gone or unreadable."""
    from PIL import Image as PILImage
    if not photo_path or not photo_path.startswith("/img/") or photo_path.endswith(".svg"):  # svg: demo listings only
        return None
    f = config.IMG_DIR / photo_path.rsplit("/", 1)[-1]
    if not f.is_file():
        return None
    try:
        with PILImage.open(f) as im:
            im = im.convert("RGB")
            im.thumbnail((THUMB_PX, THUMB_PX))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=82)
            return out.getvalue()
    except Exception as e:  # a bad image shouldn't sink the whole export
        log.warning("export: couldn't read photo %s: %s", f.name, e)
        return None


def build(cols, rows, photos, sheet_title="Kindling"):
    """cols: header names. rows: list of value lists (column 2 is the link). photos: first photo path per row."""
    try:
        from openpyxl import Workbook
        from openpyxl.drawing.image import Image as XLImage
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        import PIL  # noqa: F401  openpyxl needs Pillow for images
    except ImportError as e:
        raise XlsxUnavailable("Excel export needs the openpyxl and Pillow packages on the server "
                              "(pip install -r requirements.txt).") from e

    wb = Workbook()
    ws = wb.active
    ws.title = "".join(ch for ch in sheet_title if ch not in '[]:*?/\\')[:31] or "Kindling"
    header = ["Photo"] + list(cols)
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2A1F19")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "B2"

    widths = {"Photo": 17, "Name": 38, "Link": 16, "Price": 10, "Top 5 qualities": 42}
    for i, name in enumerate(header, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(name, 14)

    top = Alignment(vertical="center", wrap_text=True)
    for r_i, (row, photo) in enumerate(zip(rows, photos), start=2):
        ws.append([""] + list(row))
        ws.row_dimensions[r_i].height = ROW_PT
        for c in ws[r_i]:
            c.alignment = top
        link_cell = ws.cell(row=r_i, column=3)
        if link_cell.value:
            link_cell.hyperlink = link_cell.value
            link_cell.value = "Open listing"
            link_cell.font = Font(color="1A73E8", underline="single")
        data = _thumb(photo)
        if data:
            img = XLImage(io.BytesIO(data))
            ws.add_image(img, f"A{r_i}")

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
