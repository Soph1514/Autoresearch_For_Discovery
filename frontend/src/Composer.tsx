import { mountCustomResearch, type InstanceReview } from './customResearch';
import { formalize, type Progress } from './formalizationClient';
import { attachmentAccept, readAttachment } from "./attachments";
import { useEffect, useRef, useState } from "react";

type Result = InstanceReview & {
  formalization_id?: string; lean: string; lean_checked: boolean; diagnostics: string; status: string;
  attempts: number; generator: string; fidelity_error: string | null;
  fidelity: null | { p_faithful: number | null; fidelity_decision: string; reason_code: string };
};
function CustomResearch({id, result}: {id: string; result: Result}) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => mountCustomResearch(host.current!, id, result), [id, result]);
  return <div ref={host} />;
}
export function Composer({ onClose }: { onClose: () => void }) {
  const controller = useRef<AbortController | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const resultSection = useRef<HTMLElement>(null);
  const [mode, setMode] = useState<"natural" | "formal">("natural");
  const [problem, setProblem] = useState("");
  const [instance, setInstance] = useState("");
  const [lean, setLean] = useState("");
  const [attachmentTarget, setAttachmentTarget] = useState("problem");
  const [attachmentStatus, setAttachmentStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  useEffect(() => { if (result) resultSection.current?.scrollIntoView({block: 'start'}); }, [result]);
  useEffect(() => { dialog.current?.showModal(); return () => controller.current?.abort(); }, []);
  async function submit() {
    setBusy(true); setError(""); setResult(null); setProgress(null);
    try {
      controller.current = new AbortController();
      const body = await formalize({ mode, problem, instance, lean }, controller.current.signal, (event) => setProgress((previous) => ({ ...previous, ...event })));
      setResult(body);
    } catch (e) { setError(controller.current?.signal.aborted ? "Stopped. Latest source is shown below." : e instanceof Error ? e.message : "Formalization failed."); }
    finally { setBusy(false); controller.current = null; }
  }
  return <dialog className={result ? 'review-dialog' : ''} ref={dialog} onCancel={(e) => { if (busy) e.preventDefault(); else onClose(); }}>
    <form onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <div className="dialog-head"><h2>Formalize your problem.</h2>
        <button type="button" disabled={busy} onClick={onClose} aria-label="Close problem composer">×</button></div>
      <label className="field">Starting point (optional · defaults to natural language)
        <select disabled={busy} value={mode} onChange={(e) => { setMode(e.target.value as typeof mode); if (attachmentTarget === 'lean') setAttachmentTarget('problem'); setResult(null); }}>
          <option value="natural">Describe a problem — generate Lean</option>
          <option value="formal">I already have a Lean formulation</option>
        </select>
      </label>
      <label className="field">General problem, objective, and constraints (natural language)
        <textarea autoFocus required disabled={busy} rows={5} maxLength={16000} value={problem}
          onChange={(e) => { setProblem(e.target.value); setResult(null); }} />
      </label>
      <label className="field">Specific instance to solve (natural language)
        <textarea required disabled={busy} rows={4} maxLength={16000} value={instance}
          placeholder="For example: The weights are 3, 4, and 5. The capacity is 7."
          onChange={(e) => { setInstance(e.target.value); setResult(null); }} />
      </label>
      {mode === "formal" && <>
        <label className="field">Existing Lean formulation (required for this option)
          <textarea required disabled={busy} rows={9} maxLength={32000} value={lean}
            onChange={(e) => { setLean(e.target.value); setResult(null); }} />
        </label>
        <label className="field">Load a .lean file (optional · fills the source field)
          <input type="file" accept=".lean" disabled={busy} onChange={async (e) => {
            const file = e.target.files?.[0];
            if (file) { if (file.size > 32000) { setError("Lean file must be under 32 KB."); return; }
              setLean(await file.text()); setResult(null); }
          }} />
        </label>
      </>}
      <label className="field">Add attachment text to
        <select disabled={busy} value={attachmentTarget} onChange={(e) => setAttachmentTarget(e.target.value)}>
          <option value="problem">General problem</option><option value="instance">Specific instance</option>
          {mode === "formal" && <option value="lean">Existing Lean source</option>}
        </select>
      </label>
      <label className="field">Photo or attachment (optional · can fill either field)
        <input type="file" multiple accept={attachmentAccept} disabled={busy} onChange={async (e) => {
          const input = e.currentTarget;
          const files = Array.from(input.files || []);
          const toLean = mode === "formal" && attachmentTarget === "lean";
          const toInstance = attachmentTarget === "instance";
          let text = toLean ? lean : toInstance ? instance : problem;
          setBusy(true); setError(""); setResult(null);
          try {
            for (const file of files) {
              setAttachmentStatus("Reading " + file.name + "…");
              const result = await readAttachment(file);
              const combined = [text.trim(), result.text].filter(Boolean).join("\n\n");
              if (combined.length > (toLean ? 32000 : 16000)) throw Error("Combined text exceeds the field limit. Use a smaller excerpt.");
              text = combined;
              if (toLean) setLean(text); else if (toInstance) setInstance(text); else setProblem(text);
            }
            setAttachmentStatus("Attachments read. Review the extracted text before submitting.");
          } catch (err) { setError(err instanceof Error ? err.message : "Could not read attachment."); setAttachmentStatus(""); }
          finally { setBusy(false); input.value = ""; }
        }} />
      </label>
      <p className="muted">Photos, PDFs (up to 10 pages), and text files · 10 MB each. Review extracted text; OCR can misread handwriting and mathematical symbols.</p>
      {attachmentStatus && <p role="status">{attachmentStatus}</p>}
      <p className="muted">We generate Lean for the general problem and JSON inputs for your instance. Review both before preparing research.</p>
      {busy && !attachmentStatus.startsWith("Reading") && <p role="status">Generating and checking Lean… Hosted models may take a few minutes to start.</p>}
      {error && <p role="alert" className="notice">{error}</p>}
      {controller.current && <button type="button" onClick={() => controller.current?.abort()}>Stop</button>}
      {!result && progress && <section><p role="status">Attempt {progress.attempt}: {progress.stage}</p>
        {progress.lean && <textarea aria-label="Latest Lean source" readOnly rows={8} value={progress.lean} />}
        {progress.diagnostics && <pre>{progress.diagnostics}</pre>}</section>}
      {result && <section ref={resultSection} aria-label="Formalization result">
        <h3>{result.status === "checked" ? "Lean checked · fidelity accepted" : result.lean_checked ? "Lean checked · alignment needs review" : "Lean validation failed"}</h3>
        <p>{result.generator} · {result.attempts} check attempt(s)</p>
        {result.fidelity_error && <p role="alert">{result.fidelity_error}</p>}
        {result.fidelity && <p>Fidelity score: {result.fidelity.p_faithful === null ? "Unavailable" : `${(result.fidelity.p_faithful * 100).toFixed(1)}%`} · {result.fidelity.reason_code}</p>}
        {!result.lean_checked && <label className="field">Lean source<textarea readOnly rows={12} value={result.lean} /></label>}
        {result.diagnostics && <pre style={{ whiteSpace: "pre-wrap" }}>{result.diagnostics}</pre>}
        <p className="notice">Lean checking does not prove natural-language equivalence. Review the Lean and instance JSON below before continuing.</p>
      {result.formalization_id && result.lean_checked && <CustomResearch id={result.formalization_id} result={result} />}
      </section>}
      <div className="dialog-actions"><button type="button" disabled={busy} onClick={onClose}>Close</button>
        <button className="primary" disabled={busy || !problem.trim() || !instance.trim() || (mode === "formal" && !lean.trim())}>
          {mode === "formal" ? "Check Lean and generate instance JSON" : "Generate Lean and instance JSON"}</button></div>
    </form>
  </dialog>;
}
