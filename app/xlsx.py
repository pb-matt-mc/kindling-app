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
    """cols: header names. rows: list of value lists (column 2 is the link). photos: first photo path per row.

    Photos float over their row, pinned to the cell. Excel, Numbers and Files show them. Google Sheets
    drops them on import, and its import turns Excel's "Place in cell" pictures into #VALUE!, so don't use those.
    """
    try:
        import xlsxwriter
        import PIL  # noqa: F401  needed to read the photos
    except ImportError as e:
        raise XlsxUnavailable("Excel export needs the xlsxwriter and Pillow packages on the server "
                              "(pip install -r requirements.txt).") from e

    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    title = "".join(ch for ch in sheet_title if ch not in '[]:*?/\\')[:31] or "Kindling"
    ws = wb.add_worksheet(title)
    head = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#2A1F19", "valign": "vcenter", "text_wrap": True})
    body = wb.add_format({"valign": "vcenter", "text_wrap": True})
    link = wb.add_format({"valign": "vcenter", "font_color": "#1A73E8", "underline": 1})

    header = ["Photo"] + list(cols)
    ws.set_row(0, 30)
    for i, name in enumerate(header):
        ws.write_string(0, i, name, head)
    ws.freeze_panes(1, 1)
    widths = {"Photo": 17, "Name": 38, "Link": 16, "Price": 10, "Top 5 qualities": 42, "Listing area": 22}
    for i, name in enumerate(header):
        ws.set_column(i, i, widths.get(name, 14))

    for r_i, (row, photo) in enumerate(zip(rows, photos), start=1):
        ws.set_row(r_i, ROW_PT)
        for c_i, v in enumerate(row, start=1):
            if c_i == 2 and v:  # the Link column
                ws.write_url(r_i, c_i, str(v), link, "Open listing")
            elif isinstance(v, str):
                ws.write_string(r_i, c_i, v, body)  # listing titles come from sellers; never let one become a formula
            elif v is None or v == "":
                ws.write_blank(r_i, c_i, None, body)
            else:
                ws.write_number(r_i, c_i, v, body)
        data = _thumb(photo)
        if data:
            ws.insert_image(r_i, 0, "photo.jpg", {"image_data": io.BytesIO(data), "object_position": 1, "x_offset": 3, "y_offset": 3})
    wb.close()
    return buf.getvalue()


def formula_safe(v):
    """For CSV/TSV: a cell a spreadsheet would read as a formula gets a leading quote."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v
