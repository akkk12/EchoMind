import { useMemo, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";

export default function TimelineExplorer() {
  const [project, setProject] = useState("CheckoutFlow");
  const [timeline, setTimeline] = useState(null);
  const [activeType, setActiveType] = useState("All");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const events = useMemo(() => {
    const raw = timeline?.events || [];
    return (activeType === "All" ? raw : raw.filter((event) => event.type === activeType)).sort((a, b) => String(a.date || "").localeCompare(String(b.date || "")));
  }, [timeline, activeType]);

  const types = useMemo(() => ["All", ...Array.from(new Set((timeline?.events || []).map((event) => event.type))).sort()], [timeline]);

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/timeline?project=${encodeURIComponent(project.trim())}`);
      if (!response.ok) throw new Error("Could not fetch timeline.");
      setTimeline(await response.json());
      setActiveType("All");
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 px-6 py-6 text-slate-100">
      <header className="border-b border-slate-800 pb-5">
        <div className="text-sm font-medium uppercase tracking-wide text-cyan-300">Timeline Explorer</div>
        <h1 className="mt-1 text-3xl font-semibold">Project Evolution</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">Trace how a project changed through incidents, decisions, reviews, tickets, and pull requests.</p>
      </header>
      <form onSubmit={handleSubmit} className="mt-6 flex gap-3 rounded-lg border border-slate-800 bg-slate-900 p-3">
        <input className="min-h-11 flex-1 rounded-md border border-slate-700 bg-slate-950 px-4 text-sm outline-none focus:border-cyan-400" value={project} onChange={(event) => setProject(event.target.value)} />
        <button className="rounded-md bg-cyan-400 px-5 text-sm font-semibold text-slate-950 disabled:opacity-60" disabled={loading}>{loading ? "Loading" : "Load Timeline"}</button>
      </form>
      {error && <div className="mt-4 rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-200">{error}</div>}
      {timeline && <section className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-5"><div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-800 pb-5"><div><div className="text-xs font-medium uppercase tracking-wide text-cyan-300">Project Timeline</div><h2 className="mt-1 text-2xl font-semibold">{timeline.project}</h2></div><div className="flex flex-wrap gap-2">{types.map((type) => <button key={type} onClick={() => setActiveType(type)} className={`rounded-md border px-3 py-2 text-sm ${activeType === type ? "border-cyan-400 bg-cyan-950 text-cyan-100" : "border-slate-700 bg-slate-950 text-slate-300"}`}>{formatType(type)}</button>)}</div></div><div className="mt-6 border-l border-slate-700 pl-5">{events.map((event) => <TimelineCard key={`${event.type}-${event.id}`} event={event} />)}</div></section>}
      {!timeline && !loading && <div className="mt-6 rounded-lg border border-slate-800 bg-slate-900 p-6 text-sm text-slate-400">Try CheckoutFlow for the richest connected story.</div>}
    </div>
  );
}

function TimelineCard({ event }) {
  return <article className="relative mb-5 rounded-lg border border-slate-800 bg-slate-950 p-4 last:mb-0"><div className={`absolute -left-[27px] top-5 h-3.5 w-3.5 rounded-full border-2 border-slate-950 ${dotColor(event.type)}`} /><div className="flex items-start justify-between gap-3"><div><span className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-cyan-200">{formatType(event.type)}</span><h3 className="mt-3 text-lg font-semibold">{event.title}</h3></div><time className="rounded-md border border-slate-800 bg-slate-900 px-3 py-1 text-xs text-slate-400">{formatDate(event.date)}</time></div><p className="mt-3 text-sm leading-6 text-slate-300">{event.summary}</p></article>;
}

function formatType(type) {
  return type === "PullRequest" ? "Pull Request" : type === "ArchitectureReview" ? "Architecture Review" : type;
}

function formatDate(value) {
  if (!value) return "No date";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function dotColor(type) {
  return type === "Incident" ? "bg-red-400" : type === "Decision" ? "bg-cyan-300" : type === "ArchitectureReview" ? "bg-violet-300" : type === "Ticket" ? "bg-amber-300" : "bg-emerald-300";
}
