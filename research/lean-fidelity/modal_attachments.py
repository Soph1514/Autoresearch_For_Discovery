"""CPU-only extraction for user-supplied problem attachments."""
import modal

app = modal.App('lean-attachments')
image = (modal.Image.debian_slim(python_version='3.11')
         .apt_install('tesseract-ocr', 'poppler-utils')
         .pip_install('pypdf==6.1.1', 'Pillow==11.3.0'))

@app.function(image=image, cpu=2, memory=4096, timeout=180, max_containers=2)
def extract(data: bytes, extension: str) -> dict:
    import io
    import subprocess
    import tempfile
    from pathlib import Path
    from PIL import Image, ImageOps
    from pypdf import PdfReader

    if not data or len(data) > 10 * 1024 * 1024:
        raise ValueError('Files must be between 1 byte and 10 MB.')
    Image.MAX_IMAGE_PIXELS = 20_000_000
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        def ocr(path):
            with Image.open(path) as picture:
                if picture.width * picture.height > 20_000_000:
                    raise ValueError('Image exceeds 20 megapixels.')
                ImageOps.exif_transpose(picture).convert('RGB').save(root / 'ocr.png')
            result = subprocess.run(['tesseract', str(root / 'ocr.png'), 'stdout'],
                                    capture_output=True, text=True, check=True, timeout=40)
            return result.stdout
        used_ocr = False
        if extension == '.pdf':
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ValueError('Upload an unencrypted PDF.')
            if len(reader.pages) > 10:
                raise ValueError('PDFs may contain at most 10 pages.')
            (root / 'input.pdf').write_bytes(data)
            pages = []
            for index, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                if not text.strip():
                    used_ocr = True
                    subprocess.run(['pdftoppm', '-f', str(index), '-l', str(index), '-scale-to', '2400',
                                    '-singlefile', '-png', str(root / 'input.pdf'), str(root / 'page')],
                                   capture_output=True, check=True, timeout=30)
                    text = ocr(root / 'page.png')
                pages.append(text)
            text = '\n\n'.join(pages)
        elif extension in {'.png', '.jpg', '.jpeg', '.webp'}:
            used_ocr = True
            path = root / ('input' + extension)
            path.write_bytes(data)
            text = ocr(path)
        else:
            raise ValueError('Unsupported attachment format.')
        if not text.strip():
            raise ValueError('No readable text found. Try a clearer photo or paste the text.')
        if len(text) > 32000:
            raise ValueError('Extracted text is too long. Upload a shorter excerpt.')
        return {'text': text.strip(), 'ocr': used_ocr}
