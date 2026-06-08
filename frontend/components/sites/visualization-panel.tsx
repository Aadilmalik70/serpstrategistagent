"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetcher(url: string) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch");
  return res.json();
}

interface VisualizationProps {
  siteId: string;
}

interface GraphNode {
  id: string;
  path: string;
  title: string;
  status_code: number | null;
  internal_links_count: number;
  inlinks_count: number;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface GraphEdge {
  source: string;
  target: string;
}

export default function VisualizationPanel({ siteId }: VisualizationProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: GraphNode } | null>(null);
  const nodesRef = useRef<GraphNode[]>([]);
  const edgesRef = useRef<GraphEdge[]>([]);
  const animRef = useRef<number>(0);

  const { data, isLoading } = useSWR(
    `${API_URL}/sites/${siteId}/visualization`,
    fetcher
  );

  useEffect(() => {
    if (!data || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.offsetWidth;
    const height = canvas.offsetHeight;
    canvas.width = width;
    canvas.height = height;

    // Initialize positions
    const nodes: GraphNode[] = data.nodes.map((n: GraphNode) => ({
      ...n,
      x: Math.random() * width,
      y: Math.random() * height,
      vx: 0,
      vy: 0,
    }));
    const edges: GraphEdge[] = data.edges;
    nodesRef.current = nodes;
    edgesRef.current = edges;

    const nodeMap = new Map(nodes.map((n) => [n.id, n]));

    // Simple force-directed layout
    let iterations = 0;
    function simulate() {
      if (iterations > 200) {
        draw();
        return;
      }
      iterations++;

      // Repulsion between all nodes
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[j].x! - nodes[i].x!;
          const dy = nodes[j].y! - nodes[i].y!;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const force = 800 / (dist * dist);
          nodes[i].vx! -= (dx / dist) * force;
          nodes[i].vy! -= (dy / dist) * force;
          nodes[j].vx! += (dx / dist) * force;
          nodes[j].vy! += (dy / dist) * force;
        }
      }

      // Attraction along edges
      for (const edge of edges) {
        const s = nodeMap.get(edge.source);
        const t = nodeMap.get(edge.target);
        if (!s || !t) continue;
        const dx = t.x! - s.x!;
        const dy = t.y! - s.y!;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const force = dist * 0.01;
        s.vx! += (dx / dist) * force;
        s.vy! += (dy / dist) * force;
        t.vx! -= (dx / dist) * force;
        t.vy! -= (dy / dist) * force;
      }

      // Center gravity
      for (const node of nodes) {
        node.vx! += (width / 2 - node.x!) * 0.001;
        node.vy! += (height / 2 - node.y!) * 0.001;
        node.x! += node.vx! * 0.5;
        node.y! += node.vy! * 0.5;
        node.vx! *= 0.9;
        node.vy! *= 0.9;
        // Bounds
        node.x = Math.max(20, Math.min(width - 20, node.x!));
        node.y = Math.max(20, Math.min(height - 20, node.y!));
      }

      draw();
      animRef.current = requestAnimationFrame(simulate);
    }

    function draw() {
      if (!ctx) return;
      ctx.clearRect(0, 0, width, height);

      // Draw edges
      ctx.strokeStyle = "#e5e7eb";
      ctx.lineWidth = 0.5;
      for (const edge of edges) {
        const s = nodeMap.get(edge.source);
        const t = nodeMap.get(edge.target);
        if (!s || !t) continue;
        ctx.beginPath();
        ctx.moveTo(s.x!, s.y!);
        ctx.lineTo(t.x!, t.y!);
        ctx.stroke();
      }

      // Draw nodes
      for (const node of nodes) {
        const size = Math.max(4, Math.min(12, node.inlinks_count * 2 + 4));
        const color =
          node.status_code === 200
            ? "#10b981"
            : node.status_code && node.status_code >= 400
              ? "#ef4444"
              : "#6b7280";
        ctx.beginPath();
        ctx.arc(node.x!, node.y!, size, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }

    simulate();

    return () => {
      cancelAnimationFrame(animRef.current);
    };
  }, [data]);

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const found = nodesRef.current.find((n) => {
      const dx = n.x! - mx;
      const dy = n.y! - my;
      return Math.sqrt(dx * dx + dy * dy) < 12;
    });

    if (found) {
      setTooltip({ x: mx, y: my, node: found });
    } else {
      setTooltip(null);
    }
  }

  if (isLoading) {
    return <div className="h-96 bg-gray-200 rounded-lg animate-pulse" />;
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        No visualization data. Run a crawl first.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">Site Structure Visualization</h3>
          <p className="text-sm text-gray-500">
            {data.nodes.length} pages, {data.edges.length} internal links
          </p>
        </div>
        <div className="flex gap-3 text-xs">
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-green-500 inline-block" /> 2xx
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-red-500 inline-block" /> 4xx/5xx
          </span>
          <span className="flex items-center gap-1">
            <span className="w-3 h-3 rounded-full bg-gray-500 inline-block" /> Other
          </span>
        </div>
      </div>

      <div className="relative bg-white rounded-lg border border-gray-200 overflow-hidden">
        <canvas
          ref={canvasRef}
          className="w-full h-125"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setTooltip(null)}
        />
        {tooltip && (
          <div
            className="absolute bg-gray-900 text-white text-xs rounded px-3 py-2 pointer-events-none shadow-lg"
            style={{ left: tooltip.x + 10, top: tooltip.y - 40 }}
          >
            <div className="font-medium">{tooltip.node.path}</div>
            <div className="text-gray-300 mt-0.5">
              {tooltip.node.internal_links_count} outlinks · {tooltip.node.inlinks_count} inlinks
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
