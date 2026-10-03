"""Bounded attachment ingestion; extracted content is reviewed before submission."""
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
import asyncio

router = APIRouter()
ALLOWED = {'.txt', '.md', '.lean', '.json', '.csv', '.pdf', '.png', '.jpg', '.jpeg', '.webp'}
MAX_BYTES = 10 * 1024 * 1024

@router.post('/api/attachments')
async def extract_attachment(request: Request, filename: str):
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED:
        raise HTTPException(415, 'Use PNG, JPEG, WebP, PDF, TXT, Markdown, JSON, CSV, or Lean files.')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, 'Each attachment must be at most 10 MB.')
    if not data:
        raise HTTPException(422, 'The attachment is empty.')
    if extension in {'.txt', '.md', '.lean', '.json', '.csv'}:
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise HTTPException(422, 'Text attachments must use UTF-8 encoding.')
        if not text.strip() or len(text) > 32000:
            raise HTTPException(422, 'Text attachments must contain 1–32000 characters.')
        return {'text': text, 'ocr': False}
    import modal
    try:
        return await asyncio.wait_for(modal.Function.from_name('lean-attachments', 'extract').remote.aio(bytes(data), extension), 240)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, 'Could not read the attachment. Try a clearer or smaller file, or paste its text.') from exc
