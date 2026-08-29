"use client";

import { useRef, useState } from "react";

type CellValue = string | number | boolean | null;
type ResultRow = Record<string, CellValue>;
type UnresolvedResponse = { status: "unresolved"; message: string };
type AskResponse =
  | { status: "success"; request_id: string; ast: unknown; rows: ResultRow[]; row_count: number; answer: string | null; answer_note?: string }
  | UnresolvedResponse;
type DatasetUploadResponse = { columns: string[]; dataset: string; row_count: number };

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const EXAMPLES = [
  "What was average revenue by region?",
  "Show total revenue by region",
  "Which region has the most sales records?",
];
const MAX_RECENT = 4;
const PERCENT_LIKE = /pct|percent|growth|rate|share/i;

function Arrow() {
  return <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 16 16"><path d="M2.5 8h10M8.5 4l4 4-4 4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" /></svg>;
}

function Spinner() {
  return <svg aria-hidden="true" className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" d="M4 12a8 8 0 018-8" stroke="currentColor" strokeLinecap="round" strokeWidth="4" /></svg>;
}

function DownloadIcon() {
  return <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 16 16"><path d="M8 2v8m0 0L5 7m3 3l3-3M2.5 12.5h11" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" /></svg>;
}

async function readError(response: Response): Promise<string> {
  const payload: unknown = await response.json().catch(() => null);
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    return typeof payload.detail === "string" ? payload.detail : "The query could not be processed.";
  }
  return `Request failed (${response.status}).`;
}

function formatCell(column: string, value: CellValue): { text: string; tone: "neutral" | "positive" | "negative" } {
  if (value === null) return { text: "—", tone: "neutral" };
  if (typeof value === "number") {
    const isPercent = PERCENT_LIKE.test(column);
    const formatted = value.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: isPercent ? 1 : 0 });
    if (isPercent) {
      return { text: `${value > 0 ? "+" : ""}${formatted}%`, tone: value > 0 ? "positive" : value < 0 ? "negative" : "neutral" };
    }
    return { text: formatted, tone: "neutral" };
  }
  return { text: String(value), tone: "neutral" };
}

