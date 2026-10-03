import { readAttachment } from './attachments';
const element = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const dialog = element('dialog');
const form = element<HTMLFormElement>('upload-form');
const mode = element<HTMLSelectElement>('mode');
const problem = element<HTMLTextAreaElement>('problem-text');
const source = element<HTMLTextAreaElement>('lean-input');
let busy = false;
element('upload').onclick = () => { dialog.hidden = false; problem.focus(); };
element('cancel').onclick = () => { dialog.hidden = true; };
mode.onchange = () => {
  element('formal-input').hidden = mode.value !== 'formal';
  source.required = mode.value === 'formal';
  element('attachment-target-label').hidden = mode.value !== 'formal';
  form.querySelector('button.primary')!.textContent = mode.value === 'formal' ? 'Validate Lean' : 'Generate and validate';
};
element<HTMLInputElement>('lean-file').onchange = async (event) => {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  if (file.size > 32000) { element('form-error').textContent = 'Lean file must be under 32 KB.'; return; }
  source.value = await file.text();
};

element<HTMLInputElement>('attachment-file').onchange = async (event) => {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  input.disabled = true;
  const submit = form.querySelector<HTMLButtonElement>('button.primary')!;
  submit.disabled = true;
  element('form-error').textContent = '';
  const target = mode.value === 'formal' && element<HTMLSelectElement>('attachment-target').value === 'lean' ? source : problem;
  try {
    for (const file of files) {
      element('attachment-status').textContent = 'Reading ' + file.name + '…';
      const result = await readAttachment(file);
      const text = [target.value.trim(), result.text].filter(Boolean).join('\n\n');
      if (text.length > target.maxLength) throw Error('Combined text exceeds the field limit. Use a smaller excerpt.');
      target.value = text;
    }
    element('attachment-status').textContent = `${files.length} attachment(s) read. Review the extracted text above before submitting.`;
  } catch (error) {
    element('form-error').textContent = error instanceof Error ? error.message : 'Could not read attachment.';
    element('attachment-status').textContent = 'Check the fields above; files read before the error have been added.';
  } finally { input.disabled = false; submit.disabled = false; input.value = ''; }
};

function log(message: string) {
  const row = document.createElement('div'); row.className = 'line';
  row.textContent = new Date().toLocaleTimeString() + '  ' + message;
  element('logs').append(row);
}
function detail(title: string, text: string) {
  const heading = document.createElement('h2'); heading.textContent = title;
  const content = document.createElement('p'); content.className = 'description'; content.textContent = text;
  element('details').replaceChildren(heading, content);
}
form.onsubmit = async (event) => {
  event.preventDefault();
  if (busy || !problem.value.trim()) return;
  busy = true; dialog.hidden = true;
  element<HTMLButtonElement>('upload').disabled = true;
  element('problem-title').textContent = problem.value.split('\n')[0].slice(0, 120);
  element('problem-sub').textContent = mode.value === 'formal' ? 'Existing Lean formulation' : 'Qwen3-4B-Instruct · generation + one repair attempt';
  element('validation-status').textContent = 'Processing…';
  element('run-state').textContent = 'Running';
  element('best').textContent = '—'; element('count').textContent = '0';
  element('lean-output').textContent = mode.value === 'formal' ? source.value : 'Generating Lean…';
  detail('Preparing your formulation.', 'Hosted models may take a few minutes to start. Lean checking and fidelity scoring follow generation.');
  log('Submitted ' + (mode.value === 'formal' ? 'existing Lean' : 'natural-language problem'));
  const started = Date.now();
  const clock = window.setInterval(() => {
    const seconds = Math.floor((Date.now() - started) / 1000);
    element('elapsed').textContent = `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
  }, 1000);
  try {
    const response = await fetch('/api/formalizations', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: mode.value, problem: problem.value, lean: source.value }) });
    const result = await response.json();
    if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : 'Input could not be processed.');
    element('lean-output').textContent = result.lean;
    element('count').textContent = String(result.attempts);
    element('best').textContent = result.fidelity?.p_faithful == null ? '—' : `${(result.fidelity.p_faithful * 100).toFixed(1)}%`;
    const status = result.status === 'checked' ? 'Lean checked · fidelity accepted' : result.lean_checked ? 'Lean checked · review alignment' : 'Lean validation failed';
    element('validation-status').textContent = status;
    element('run-state').textContent = 'Complete';
    detail(status, result.fidelity_error || (result.fidelity ? 'Fidelity: ' + result.fidelity.reason_code : result.diagnostics));
    if (result.diagnostics) log(result.diagnostics);
    log(status);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Service unavailable';
    element('run-state').textContent = 'Failed';
    element('validation-status').textContent = 'Service error';
    detail('Could not complete this request.', message); log(message);
  } finally {
    clearInterval(clock); busy = false; element<HTMLButtonElement>('upload').disabled = false;
  }
};
