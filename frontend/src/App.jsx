import DecisionExplorer from "./pages/DecisionExplorer.jsx";
import ExpertFinder from "./pages/ExpertFinder.jsx";
import KnowledgeGraph from "./pages/KnowledgeGraph.jsx";
import TimelineExplorer from "./pages/TimelineExplorer.jsx";
import { useState } from "react";

const pages = [
  ["decision", "Decision Explorer"],
  ["expert", "Expert Finder"],
  ["timeline", "Timeline Explorer"],
  ["graph", "Knowledge Graph"]
];

export default function App() {
  const [activePage, setActivePage] = useState("decision");

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="grid min-h-screen lg:grid-cols-[240px_1fr]">
        <aside className="border-b border-slate-800 bg-slate-950 px-4 py-4 lg:border-b-0 lg:border-r">
          <div className="text-xl font-semibold">EchoMind</div>
          <div className="mt-1 text-xs uppercase tracking-wide text-cyan-300">FreshCart demo</div>
          <nav className="mt-6 flex gap-2 overflow-x-auto lg:flex-col">
            {pages.map(([id, label]) => (
              <button
                key={id}
                onClick={() => setActivePage(id)}
                className={`rounded-md px-3 py-2 text-left text-sm transition ${
                  activePage === id
                    ? "bg-cyan-400 text-slate-950"
                    : "text-slate-300 hover:bg-slate-900"
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
        </aside>
        <main className="min-w-0">
          {activePage === "decision" && <DecisionExplorer />}
          {activePage === "expert" && <ExpertFinder />}
          {activePage === "timeline" && <TimelineExplorer />}
          {activePage === "graph" && <KnowledgeGraph />}
        </main>
      </div>
    </div>
  );
}
