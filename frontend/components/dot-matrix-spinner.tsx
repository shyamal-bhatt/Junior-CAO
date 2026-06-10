"use client"

import { useEffect, useState } from "react"

// A mechanical, jagged 3x3 dot-fill loader. Dots fill/erase in a fixed
// sequence so it feels like a stepping print-head, not a smooth spinner.
const SEQUENCE = [
  [0],
  [0, 1],
  [0, 1, 2],
  [0, 1, 2, 5],
  [0, 1, 2, 5, 8],
  [1, 2, 5, 8, 7],
  [2, 5, 8, 7, 6],
  [5, 8, 7, 6, 3],
  [8, 7, 6, 3, 4],
  [7, 6, 3, 4],
  [6, 3, 4],
  [3, 4],
  [4],
  [],
]

export function DotMatrixSpinner({ label = "PROCESSING" }: { label?: string }) {
  const [step, setStep] = useState(0)

  useEffect(() => {
    const id = setInterval(() => {
      setStep((s) => (s + 1) % SEQUENCE.length)
    }, 110)
    return () => clearInterval(id)
  }, [])

  const active = SEQUENCE[step]

  return (
    <div className="flex items-center gap-2 font-mono text-xs text-neutral-400">
      <div
        className="grid grid-cols-3 gap-[2px]"
        role="status"
        aria-label="Assistant is generating a response"
      >
        {Array.from({ length: 9 }).map((_, i) => (
          <span
            key={i}
            className={
              active.includes(i)
                ? "h-[5px] w-[5px] bg-green-400"
                : "h-[5px] w-[5px] bg-neutral-700"
            }
          />
        ))}
      </div>
      <span className="tracking-widest">
        {label}
        <span className="inline-block w-6 text-left">
          {".".repeat((step % 3) + 1)}
        </span>
      </span>
    </div>
  )
}
