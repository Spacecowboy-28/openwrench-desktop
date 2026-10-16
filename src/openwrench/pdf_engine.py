"""PDFium operations run only in an isolated worker process in the desktop UI."""
from contextlib import closing
import json
from pathlib import Path
import pypdfium2 as pdfium
import pypdfium2.raw as raw

from openwrench.library import MAX_PAGES, MAX_TEXT


def extract(content, progress=lambda *a: None, cancelled=lambda: False):
    try:
        with pdfium.PdfDocument(content) as document:
            # Even empty-password encrypted documents require explicit unlocked copies.
            if raw.FPDF_GetSecurityHandlerRevision(document) >= 0:
                raise ValueError('Encrypted PDFs are unsupported. Import an unlocked lawful copy.')
            if not 0 < len(document) <= MAX_PAGES:
                raise ValueError('PDF must contain 1 to 5000 pages.')
            pages, size = [], 0
            for index in range(len(document)):
                if cancelled():
                    raise InterruptedError('PDF processing cancelled.')
                with closing(document[index]) as page, closing(page.get_textpage()) as textpage:
                    if textpage.count_chars() > 1_000_000:
                        raise ValueError('PDF page exceeds the extraction limit.')
                    value = textpage.get_text_bounded()
                    size += len(value.encode('utf-8'))
                    if size > MAX_TEXT:
                        raise ValueError('PDF exceeds the 20 MiB extracted-text limit.')
                    pages.append(value)
                progress(index + 1, len(document))
            return pages
    except pdfium.PdfiumError as error:
        raise ValueError('Unable to read PDF. It is malformed or password protected.') from error


def render(path, page_number, scale, output):
    with pdfium.PdfDocument(path) as document:
        if not 1 <= page_number <= len(document):
            raise ValueError('Page outside this document.')
        with closing(document[page_number-1]) as page:
            width, height = page.get_size()
            scale = min(max(float(scale), 0.25), 4.0, (16_000_000 / max(width * height, 1)) ** .5)
            with closing(page.render(scale=scale, force_bitmap_format=raw.FPDFBitmap_BGRA)) as bitmap:
                Path(output).write_bytes(bytes(bitmap.buffer))
                return dict(width=bitmap.width, height=bitmap.height, stride=bitmap.stride, pages=len(document))
