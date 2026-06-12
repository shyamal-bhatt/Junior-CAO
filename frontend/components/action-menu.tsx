"use client"

import { Database, FileText, ListPlus } from "lucide-react"

const ACTIONS = [
  { id: "search", label: "SEARCH DB", icon: Database },
  { id: "summarize", label: "SUMMARIZE", icon: FileText },
  { id: "task", label: "CREATE TASK", icon: ListPlus },
]

export function ActionMenu({ onAction }: { onAction: (id: string) => void }) {
  return (
    <div
      className="absolute left-full top-16 ml-2 w-52 border border-neutral-700 bg-neutral-950/85 p-2.5 font-mono backdrop-blur-md"
      style={{
        backgroundImage: "radial-gradient(#ffffff20 1px, transparent 1px)",
        backgroundSize: "10px 10px",
      }}
    >
      <div className="mb-2 border-b border-dashed border-neutral-700 pb-1.5 text-xs tracking-widest text-neutral-500">
        ACTIONS
      </div>
      <div className="flex flex-col gap-2">
        {ACTIONS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => onAction(id)}
            className="flex items-center gap-2 border border-neutral-700 bg-neutral-900 px-2.5 py-2.5 text-left text-sm tracking-wider text-neutral-100 transition-colors hover:border-green-400 hover:text-green-400"
          >
            <Icon className="h-4 w-4 shrink-0" strokeWidth={1.5} />
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}
