from fastapi.testclient import TestClient
from the_pigeon_holes.ui.api import app

client = TestClient(app)

def test_text_extracted_without_cloud_call():
    response = client.post('/api/attachments?filename=notes.md', content=b'Prove n + 0 = n')
    assert response.status_code == 200
    assert response.json() == {'text': 'Prove n + 0 = n', 'ocr': False}

def test_lean_source_preserved():
    source = 'theorem x : True := by trivial\n'
    response = client.post('/api/attachments?filename=proof.lean', content=source.encode())
    assert response.json()['text'] == source

def test_bad_attachments_rejected():
    assert client.post('/api/attachments?filename=x.exe', content=b'x').status_code == 415
    assert client.post('/api/attachments?filename=x.txt', content=b'').status_code == 422
    assert client.post('/api/attachments?filename=x.txt', content=b'\xff').status_code == 422
    assert client.post('/api/attachments?filename=x.txt', content=b'x' * (10 * 1024 * 1024 + 1)).status_code == 413

def test_image_calls_extractor(monkeypatch):
    import modal
    class Remote:
        async def aio(self, data, extension):
            assert data == b'image bytes' and extension == '.png'
            return {'text': 'extracted problem', 'ocr': True}
    class Extractor:
        remote = Remote()
    monkeypatch.setattr(modal.Function, 'from_name', lambda *args: Extractor())
    result = client.post('/api/attachments?filename=photo.png', content=b'image bytes')
    assert result.json() == {'text': 'extracted problem', 'ocr': True}
