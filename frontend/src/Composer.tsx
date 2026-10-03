import { useEffect, useRef, useState } from "react";

type Result = {
  lean: string; lean_checked: boolean; diagnostics: string; status: string;
  attempts: number; generator: string; fidelity_error: string | null;
  fidelity: null | { p_faithful: number | null; fidelity_decision: string; reason_code: string };
};
export function Composer({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [mode, setMode] = useState<"natural" | "formal">("natural");
  const [problem, setProblem] = useState("");
  const [lean, setLean] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  async function submit() {
    setBusy(true); setError(""); setResult(null);
    try {
      const response = await fetch("/api/formalizations", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode, problem, lean }),
      });
      const body = await response.json();
      if (!response.ok) throw Error(typeof body.detail === "string" ? body.detail : "Please check your problem and Lean input.");
      setResult(body);
    } catch (e) { setError(e instanceof Error ? e.message : "Formalization failed."); }
    finally { setBusy(false); }
  }
  return <dialog ref={dialog} onCancel={(e) => { if (busy) e.preventDefault(); else onClose(); }}>
    <form onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <div className="dialog-head"><h2>Formalize your problem.</h2>
        <button type="button" disabled={busy} onClick={onClose} aria-label="Close problem composer">×</button></div>
      <label className="field">Starting point (optional · defaults to natural language)
        <select disabled={busy} value={mode} onChange={(e) => { setMode(e.target.value as typeof mode); setResult(null); }}>
          <option value="natural">Describe a problem — Qwen generates Lean</option>
          <option value="formal">I already have a Lean formulation</option>
        </select>
      </label>
      <label className="field">Problem, objective, and constraints (required)
        <textarea autoFocus required disabled={busy} rows={5} maxLength={16000} value={problem}
          onChange={(e) => { setProblem(e.target.value); setResult(null); }} />
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
      <p className="muted">Qwen generates a formulation; Lean checks it, then our fine-tuned Qwen model scores its alignment with your problem.</p>
      {busy && <p role="status">Generating and checking Lean… Hosted models may take a few minutes to start.</p>}
      {error && <p role="alert" className="notice">{error}</p>}
      {result && <section aria-label="Formalization result">
        <h3>{result.status === "checked" ? "Lean checked · fidelity accepted" : result.lean_checked ? "Lean checked · alignment needs review" : "Lean validation failed"}</h3>
        <p>{result.generator} · {result.attempts} check attempt(s)</p>
        {result.fidelity_error && <p role="alert">{result.fidelity_error}</p>}
        {result.fidelity && <p>Fidelity score: {result.fidelity.p_faithful === null ? "Unavailable" : `${(result.fidelity.p_faithful * 100).toFixed(1)}%`} · {result.fidelity.reason_code}</p>}
        <label className="field">Lean source<textarea readOnly rows={12} value={result.lean} /></label>
        {result.diagnostics && <pre style={{ whiteSpace: "pre-wrap" }}>{result.diagnostics}</pre>}
        <p className="notice">Lean checking does not prove natural-language equivalence. Review the formulation before using it. Automated research for custom problems still requires a prepared evaluator and problem contract.</p>
      </section>}
      <div className="dialog-actions"><button type="button" disabled={busy} onClick={onClose}>Close</button>
        <button className="primary" disabled={busy || !problem.trim() || (mode === "formal" && !lean.trim())}>
          {mode === "formal" ? "Validate Lean" : "Generate and validate Lean"}</button></div>
    </form>
  </dialog>;
}
