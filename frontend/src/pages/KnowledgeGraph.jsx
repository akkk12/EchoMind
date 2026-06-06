import { useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";

const graph = {
  nodes: [
    { id: "person-maya-rao", name: "Maya Rao", type: "Person", subtitle: "VP of Engineering" },
    { id: "person-ethan-brooks", name: "Ethan Brooks", type: "Person", subtitle: "Staff Backend Engineer" },
    { id: "person-priya-shah", name: "Priya Shah", type: "Person", subtitle: "Senior Data Engineer" },
    { id: "person-lucas-chen", name: "Lucas Chen", type: "Person", subtitle: "Site Reliability Engineer" },
    { id: "project-checkoutflow", name: "CheckoutFlow", type: "Project", subtitle: "Reliable ordering" },
    { id: "project-stocksync", name: "StockSync", type: "Project", subtitle: "Inventory accuracy" },
    { id: "AR-001", name: "Split Checkout Into Order Services", type: "Decision", subtitle: "Separate checkout responsibilities" },
    { id: "AR-002", name: "Order Lifecycle Events", type: "Decision", subtitle: "Use events" },
    { id: "AR-005", name: "Delivery Notification Idempotency", type: "Decision", subtitle: "Deduplicate retries" },
    { id: "INC-001", name: "Holiday Checkout Freeze", type: "Incident", subtitle: "Checkout unavailable" },
    { id: "INC-002", name: "Duplicate Delivery Notifications", type: "Incident", subtitle: "Repeated messages" },
    { id: "review-AR-001", name: "CheckoutFlow Review", type: "ArchitectureReview", subtitle: "Architecture review" },
    { id: "review-AR-005", name: "Idempotency Review", type: "ArchitectureReview", subtitle: "Architecture review" }
  ],
  links: [
    { source: "person-maya-rao", target: "AR-001", type: "PARTICIPATED_IN" },
    { source: "person-ethan-brooks", target: "AR-001", type: "PARTICIPATED_IN" },
    { source: "person-lucas-chen", target: "AR-001", type: "PARTICIPATED_IN" },
    { source: "person-ethan-brooks", target: "AR-002", type: "PARTICIPATED_IN" },
    { source: "person-priya-shah", target: "AR-002", type: "PARTICIPATED_IN" },
    { source: "person-ethan-brooks", target: "AR-005", type: "PARTICIPATED_IN" },
    { source: "INC-001", target: "AR-001", type: "LED_TO" },
    { source: "INC-001", target: "AR-002", type: "LED_TO" },
    { source: "INC-002", target: "AR-005", type: "LED_TO" },
    { source: "AR-001", target: "project-checkoutflow", type: "AFFECTS" },
    { source: "AR-002", target: "project-checkoutflow", type: "AFFECTS" },
    { source: "AR-002", target: "project-stocksync", type: "AFFECTS" },
    { source: "AR-005", target: "project-checkoutflow", type: "AFFECTS" },
    { source: "review-AR-001", target: "AR-001", type: "SUPPORTS" },
    { source: "review-AR-005", target: "AR-005", type: "SUPPORTS" }
  ]
};

const colors = { Person: "#94a3b8", Project: "#14b8a6", Decision: "#22d3ee", Incident: "#f87171", ArchitectureReview: "#a78bfa" };

export default function KnowledgeGraph() {
  const graphRef = useRef(null);
  const [selected, setSelected] = useState(null);
  const [activeTypes, setActiveTypes] = useState(new Set(Object.keys(colors)));
  const data = useMemo(() => {
    const nodes = graph.nodes.filter((node) => activeTypes.has(node.type));
    const ids = new Set(nodes.map((node) => node.id));
    return { nodes, links: graph.links.filter((link) => ids.has(link.source) && ids.has(link.target)) };
  }, [activeTypes]);

  function toggle(type) {
    setActiveTypes((current) => {
      const next = new Set(current);
      next.has(type) ? next.delete(type) : next.add(type);
      return next;
    });
  }

  return (
    <div className="h-screen bg-slate-950 px-6 py-6 text-slate-100">
      <header className="flex items-start justify-between border-b border-slate-800 pb-5">
        <div><div className="text-sm font-medium uppercase tracking-wide text-cyan-300">Knowledge Graph</div><h1 className="mt-1 text-3xl font-semibold">FreshCart Memory Graph</h1><p className="mt-2 text-sm text-slate-400">Mock graph data showing people, projects, decisions, incidents, and reviews.</p></div>
        <button onClick={() => graphRef.current?.zoomToFit(500, 60)} className="rounded-md bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950">Reset View</button>
      </header>
      <section className="mt-4 grid h-[calc(100vh-150px)] gap-4 lg:grid-cols-[1fr_320px]">
        <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-900">
          <ForceGraph2D ref={graphRef} graphData={data} backgroundColor="#0f172a" linkColor={() => "rgba(148, 163, 184, 0.35)"} nodeLabel={(node) => `${node.type}: ${node.name}`} onNodeClick={setSelected} onEngineStop={() => graphRef.current?.zoomToFit(500, 60)} nodeCanvasObject={(node, ctx, scale) => { const radius = node.type === "Project" ? 8 : 6; ctx.beginPath(); ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI); ctx.fillStyle = colors[node.type] || "#e2e8f0"; ctx.fill(); if (selected?.id === node.id) { ctx.strokeStyle = "#f8fafc"; ctx.lineWidth = 1.5 / scale; ctx.stroke(); } ctx.font = `${Math.max(10 / scale, 3)}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.fillStyle = "#e5e7eb"; ctx.fillText(node.name, node.x, node.y + radius + 3); }} />
        </div>
        <aside className="space-y-4">
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4"><h2 className="text-sm font-semibold">Node Types</h2><div className="mt-3 grid gap-2">{Object.keys(colors).map((type) => <button key={type} onClick={() => toggle(type)} className="flex items-center justify-between rounded-md border border-slate-800 bg-slate-950 px-3 py-2 text-sm"><span><span className="mr-2 inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colors[type] }} />{type}</span><span className="text-xs text-slate-500">{activeTypes.has(type) ? "shown" : "hidden"}</span></button>)}</div></div>
          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4"><h2 className="text-sm font-semibold">Selected Node</h2>{selected ? <div className="mt-3"><div className="text-xs uppercase tracking-wide text-cyan-300">{selected.type}</div><h3 className="mt-1 text-lg font-semibold">{selected.name}</h3><p className="mt-2 text-sm text-slate-400">{selected.subtitle}</p><div className="mt-4 rounded-md border border-slate-800 bg-slate-950 p-3 text-sm text-slate-300">{selected.id}</div></div> : <p className="mt-3 text-sm text-slate-400">Select a node to inspect it.</p>}</div>
        </aside>
      </section>
    </div>
  );
}
