"use client"

import { useEffect, useState } from "react"

// Blocky, 8-bit style vertical bar waveform. Bars snap between a small set of
// discrete heights so it reads as crude/jagged rather than smooth.
const BAR_COUNT = 28
const STEPS = [10, 25, 40, 60, 80, 100]

function randomBars() {
  return Array.from({ length: BAR_COUNT }, () => STEPS[Math.floor(Math.random() * STEPS.length)])
}

export function VoiceWaveform() {
  const [bars, setBars] = useState<number[]>(() => randomBars())

  useEffect(() => {
    const id = setInterval(() => setBars(randomBars()), 120)
    return () => clearInterval(id)
  }, [])

  return (
    <div
      className="flex h-9 flex-1 items-center justify-center gap-[2px] border border-neutral-700 bg-black px-2"
      role="img"
      aria-label="Voice input waveform, listening"
    >
      {bars.map((h, i) => (
        <span
          key={i}
          className="w-[3px] bg-green-400"
          style={{ height: `${h}%` }}
        />
      ))}
    </div>
  )
}
