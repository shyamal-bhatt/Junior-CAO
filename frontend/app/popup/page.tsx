"use client"

import { MatrixOverlay } from "@/components/matrix-overlay"

export default function PopupPage() {
  return (
    <main className="relative h-screen w-screen overflow-hidden bg-neutral-950">
      <MatrixOverlay isPopup={true} />
    </main>
  )
}
