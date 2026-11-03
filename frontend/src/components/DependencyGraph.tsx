// The dependency diagram: every step as a box, with arrows showing what must be done before what.
//
// It reads like a timeline from left to right. Steps with nothing before them go in the first column; every other
// step goes one column to the right of the last step it's waiting on. That way, every arrow points to the right.
// Colours: green = done, blue = can start now, orange = waiting on an earlier step.

import type { GraphData } from "../lib/types";

const BOX_W = 190;
const BOX_H = 48;
const COL_GAP = 56;
const ROW_GAP = 14;
const PAD = 12;

const COLOURS = {
  done: { fill: "#dcfce7", stroke: "#22c55e" },
  todo: { fill: "#dbeafe", stroke: "#3b82f6" },
  waiting: { fill: "#ffedd5", stroke: "#f97316" },
};

// Split a step name over at most two lines of about 26 characters, adding "…" if it's longer.
function wrap(name: string, width = 26): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of name.split(" ")) {
    if ((line + " " + word).trim().length > width && line) {
      lines.push(line);
      line = word;
    } else {
      line = (line + " " + word).trim();
    }
  }
  if (line) lines.push(line);
  return lines.length > 2 ? [lines[0], lines[1] + "…"] : lines;
}

export function DependencyGraph({ graph }: { graph: GraphData }) {
  const ids = new Set(graph.nodes.map((n) => n.id));
  // For each step, the steps that must come before it (only those shown in this diagram).
  const before = new Map<string, string[]>();
  for (const e of graph.edges) {
    if (ids.has(e.from) && ids.has(e.to)) before.set(e.to, [...(before.get(e.to) ?? []), e.from]);
  }

  // Work out each step's column: one more than the furthest step it's waiting on. `visiting` guards against a
  // loop in the data (a step waiting on itself), which would otherwise go round forever.
  const column = new Map<string, number>();
  const visiting = new Set<string>();
  const columnOf = (id: string): number => {
    if (column.has(id)) return column.get(id)!;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const prior = before.get(id) ?? [];
    const col = prior.length ? Math.max(...prior.map(columnOf)) + 1 : 0;
    visiting.delete(id);
    column.set(id, col);
    return col;
  };

  // Place each box: its column decides how far right, its order within the column decides how far down.
  const rowsUsed = new Map<number, number>();
  const position = new Map<string, { x: number; y: number }>();
  const ordered = [...graph.nodes].sort((a, b) => columnOf(a.id) - columnOf(b.id) || a.name.localeCompare(b.name));
  for (const node of ordered) {
    const col = columnOf(node.id);
    const row = rowsUsed.get(col) ?? 0;
    rowsUsed.set(col, row + 1);
    position.set(node.id, { x: PAD + col * (BOX_W + COL_GAP), y: PAD + row * (BOX_H + ROW_GAP) });
  }
  const columns = Math.max(0, ...[...column.values()]) + 1;
  const tallest = Math.max(1, ...[...rowsUsed.values()]);
  const width = PAD * 2 + columns * BOX_W + (columns - 1) * COL_GAP;
  const height = PAD * 2 + tallest * BOX_H + (tallest - 1) * ROW_GAP;

  return (
    <div>
      <div className="max-h-[420px] overflow-auto rounded-xl border border-slate-200 bg-white">
        <svg width={width} height={height} role="img" aria-label="Diagram of the steps and their order">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8" />
            </marker>
          </defs>
          {/* The arrows, drawn first so the boxes sit on top of them. Each one curves from the right edge of the
              earlier step to the left edge of the later one. */}
          {graph.edges.map((e) => {
            const a = position.get(e.from);
            const b = position.get(e.to);
            if (!a || !b) return null;
            const x1 = a.x + BOX_W;
            const y1 = a.y + BOX_H / 2;
            const x2 = b.x;
            const y2 = b.y + BOX_H / 2;
            const bend = Math.max(24, (x2 - x1) / 2);
            return (
              <path
                key={`${e.from}-${e.to}`}
                d={`M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`}
                fill="none"
                stroke="#94a3b8"
                strokeWidth="1.3"
                markerEnd="url(#arrow)"
              />
            );
          })}
          {/* The step boxes. Only the step's name is shown; its internal code is used just to connect arrows. */}
          {graph.nodes.map((n) => {
            const p = position.get(n.id)!;
            const c = COLOURS[n.group] ?? COLOURS.waiting;
            const lines = wrap(n.name);
            return (
              <g key={n.id}>
                <title>{n.name}</title>
                <rect x={p.x} y={p.y} width={BOX_W} height={BOX_H} rx="9" fill={c.fill} stroke={c.stroke} />
                <text x={p.x + BOX_W / 2} y={p.y + BOX_H / 2 - (lines.length - 1) * 7} textAnchor="middle"
                      dominantBaseline="middle" fontSize="11.5" fill="#0f172a">
                  {lines.map((line, i) => (
                    <tspan key={i} x={p.x + BOX_W / 2} dy={i === 0 ? 0 : 14}>{line}</tspan>
                  ))}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        <span><span className="mr-1 inline-block size-2.5 rounded-sm bg-green-400" />Done</span>
        <span><span className="mr-1 inline-block size-2.5 rounded-sm bg-blue-400" />Ready now</span>
        <span><span className="mr-1 inline-block size-2.5 rounded-sm bg-orange-400" />Waiting on an earlier step</span>
      </p>
    </div>
  );
}
