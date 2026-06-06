import { useMemo, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8080";

export default function ExpertFinder() {
  const [project, setProject] = useState("StockSync");
  const [result, setResult] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const experts = result?.experts || [];
  const selected = useMemo(() => experts.find((expert) => expert.person.id === selectedId) || experts[0], [experts, selectedId]);

  async function handleSubmit(event) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/experts?project=${encodeURIComponent(project.trim())}`);
      if (!response.ok) throw new Error("Could not fetch experts.");
      const data = await response.json();
      setResult(data);
      setSelectedId(data.experts?.[0]?.person?.id || null);
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 px-6 py-6 text-slate-100">
      <header className="border-b border-slate-800 pb-5">
        <div className="text-sm font-medium uppercase tracking-wide text-cyan-300">Expert Finder</div>
        <h1 className="mt-1 text-3xl font-semibold">Find Project Experts</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">Rank people by tickets, PRs, reviews, and discussions connected to a project.</p>
      </header>
      <form onSubmit={handleSubmit} className="mt-6 flex gap-3 rounded-lg border border-slate-800 bg-slate-900 p-3">
        <input className="min-h-11 flex-1 rounded-md border border-slate-700 bg-slate-950 px-4 text-sm outline-none focus:border-cyan-400" value={project} onChange={(event) => setProject(event.target.value)} />
        <button className="rounded-md bg-cyan-400 px-5 text-sm font-semibold text-slate-950 disabled:opacity-60" disabled={loading}>{loading ? "Finding" : "Find Experts"}</button>
      </form>
      <div className="mt-3 flex flex-wrap gap-2">{["CheckoutFlow", "StockSync", "DeliveryTrack", "EchoMind"].map((item) => <button key={item} onClick={() => setProject(item)} className="rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300">{item}</button>)}</div>
      {error && <div className="mt-4 rounded-lg border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-200">{error}</div>}
      {result && (
        <div className="mt-6 grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            <div className="text-xs font-medium uppercase tracking-wide text-cyan-300">Ranked Results</div>
            <h2 className="mt-1 text-xl font-semibold">{result.project}</h2>
            <div className="mt-4 grid gap-3">{experts.map((expert, index) => <button key={expert.person.id} onClick={() => setSelectedId(expert.person.id)} className={`rounded-lg border p-4 text-left ${selected?.person.id === expert.person.id ? "border-cyan-400 bg-cyan-950/30" : "border-slate-800 bg-slate-950"}`}><div className="flex items-start justify-between"><div><div className="text-xs uppercase tracking-wide text-slate-500">Rank #{index + 1}</div><h3 className="mt-1 font-semibold">{expert.person.name}</h3><p className="mt-1 text-sm text-slate-400">{expert.person.role} · {expert.person.team}</p></div><Score value={expert.score} /></div><p className="mt-3 text-sm leading-6 text-slate-300">{expert.why}</p></button>)}</div>
          </section>
          <section className="rounded-lg border border-slate-800 bg-slate-900 p-5">
            {selected ? <><div className="text-xs font-medium uppercase tracking-wide text-cyan-300">Expert Profile</div><h2 className="mt-1 text-2xl font-semibold">{selected.person.name}</h2><p className="mt-1 text-sm text-slate-400">{selected.person.role} · {selected.person.team}</p><p className="mt-5 text-sm leading-7 text-slate-300">{selected.why}</p><h3 className="mt-6 text-sm font-semibold">Evidence</h3><div className="mt-3 grid gap-3">{selected.evidence.map((item) => <article key={`${item.type}-${item.id}`} className="rounded-md border border-slate-800 bg-slate-950 p-4"><div className="text-xs font-medium uppercase tracking-wide text-cyan-300">{item.type} {item.id}</div><h4 className="mt-1 font-semibold">{item.title}</h4><p className="mt-2 text-sm text-slate-400">{item.reason}</p></article>)}</div></> : <p className="text-sm text-slate-400">Run a search to see experts.</p>}
          </section>
        </div>
      )}
    </div>
  );
}

function Score({ value }) {
  return <div className="flex h-12 w-12 items-center justify-center rounded-md border border-cyan-400/40 bg-cyan-950 font-bold text-cyan-200">{value}</div>;
}