function toCsv(columns: string[], rows: ResultRow[]): string {
  const escape = (value: CellValue) => {
    if (value === null) return "";
    const str = String(value);
    return /[",\n]/.test(str) ? `"${str.replaceAll('"', '""')}"` : str;
  };
  const lines = [columns.join(","), ...rows.map((row) => columns.map((column) => escape(row[column])).join(","))];
  return lines.join("\n");
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<ResultRow[]>([]);
  const [rowCount, setRowCount] = useState<number | null>(null);
  const [hasRun, setHasRun] = useState(false);
  const [answer, setAnswer] = useState<string | null>(null);
  const [answerNote, setAnswerNote] = useState<string | null>(null);
  const [plan, setPlan] = useState<unknown>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadSummary, setUploadSummary] = useState<string | null>(null);
  const [recentQueries, setRecentQueries] = useState<string[]>([]);
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
      setHasRun(false);
      setAnswer(null);
      setAnswerNote(null);
      setPlan(null);
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
    try {
      const response = await fetch(`${API_URL}/api/v1/queries/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_query: trimmedQuery, dataset: "sales" }),
      });
      if (!response.ok) throw new Error(await readError(response));

      const asked: AskResponse = await response.json();
      if (asked.status === "unresolved") {
        setError(asked.message);
        return;
      }

      setResult(asked.rows);
      setRowCount(asked.row_count);
      setAnswer(asked.answer);
      setAnswerNote(asked.answer_note ?? null);
      setPlan(asked.ast);
      setRecentQueries((previous) => [trimmedQuery, ...previous.filter((entry) => entry !== trimmedQuery)].slice(0, MAX_RECENT));
    } catch (caughtError: unknown) {
      setError(caughtError instanceof Error ? caughtError.message : "Something went wrong while running the analysis.");
    } finally {
      setHasRun(true);
      setLoading(false);
    }
  }

  function downloadCsv() {
    if (result.length === 0) return;
    const csv = toCsv(columns, result);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "localmind-results.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  const columns = result.length > 0 ? Object.keys(result[0]) : [];

  return (
    <main className="min-h-screen bg-[#f7f6f2] text-[#1b1c1a]">
      <div className="mx-auto max-w-7xl px-5 pb-20 pt-6 sm:px-8 lg:px-12">
        <nav aria-label="Main navigation" className="motion-enter flex items-center justify-between border-b border-[#c8c8c1] pb-5">
          <a className="text-xl font-semibold tracking-[-0.05em]" href="#top">LocalMind<span className="text-[#9b4b28]">.</span></a>
          <p className="text-xs uppercase tracking-[0.14em] text-[#676860]">Sales data / Local workspace</p>
        </nav>

        <header className="motion-enter-delayed py-8 lg:py-10" id="top">
          <p className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-[#9b4b28]">Ask. Inspect. Decide.</p>
          <h1 className="max-w-3xl text-3xl font-semibold leading-[0.98] tracking-[-0.05em] sm:text-4xl lg:text-5xl">A more direct way to read your data.</h1>
        </header>

        <section className="grid gap-6 lg:grid-cols-[0.85fr_1.15fr] lg:items-start">
          <div className="motion-enter workspace-panel border border-[#c8c8c1] p-5 lg:p-6">
            <div className="flex items-start justify-between gap-4 border-b border-[#deded7] pb-4">
              <div><p className="text-sm font-semibold">New analysis</p><p className="mt-1 text-sm text-[#6b6c64]">Sales dataset · validated before execution</p></div>
              <span className="font-mono text-xs text-[#6b6c64]">01</span>
            </div>

            <label className="mt-5 block text-xs font-semibold uppercase tracking-[0.14em] text-[#595a54]" htmlFor="query">Your question</label>
            <textarea className="mt-3 min-h-28 w-full resize-y border border-[#bfc0b8] bg-transparent px-4 py-3 text-base leading-7 outline-none transition placeholder:text-[#9a9b94] focus:border-[#1b1c1a]" id="query" onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void runQuery(); }} placeholder="What was average revenue by region?" value={query} />

            <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
              <p className="font-mono text-xs text-[#777870]">Ctrl/Cmd + Enter to run</p>
              <button className="run-button inline-flex items-center gap-2 border border-[#1b1c1a] bg-[#1b1c1a] px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:border-[#989993] disabled:bg-[#989993]" disabled={loading} onClick={() => void runQuery()} type="button">{loading ? <><Spinner />Analysing…</> : <>Run analysis<Arrow /></>}</button>
            </div>

            {error && <p className="motion-enter mt-4 border-l-2 border-[#9b4b28] bg-[#f1e2d8] px-5 py-4 text-sm text-[#732f19]" role="alert">{error}</p>}

            {recentQueries.length > 0 && (
              <div className="mt-6 border-t border-[#d6d7d0] pt-5">
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#595a54]">Recent questions</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {recentQueries.map((entry) => (
                    <button className="border border-[#c8c8c1] px-3 py-1.5 text-xs text-[#55564f] transition hover:border-[#1b1c1a] hover:text-[#1b1c1a]" key={entry} onClick={() => setQuery(entry)} type="button">{entry.length > 44 ? `${entry.slice(0, 44)}…` : entry}</button>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-6 border-t border-[#d6d7d0] pt-5">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#595a54]">Start with a prompt</p>
              <div className="mt-4 divide-y divide-[#d6d7d0] border-y border-[#d6d7d0]">
                {EXAMPLES.map((example, index) => (
                  <button className="prompt-option flex w-full items-center justify-between gap-4 py-3 text-left text-sm font-medium" key={example} onClick={() => setQuery(example)} type="button"><span><span className="mr-3 font-mono text-xs text-[#9b4b28]">0{index + 1}</span>{example}</span><Arrow /></button>
                ))}
              </div>
            </div>

            <div className="mt-6 border-t border-[#d6d7d0] pt-5">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#595a54]">Use your own data</p>
              <p className="mt-2 text-sm leading-6 text-[#686963]">Import a CSV to replace the sample sales dataset. Your file stays on this machine.</p>
              <input accept=".csv,text/csv" className="mt-4 block w-full text-xs text-[#55564f] file:mr-3 file:border file:border-[#1b1c1a] file:bg-transparent file:px-3 file:py-2 file:text-xs file:font-semibold file:text-[#1b1c1a] hover:file:bg-[#eeece5]" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} ref={fileInputRef} type="file" />
              <button className="mt-3 inline-flex items-center gap-2 border border-[#1b1c1a] px-4 py-2 text-xs font-semibold transition hover:bg-[#1b1c1a] hover:text-white disabled:cursor-not-allowed disabled:border-[#aaa9a2] disabled:text-[#8b8c85]" disabled={!selectedFile || uploading} onClick={() => void uploadDataset()} type="button">{uploading ? "Importing CSV…" : "Import CSV"}<Arrow /></button>
              {uploadSummary && <p className="mt-3 border-l-2 border-[#9b4b28] pl-3 text-xs leading-5 text-[#55564f]" role="status">{uploadSummary}</p>}
            </div>
          </div>

          <div aria-busy={loading} aria-live="polite" className="motion-enter-delayed sticky top-6 border border-[#1b1c1a] p-5 lg:p-6">
            <div className="flex flex-col gap-3 border-b-2 border-[#1b1c1a] pb-4 sm:flex-row sm:items-end sm:justify-between">
              <div><p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#9b4b28]">{loading ? "Running…" : hasRun ? "Query complete" : "Awaiting a question"}</p><h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em] lg:text-3xl">Results</h2></div>
              <div className="flex items-center gap-3">
                {rowCount !== null && !loading && <p className="font-mono text-sm text-[#595a54]">{rowCount} {rowCount === 1 ? "record" : "records"}</p>}
                {result.length > 0 && !loading && <button className="inline-flex items-center gap-1.5 border border-[#c8c8c1] px-3 py-1.5 text-xs font-semibold text-[#55564f] transition hover:border-[#1b1c1a] hover:text-[#1b1c1a]" onClick={downloadCsv} type="button"><DownloadIcon />Export CSV</button>}
              </div>
            </div>

            {!loading && answer && (
              <div className="mt-4 border-l-2 border-[#1b1c1a] bg-[#eeece5] px-5 py-4">
                <p className="text-sm leading-6 text-[#30312e]">{answer}</p>
              </div>
            )}
            {!loading && !answer && answerNote && (
              <p className="mt-4 text-xs italic text-[#8b8c85]">{answerNote}</p>
            )}

            {loading ? (
              <div className="mt-2 animate-pulse space-y-3 py-4">
                {[0, 1, 2, 3].map((row) => <div className="h-6 bg-[#e7e6e0]" key={row} />)}
              </div>
            ) : !hasRun ? (
              <div className="py-16 text-center"><p className="text-base font-medium text-[#55564f]">Run an analysis to see results here.</p><p className="mt-2 text-sm text-[#8b8c85]">Try one of the example prompts on the left.</p></div>
            ) : result.length === 0 ? (
              <div className="py-12"><p className="text-lg font-medium">No matching records.</p><p className="mt-2 text-sm text-[#6b6c64]">Try a wider time range or a different measure.</p></div>
            ) : (
              <div className="mt-4 max-h-[32rem] overflow-auto">
                <table className="w-full min-w-max text-left text-sm">
                  <thead className="sticky top-0 border-b border-[#c8c8c1] bg-[#f7f6f2] font-mono text-xs uppercase tracking-[0.1em] text-[#62635c]"><tr>{columns.map((column) => <th className="px-4 py-3 font-medium first:pl-0" key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead>
                  <tbody className="divide-y divide-[#deded7]">
                    {result.map((row, index) => (
                      <tr className="transition-colors hover:bg-[#eeece5]" key={index}>
                        {columns.map((column) => {
                          const cell = formatCell(column, row[column]);
                          const toneClass = cell.tone === "positive" ? "text-[#2f6b3f]" : cell.tone === "negative" ? "text-[#9b4b28]" : "";
                          return <td className={`px-4 py-3 first:pl-0 ${cell.text === "—" ? "text-[#999a93]" : toneClass}`} key={column}>{cell.text}</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {!loading && plan !== null && (
              <details className="mt-4 border-t border-[#d6d7d0] pt-4">
                <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.14em] text-[#595a54]">View query plan</summary>
                <pre className="mt-3 overflow-x-auto bg-[#f1f1ec] p-3 text-xs leading-5 text-[#42433d]">{JSON.stringify(plan, null, 2)}</pre>
              </details>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}