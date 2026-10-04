export const attachmentAccept = '.png,.jpg,.jpeg,.webp,.pdf,.txt,.md,.lean,.json,.csv';
export async function readAttachment(file: File): Promise<{text: string; ocr: boolean}> {
  if (file.size > 10 * 1024 * 1024) throw Error('Each attachment must be at most 10 MB.');
  const response = await fetch('/api/attachments?filename=' + encodeURIComponent(file.name), {
    method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
  });
  const result = await response.json();
  if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Could not read attachment.');
  return result;
}
