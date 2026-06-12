"use client"

import { useEffect, useState } from "react"

export function EdgePill({ onExpand }: { onExpand: () => void }) {
  const [time, setTime] = useState("")
  const [blink, setBlink] = useState(true)

  useEffect(() => {
    const tick = () => {
      const d = new Date()
      const pad = (n: number) => n.toString().padStart(2, "0")
      setTime(`${pad(d.getHours())}:${pad(d.getMinutes())}`)
    }
    tick()
    const t = setInterval(tick, 1000 * 10)
    const b = setInterval(() => setBlink((v) => !v), 600)
    return () => {
      clearInterval(t)
      clearInterval(b)
    }
  }, [])

  return (
    <button
      type="button"
      onClick={onExpand}
      aria-label="Expand assistant overlay"
      className="fixed right-0 top-1/2 z-50 flex -translate-y-1/2 flex-col items-center gap-2.5 border border-neutral-700 bg-neutral-950/80 px-2.5 py-4 font-mono text-neutral-100 backdrop-blur-md transition-colors hover:border-neutral-500"
      style={{
        width: 48,
        backgroundImage: "radial-gradient(#ffffff20 1px, transparent 1px)",
        backgroundSize: "10px 10px",
      }}
    >
      <span className="text-base text-green-400">{blink ? ">" : "\u00A0"}</span>
      <span
        className="text-xs tracking-widest text-neutral-400"
        style={{ writingMode: "vertical-rl" }}
      >
        {time}
      </span>
    </button>
  )
}
