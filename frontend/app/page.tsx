"use client"

import { MatrixOverlay } from "@/components/matrix-overlay"

export default function Page() {
  return (
    <main className="relative min-h-svh overflow-hidden bg-neutral-950">
      {/* Faux desktop backdrop so the floating PiP overlay reads as an overlay */}
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          backgroundImage:
            "linear-gradient(#ffffff0a 1px, transparent 1px), linear-gradient(90deg, #ffffff0a 1px, transparent 1px)",
          backgroundSize: "32px 32px",
        }}
        aria-hidden="true"
      />
      <MatrixOverlay />
    </main>
  )
}
