import { useMemo, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";
const AI_BASE_URL = import.meta.env.VITE_AI_BASE_URL || "http://localhost:8000";

export default function DecisionExplorer() {
  const [query, setQuery] = useState("Why did checkout freeze during the holiday sale?");
  const [decisionResult, setDecisionResult] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const contributors = useMemo(() => {
    const names = new Set();
    decisionResult?.architectureReviews?.forEach((review) => review.participants?.forEach((name) => names.add(name)));
    decisionResult?.discussions?.forEach((discussion) => discussion.participants?.forEach((name) => names.add(name)));
    if (decisionResult?.decision?.owner) names.add(decisionResult.decision.owner);
    return Array.from(names);
  }, [decisionResult]);

  const timeline = useMemo(() => {
    if (!decisionResult) return [];
    return [
      ...(decisionResult.incidents || []).map((item) => ({ ...item, type: "Incident", summary: item.impact })),
      ...(decisionResult.architectureReviews || []).map((item) => ({ ...item, type: "Architecture Review", summary: item.discussionSummary || item.context, title: item.title })),
      ...(decisionResult.discussions || []).map((item) => ({ ...item, type: "Discussion", summary: item.summary, title: item.topic }))
    ].sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
  }, [decisionResult]);

  async function handleSearch(event) {
    event.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setDecisionResult(null);
    setAnalysis(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/decisions/search?query=${encodeURIComponent(query.trim())}`);
      if (!response.ok) throw new Error("Could not search decisions.");
      const results = await response.json();
      const first = Array.isArray(results) ? results[0] : results;
      if (!first) throw new Error("No matching decision found. Try CheckoutFlow, idempotency, or StockSync.");
      setDecisionResult(first);
      await analyze(first);
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  async function analyze(result) {
    try {
      const response = await fetch(`${AI_BASE_URL}/decision-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: query,
          decision: result.decision,
          architectureReviews: result.architectureReviews || [],
          incidents: result.incidents || [],
          discussions: result.discussions || []
        })
      });
      if (!response.ok) throw new Error("AI service unavailable.");
      setAnalysis(await response.json());
    } catch {
      setAnalysis({
        answer: result.decision.finalDecision,
        whyItMattered: result.decision.reasons || [],
        tradeoffs: ["AI service was unavailable, so this fallback uses structured graph evidence only."],
        citations: [],
        confidence: "medium"
      });
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 px-6 py-6 text-slate-100">
      <header className="border-b border-slate-800 pb-5">
        <div className="text-sm font-medium uppercase tracking-wide text-cyan-300">Decision Time Machine</div>
        <h1 className="mt-1 text-3xl font-semibold">Decision Explorer</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">Ask why a FreshCart decision happened and see the evidence behind the answer.</p>
      </header>

      <form onSubmit={handleSearch} className="mt-6 flex gap-3 rounded-lg border border-slate-800 bg-slate-900 p-3">
        <input className="min-h-11 flex-1 rounded-md border border-slate-700 bg-slate-950 px-4 text-sm outline-none focus:border-cyan-400" value={query} onChange={(event) => setQuery(event.target.value)} />
        <button className="rounded-md bg-cyan-400 px-5 text-sm font-semibold text-slate-950 disabled:opacity-60" disabled={loading}>{loading ? "Analyzing" : "Analyze"}</button>
      </form>

      {error && <div className="mt-4 rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-200">{error}</div>}

      {!decisionResult && (
        <div className="mt-6 grid gap-3 md:grid-cols-3">
          {["Why did checkout freeze during the holiday sale?", "Why did delivery notifications need idempotency keys?", "Why did FreshCart add inventory reservations?"].map((sample) => (
            <button key={sample} onClick={() => setQuery(sample)} className="rounded-lg border border-slate-800 bg-slate-900 p-4 text-left text-sm text-slate-300 hover:border-cyan-400">{sample}</button>
          ))}
        </div>
      )}

      {decisionResult && (
        <div className="mt-6 grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <section className="space-y-6">
            <Panel title={decisionResult.decision.title} eyebrow={`Matched decision ${decisionResult.decision.id}`}>
              <p className="text-sm leading-7 text-slate-300">{decisionResult.decision.finalDecision}</p>
              <div className="mt-4 flex flex-wrap gap-2">{decisionResult.decision.reasons?.map((reason) => <Badge key={reason}>{reason}</Badge>)}</div>
            </Panel>
            <Panel title="Polished Explanation" eyebrow={`Confidence: ${analysis?.confidence || "pending"}`}>
              <p className="text-sm leading-7 text-slate-200">{analysis?.answer || "Generating explanation..."}</p>
              <List title="Why it mattered" items={analysis?.whyItMattered} />
              <List title="Tradeoffs" items={analysis?.tradeoffs} />
            </Panel>
            <Panel title="Evidence" eyebrow="Reviews, incidents, and discussions">
              <div className="grid gap-3">{timeline.map((item) => <EvidenceCard key={`${item.type}-${item.id}`} item={item} />)}</div>
            </Panel>
          </section>
          <aside className="space-y-6">
            <Panel title="Contributors" eyebrow="People connected to this decision">
              <div className="grid gap-2">{contributors.map((name) => <div key={name} className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm">{name}</div>)}</div>
            </Panel>
            <Panel title="Related Timeline" eyebrow="Chronological context">
              <div className="border-l border-slate-700 pl-4">{timeline.map((item) => <TimelineItem key={`${item.type}-${item.id}`} item={item} />)}</div>
            </Panel>
          </aside>
        </div>
      )}
    </div>
  );
}

function Panel({ eyebrow, title, children }) {
  return <section className="rounded-lg border border-slate-800 bg-slate-900 p-5"><div className="text-xs font-medium uppercase tracking-wide text-cyan-300">{eyebrow}</div><h2 className="mt-1 text-xl font-semibold">{title}</h2><div className="mt-4">{children}</div></section>;
}

function Badge({ children }) {
  return <span className="rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-300">{children}</span>;
}

function List({ title, items = [] }) {
  if (!items.length) return null;
  return <div className="mt-5"><h3 className="text-sm font-semibold">{title}</h3><ul className="mt-2 space-y-2">{items.map((item) => <li key={item} className="rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-300">{item}</li>)}</ul></div>;
}

function EvidenceCard({ item }) {
  return <article className="rounded-md border border-slate-800 bg-slate-950 p-4"><div className="text-xs font-medium uppercase tracking-wide text-cyan-300">{item.type} {item.id}</div><h3 className="mt-1 font-semibold">{item.title || item.topic}</h3><p className="mt-2 text-sm leading-6 text-slate-400">{item.summary || item.rootCause || item.context}</p></article>;
}

function TimelineItem({ item }) {
  return <div className="relative mb-5 last:mb-0"><div className="absolute -left-[21px] top-1 h-3 w-3 rounded-full bg-cyan-300" /><div className="text-xs text-slate-500">{formatDate(item.date)}</div><div className="mt-1 text-sm font-semibold">{item.title}</div><div className="text-xs uppercase tracking-wide text-cyan-300">{item.type}</div></div>;
}

function formatDate(value) {
  if (!value) return "No date";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(date);
}
