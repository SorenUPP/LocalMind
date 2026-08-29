"use client";

import { useRef, useState } from "react";

type CellValue = string | number | boolean | null;
type ResultRow = Record<string, CellValue>;
type UnresolvedResponse = { status: "unresolved"; message: string };
type CompileResponse = { status: "validated"; request_id: string; ast: unknown } | UnresolvedResponse;
type ExecuteResponse = { status: "success"; row_count: number; rows: ResultRow[] } | UnresolvedResponse;
type DatasetUploadResponse = { columns: string[]; dataset: string; row_count: number };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const EXAMPLES = [
  "What was average revenue by region?",
  "Show total revenue by region",
  "Which region has the most sales records?",
];

function Arrow() {
  return <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 16 16"><path d="M2.5 8h10M8.5 4l4 4-4 4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" /></svg>;
}

async function readError(response: Response): Promise<string> {
  const payload: unknown = await response.json().catch(() => null);
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    return typeof payload.detail === "string" ? payload.detail : "The query could not be processed.";
  }
  return `Request failed (${response.status}).`;
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<ResultRow[]>([]);
  const [rowCount, setRowCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadSummary, setUploadSummary] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function uploadDataset() {
    if (!selectedFile) {
      setError("Choose a CSV file before importing it.");
      return;
    }

    setUploading(true);
    setError(null);
    setUploadSummary(null);
    try {
      const body = new FormData();
      body.append("file", selectedFile);
      const response = await fetch(`${API_URL}/api/v1/datasets/sales/upload`, { method: "POST", body });
      if (!response.ok) throw new Error(await readError(response));

      const uploaded: DatasetUploadResponse = await response.json();
      setUploadSummary(`Loaded ${uploaded.row_count} rows with ${uploaded.columns.length} columns into ${uploaded.dataset}.`);
      setSelectedFile(null);
      setResult([]);
      setRowCount(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (caughtError: unknown) {
      setError(caughtError instanceof Error ? caughtError.message : "The CSV could not be imported.");
    } finally {
      setUploading(false);
    }
  }

  async function runQuery() {
    const trimmedQuery = query.trim();
    if (!trimmedQuery) {
      setError("Write a question before running the analysis.");
      return;
    }

    setLoading(true);
    setError(null);
    setResult([]);
    setRowCount(null);
    try {
      const compileResponse = await fetch(`${API_URL}/api/v1/queries/compile?user_query=${encodeURIComponent(trimmedQuery)}&dataset=sales`, { method: "POST" });
      if (!compileResponse.ok) throw new Error(await readError(compileResponse));

      const compiled: CompileResponse = await compileResponse.json();
      if (compiled.status === "unresolved") {
        setError(compiled.message);
        return;
      }

      const executeResponse = await fetch(`${API_URL}/api/v1/queries/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(compiled.ast),
      });
      if (!executeResponse.ok) throw new Error(await readError(executeResponse));

      const executed: ExecuteResponse = await executeResponse.json();
      if (executed.status === "unresolved") {
        setError(executed.message);
        return;
      }

      setResult(executed.rows);
      setRowCount(executed.row_count);
    } catch (caughtError: unknown) {
      setError(caughtError instanceof Error ? caughtError.message : "Something went wrong while running the analysis.");
    } finally {
      setLoading(false);
    }
  }

  const columns = result.length > 0 ? Object.keys(result[0]) : [];

  return (
    <main className="min-h-screen bg-[#f7f6f2] text-[#1b1c1a]">
      <div className="mx-auto max-w-7xl px-5 pb-20 pt-6 sm:px-8 lg:px-12">
        <nav aria-label="Main navigation" className="motion-enter flex items-center justify-between border-b border-[#c8c8c1] pb-5">
          <a className="text-xl font-semibold tracking-[-0.05em]" href="#top">LocalMind<span className="text-[#9b4b28]">.</span></a>
          <p className="text-xs uppercase tracking-[0.14em] text-[#676860]">Sales data / Local workspace</p>
        </nav>

        <header className="motion-enter-delayed grid gap-10 py-16 lg:grid-cols-[1.35fr_0.65fr] lg:py-24">
          <div id="top">
            <p className="mb-5 text-xs font-semibold uppercase tracking-[0.16em] text-[#9b4b28]">Ask. Inspect. Decide.</p>
            <h1 className="max-w-4xl text-5xl font-semibold leading-[0.95] tracking-[-0.065em] sm:text-6xl lg:text-8xl">A more direct way to read your data.</h1>
          </div>
          <div className="self-end border-l-2 border-[#1b1c1a] pl-5 text-base leading-7 text-[#55564f]">
            LocalMind converts a question into a checked query against your local sales dataset. You get the answer, without needing to write SQL.
          </div>
        </header>

        <section className="grid border-y border-[#c8c8c1] lg:grid-cols-[1.35fr_0.65fr]">
          <div className="motion-enter workspace-panel border-b border-[#c8c8c1] p-5 lg:border-b-0 lg:border-r lg:p-8">
            <div className="flex items-start justify-between gap-4 border-b border-[#deded7] pb-5">
              <div><p className="text-sm font-semibold">New analysis</p><p className="mt-1 text-sm text-[#6b6c64]">Sales dataset · validated before execution</p></div>
              <span className="font-mono text-xs text-[#6b6c64]">01</span>
            </div>

            <label className="mt-7 block text-xs font-semibold uppercase tracking-[0.14em] text-[#595a54]" htmlFor="query">Your question</label>
            <textarea className="mt-3 min-h-40 w-full resize-y border border-[#bfc0b8] bg-transparent px-4 py-4 text-lg leading-8 outline-none transition placeholder:text-[#9a9b94] focus:border-[#1b1c1a]" id="query" onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void runQuery(); }} placeholder="What was average revenue by region?" value={query} />

            <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
              <p className="font-mono text-xs text-[#777870]">Ctrl/Cmd + Enter to run</p>
              <button className="run-button inline-flex items-center gap-2 border border-[#1b1c1a] bg-[#1b1c1a] px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:border-[#989993] disabled:bg-[#989993]" disabled={loading} onClick={() => void runQuery()} type="button">{loading ? "Analysing request…" : "Run analysis"}<Arrow /></button>
            </div>
          </div>

          <aside className="motion-enter-delayed p-5 lg:p-8">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#595a54]">Start with a prompt</p>
            <div className="mt-5 divide-y divide-[#d6d7d0] border-y border-[#d6d7d0]">
              {EXAMPLES.map((example, index) => (
                <button className="prompt-option flex w-full items-center justify-between gap-4 py-4 text-left text-sm font-medium" key={example} onClick={() => setQuery(example)} type="button"><span><span className="mr-3 font-mono text-xs text-[#9b4b28]">0{index + 1}</span>{example}</span><Arrow /></button>
              ))}
            </div>
            <div className="mt-8 border-t border-[#d6d7d0] pt-5 text-sm leading-6 text-[#686963]"><p className="font-semibold text-[#30312e]">A practical guardrail</p><p className="mt-2">Questions are mapped to the columns that exist in this dataset before anything runs.</p></div>
            <div className="mt-8 border-t border-[#d6d7d0] pt-5">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#595a54]">Use your own data</p>
              <p className="mt-2 text-sm leading-6 text-[#686963]">Import a CSV to replace the sample sales dataset. Your file stays on this machine.</p>
              <input accept=".csv,text/csv" className="mt-4 block w-full text-xs text-[#55564f] file:mr-3 file:border file:border-[#1b1c1a] file:bg-transparent file:px-3 file:py-2 file:text-xs file:font-semibold file:text-[#1b1c1a] hover:file:bg-[#eeece5]" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} ref={fileInputRef} type="file" />
              <button className="mt-3 inline-flex items-center gap-2 border border-[#1b1c1a] px-4 py-2 text-xs font-semibold transition hover:bg-[#1b1c1a] hover:text-white disabled:cursor-not-allowed disabled:border-[#aaa9a2] disabled:text-[#8b8c85]" disabled={!selectedFile || uploading} onClick={() => void uploadDataset()} type="button">{uploading ? "Importing CSV…" : "Import CSV"}<Arrow /></button>
              {uploadSummary && <p className="mt-3 border-l-2 border-[#9b4b28] pl-3 text-xs leading-5 text-[#55564f]" role="status">{uploadSummary}</p>}
            </div>
          </aside>
        </section>

        {error && <p className="motion-enter mt-6 border-l-2 border-[#9b4b28] bg-[#f1e2d8] px-5 py-4 text-sm text-[#732f19]" role="alert">{error}</p>}

        {rowCount !== null && (
          <section aria-live="polite" className="motion-enter mt-14">
            <div className="flex flex-col gap-4 border-b-2 border-[#1b1c1a] pb-5 sm:flex-row sm:items-end sm:justify-between">
              <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#9b4b28]">Query complete</p><h2 className="mt-2 text-4xl font-semibold tracking-[-0.045em]">Results</h2></div>
              <p className="font-mono text-sm text-[#595a54]">{rowCount} {rowCount === 1 ? "record" : "records"} returned</p>
            </div>

            {result.length === 0 ? (
              <div className="border-b border-[#c8c8c1] py-12"><p className="text-lg font-medium">No matching records.</p><p className="mt-2 text-sm text-[#6b6c64]">Try a wider time range or a different measure.</p></div>
            ) : (
              <div className="overflow-x-auto border-b border-[#c8c8c1]">
                <table className="w-full min-w-max text-left text-sm">
                  <thead className="border-b border-[#c8c8c1] font-mono text-xs uppercase tracking-[0.1em] text-[#62635c]"><tr>{columns.map((column) => <th className="px-4 py-4 font-medium first:pl-0" key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead>
                  <tbody className="divide-y divide-[#deded7]">{result.map((row, index) => <tr className="transition-colors hover:bg-[#eeece5]" key={index}>{columns.map((column) => <td className="px-4 py-4 first:pl-0" key={column}>{row[column] === null ? <span className="text-[#999a93]">—</span> : String(row[column])}</td>)}</tr>)}</tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </div>
    </main>
  );
}
