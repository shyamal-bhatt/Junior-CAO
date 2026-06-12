"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  Lasso,
  Minus,
  X,
  Maximize2,
  Mic,
  CornerDownLeft,
} from "lucide-react"
import { DotMatrixSpinner } from "@/components/dot-matrix-spinner"
import { VoiceWaveform } from "@/components/voice-waveform"
import { ActionMenu } from "@/components/action-menu"
import { EdgePill } from "@/components/edge-pill"

type Message = {
  id: number
  role: "user" | "assistant"
  text: string
}

type Mode = "full" | "floating" | "docked"

const INITIAL_MESSAGES: Message[] = []

const dotPattern = {
  backgroundImage: "radial-gradient(#ffffff20 1px, transparent 1px)",
  backgroundSize: "10px 10px",
}

export function MatrixOverlay() {
  const [mode, setMode] = useState<Mode>("full")
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const [messages, setMessages] = useState<Message[]>(INITIAL_MESSAGES)
  const [sessions, setSessions] = useState<{ id: string; title: string }[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [grabbed, setGrabbed] = useState(false)
  const [listening, setListening] = useState(false)

  const dragState = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(
    null,
  )
  const logRef = useRef<HTMLDivElement>(null)

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch("http://localhost:8000/api/v1/chat/sessions")
      if (res.ok) {
        const data = await res.json()
        setSessions(data)
      }
    } catch (err) {
      console.error("Failed to fetch sessions:", err)
    }
  }, [])

  const loadSessionMessages = useCallback(async (sessionId: string) => {
    setLoading(true)
    try {
      const res = await fetch(`http://localhost:8000/api/v1/chat/sessions/${sessionId}/messages`)
      if (res.ok) {
        const data = await res.json()
        const uiMsgs: Message[] = data.map((m: any, idx: number) => ({
          id: m.id || Date.now() + idx,
          role: m.role,
          text: m.content,
        }))
        setMessages(uiMsgs)
      }
    } catch (err) {
      console.error("Failed to load session messages:", err)
    } finally {
      setLoading(false)
    }
  }, [])

  const startNewChat = useCallback(() => {
    setActiveSessionId(null)
    setMessages([])
  }, [])

  const selectSession = useCallback((sessionId: string) => {
    setActiveSessionId(sessionId)
    loadSessionMessages(sessionId)
  }, [loadSessionMessages])

  const deleteSession = useCallback(async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      const res = await fetch(`http://localhost:8000/api/v1/chat/sessions/${sessionId}`, {
        method: "DELETE",
      })
      if (res.ok) {
        if (activeSessionId === sessionId) {
          startNewChat()
        }
        fetchSessions()
      }
    } catch (err) {
      console.error("Failed to delete session:", err)
    }
  }, [activeSessionId, fetchSessions, startNewChat])

  // Center the floating window the first time it is opened.
  useEffect(() => {
    if (mode === "floating" && pos.x === 0 && pos.y === 0) {
      setPos({
        x: Math.max(16, window.innerWidth / 2 - 200),
        y: Math.max(16, window.innerHeight / 2 - 260),
      })
    }
  }, [mode, pos.x, pos.y])

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [messages, loading, mode])

  // Load sessions on mount and set latest as active if available
  useEffect(() => {
    const init = async () => {
      try {
        const res = await fetch("http://localhost:8000/api/v1/chat/sessions")
        if (res.ok) {
          const data = await res.json()
          setSessions(data)
          if (data.length > 0) {
            setActiveSessionId(data[0].id)
            setLoading(true)
            const msgRes = await fetch(`http://localhost:8000/api/v1/chat/sessions/${data[0].id}/messages`)
            if (msgRes.ok) {
              const msgData = await msgRes.json()
              const uiMsgs: Message[] = msgData.map((m: any, idx: number) => ({
                id: m.id || Date.now() + idx,
                role: m.role,
                text: m.content,
              }))
              setMessages(uiMsgs)
            }
            setLoading(false)
          }
        }
      } catch (err) {
        console.error("Failed initializing chat sessions:", err)
        setLoading(false)
      }
    }
    init()
  }, [])

  const onPointerMove = useCallback((e: PointerEvent) => {
    if (!dragState.current) return
    const { startX, startY, baseX, baseY } = dragState.current
    setPos({
      x: baseX + (e.clientX - startX),
      y: baseY + (e.clientY - startY),
    })
  }, [])

  const onPointerUp = useCallback(() => {
    dragState.current = null
    window.removeEventListener("pointermove", onPointerMove)
    window.removeEventListener("pointerup", onPointerUp)
  }, [onPointerMove])

  const startDrag = (e: React.PointerEvent) => {
    dragState.current = {
      startX: e.clientX,
      startY: e.clientY,
      baseX: pos.x,
      baseY: pos.y,
    }
    window.addEventListener("pointermove", onPointerMove)
    window.addEventListener("pointerup", onPointerUp)
  }

  const send = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    const userMsg: Message = { id: Date.now(), role: "user", text: trimmed }
    const nextMessages = [...messages, userMsg]
    setMessages(nextMessages)
    setInput("")
    setLoading(true)

    try {
      const formattedMessages = nextMessages.map((m) => ({
        role: m.role,
        content: m.text,
      }))
      const response = await fetch("http://localhost:8000/api/v1/chat/agent", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          messages: formattedMessages,
          model: "openai/gpt-4o-mini",
          stream: false,
          context: grabbed ? "Organization/Linkmate" : null,
          session_id: activeSessionId,
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()
      setMessages((m) => [
        ...m,
        {
          id: Date.now(),
          role: "assistant",
          text: data.reply,
        },
      ])

      if (data.session_id) {
        setActiveSessionId(data.session_id)
      }
      fetchSessions()
    } catch (error) {
      console.error("Failed to send message to backend:", error)
      setMessages((m) => [
        ...m,
        {
          id: Date.now(),
          role: "assistant",
          text: "> ERROR: Failed to communicate with backend.",
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleAction = async (id: string) => {
    setLoading(true)
    try {
      const formattedMessages = messages.map((m) => ({
        role: m.role,
        content: m.text,
      }))
      const response = await fetch("http://localhost:8000/api/v1/chat/action", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          action: id,
          context: grabbed ? "Organization/Linkmate" : null,
          messages: formattedMessages,
          model: "openai/gpt-4o-mini",
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()
      setMessages((m) => [
        ...m,
        {
          id: Date.now(),
          role: "assistant",
          text: data.result,
        },
      ])
    } catch (error) {
      console.error("Failed to run action on backend:", error)
      setMessages((m) => [
        ...m,
        {
          id: Date.now(),
          role: "assistant",
          text: `> ERROR: Failed to execute action [${id.toUpperCase()}].`,
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  // ── Docked: the slim edge pill ────────────────────────────────────────────
  if (mode === "docked") {
    return <EdgePill onExpand={() => setMode("floating")} />
  }

  const isFull = mode === "full"

  // Shared chat surface (log + input) reused by both full and floating modes.
  const chatSurface = (
    <>
      {/* Grab & Inject context bar */}
      <button
        type="button"
        onClick={() => setGrabbed((g) => !g)}
        className="flex w-full items-center gap-2 border-b border-neutral-800 bg-black/40 px-3 py-2 text-left"
        aria-pressed={grabbed}
      >
        <Lasso
          className={grabbed ? "h-3.5 w-3.5 text-green-400" : "h-3.5 w-3.5 text-neutral-500"}
          strokeWidth={1.5}
        />
        <span className="text-[10px] tracking-widest">
          {grabbed ? (
            <span className="text-green-400">CONTEXT CAPTURED: [Organization/Linkmate]</span>
          ) : (
            <span className="text-neutral-500">DOCKING STATUS: IDLE</span>
          )}
        </span>
      </button>

      {/* Chat log */}
      <div ref={logRef} className="flex-1 overflow-y-auto px-3 py-3" style={dotPattern}>
        <div className="mx-auto flex max-w-3xl flex-col gap-3">
          {messages.map((msg) =>
            msg.role === "user" ? (
              <div key={msg.id} className="flex justify-end">
                <div className="max-w-[80%] border border-neutral-700 bg-neutral-800 px-2 py-1.5 text-xs leading-relaxed text-neutral-100">
                  {msg.text}
                </div>
              </div>
            ) : (
              <div key={msg.id} className="flex justify-start">
                <div className="max-w-[85%] border border-neutral-800 bg-neutral-950/60 px-2 py-1.5 text-xs leading-relaxed text-green-400">
                  {msg.text}
                </div>
              </div>
            ),
          )}
          {loading && (
            <div className="flex justify-start">
              <div className="border border-neutral-800 bg-neutral-950/60 px-2 py-1.5">
                <DotMatrixSpinner />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Input area */}
      <div className="flex items-center gap-1.5 border-t border-dashed border-neutral-700 p-2">
        <div className="mx-auto flex w-full max-w-3xl items-center gap-1.5">
          {listening ? (
            <VoiceWaveform />
          ) : (
            <div className="flex flex-1 items-center border border-neutral-700 bg-black px-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") send(input)
                }}
                placeholder="> ASK JUNIOR CAO..."
                aria-label="Message input"
                className="h-9 flex-1 bg-transparent text-xs text-neutral-100 placeholder:text-neutral-500 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => send(input)}
                aria-label="Send"
                className="text-neutral-500 hover:text-neutral-100"
              >
                <CornerDownLeft className="h-3.5 w-3.5" strokeWidth={1.5} />
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={() => setListening((v) => !v)}
            aria-label={listening ? "Stop voice input" : "Start voice input"}
            aria-pressed={listening}
            className={
              listening
                ? "flex h-9 w-9 items-center justify-center border border-green-400 bg-green-400/10 text-green-400"
                : "flex h-9 w-9 items-center justify-center border border-neutral-700 bg-black text-neutral-400 hover:border-neutral-400 hover:text-neutral-100"
            }
          >
            <Mic className="h-4 w-4" strokeWidth={1.5} />
          </button>
        </div>
      </div>
    </>
  )

  // ── Full: full-screen chat interface with the Actions panel on the side ────
  if (isFull) {
    return (
      <div className="fixed inset-0 z-40 flex font-mono text-neutral-100">
        {/* Sessions side panel */}
        <aside
          className="hidden w-64 shrink-0 flex-col border-r border-neutral-700 bg-neutral-950/85 p-3 md:flex"
          style={dotPattern}
        >
          <div className="mb-3 border-b border-dashed border-neutral-700 pb-2 flex justify-between items-center text-[10px] tracking-widest text-neutral-500">
            <span>SESSIONS</span>
            <button
              onClick={startNewChat}
              className="text-[9px] border border-neutral-700 px-1.5 py-0.5 bg-neutral-900 text-neutral-400 hover:border-green-400 hover:text-green-400"
            >
              + NEW CHAT
            </button>
          </div>
          <SessionPanel
            sessions={sessions}
            activeSessionId={activeSessionId}
            onSelectSession={selectSession}
            onDeleteSession={deleteSession}
          />
        </aside>

        {/* Main chat column */}
        <div className="flex min-w-0 flex-1 flex-col bg-neutral-950" style={dotPattern}>
          {/* Title bar */}
          <div className="flex items-center justify-between border-b border-dashed border-neutral-700 px-3 py-2">
            <span className="text-[10px] tracking-widest text-neutral-500">
              JUNIOR CAO
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setMode("floating")}
                aria-label="Minimize to floating window"
                className="flex h-5 w-5 items-center justify-center border border-neutral-700 text-neutral-400 hover:border-neutral-400 hover:text-neutral-100"
              >
                <Minus className="h-3 w-3" strokeWidth={1.5} />
              </button>
            </div>
          </div>
          {chatSurface}
        </div>

        {/* Actions side panel */}
        <aside
          className="hidden w-64 shrink-0 flex-col border-l border-neutral-700 bg-neutral-950/85 p-3 md:flex"
          style={dotPattern}
        >
          <div className="mb-3 border-b border-dashed border-neutral-700 pb-2 text-[10px] tracking-widest text-neutral-500">
            ACTIONS
          </div>
          <ActionPanel onAction={handleAction} />
        </aside>
      </div>
    )
  }

  // ── Floating: draggable PiP window ─────────────────────────────────────────
  return (
    <div
      className="fixed z-40 flex h-[520px] w-[400px] select-none flex-col border border-neutral-700 bg-neutral-950/80 font-mono text-neutral-100 backdrop-blur-md"
      style={{
        left: pos.x,
        top: pos.y,
        boxShadow: "6px 6px 0 0 #000",
        ...dotPattern,
      }}
    >
      {grabbed && <ActionMenu onAction={handleAction} />}

      {/* Title bar */}
      <div className="flex items-center justify-between border-b border-dashed border-neutral-700 px-2 py-1.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] tracking-widest text-neutral-500">JUNIOR CAO</span>
          <button
            onClick={startNewChat}
            className="text-[9px] border border-neutral-700 px-1.5 py-0.5 bg-neutral-900 text-neutral-400 hover:border-green-400 hover:text-green-400"
            title="Start new chat session"
          >
            + NEW
          </button>
        </div>
        <div
          onPointerDown={startDrag}
          className="mx-2 flex h-4 flex-1 cursor-grab items-center justify-center gap-[3px] active:cursor-grabbing"
          aria-label="Drag handle"
          role="button"
        >
          {Array.from({ length: 12 }).map((_, i) => (
            <span key={i} className="h-[3px] w-[3px] bg-neutral-600" />
          ))}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setMode("full")}
            aria-label="Maximize to full screen"
            className="flex h-4 w-4 items-center justify-center border border-neutral-700 text-neutral-400 hover:border-neutral-400 hover:text-neutral-100"
          >
            <Maximize2 className="h-3 w-3" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            onClick={() => setMode("docked")}
            aria-label="Minimize to edge"
            className="flex h-4 w-4 items-center justify-center border border-neutral-700 text-neutral-400 hover:border-neutral-400 hover:text-neutral-100"
          >
            <Minus className="h-3 w-3" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            onClick={() => setMode("docked")}
            aria-label="Close"
            className="flex h-4 w-4 items-center justify-center border border-neutral-700 text-neutral-400 hover:border-neutral-400 hover:text-neutral-100"
          >
            <X className="h-3 w-3" strokeWidth={1.5} />
          </button>
        </div>
      </div>

      {chatSurface}
    </div>
  )
}

// Sidebar listing of historical chat sessions
function SessionPanel({
  sessions,
  activeSessionId,
  onSelectSession,
  onDeleteSession,
}: {
  sessions: { id: string; title: string }[]
  activeSessionId: string | null
  onSelectSession: (id: string) => void
  onDeleteSession: (id: string, e: React.MouseEvent) => void
}) {
  return (
    <div className="flex flex-col gap-1.5 overflow-y-auto pr-1">
      {sessions.map((sess) => {
        const isActive = sess.id === activeSessionId
        return (
          <div
            key={sess.id}
            onClick={() => onSelectSession(sess.id)}
            className={`group flex items-center justify-between border px-2 py-1.5 cursor-pointer transition-colors text-[11px] font-mono ${
              isActive
                ? "border-green-400 bg-green-400/10 text-green-400"
                : "border-neutral-800 bg-neutral-900 text-neutral-400 hover:border-neutral-500 hover:text-neutral-100"
            }`}
          >
            <span className="truncate pr-2">{sess.title}</span>
            <button
              onClick={(e) => onDeleteSession(sess.id, e)}
              className="opacity-0 group-hover:opacity-100 text-neutral-500 hover:text-red-400 px-1 text-[9px] border border-transparent hover:border-neutral-700 bg-transparent"
              title="Delete session"
            >
              DEL
            </button>
          </div>
        )
      })}
    </div>
  )
}

// Vertical list variant of the action buttons for the full-screen side panel.
function ActionPanel({ onAction }: { onAction: (id: string) => void }) {
  const actions = [
    { id: "search", label: "SEARCH DB" },
    { id: "summarize", label: "SUMMARIZE" },
    { id: "task", label: "CREATE TASK" },
  ]
  return (
    <div className="flex flex-col gap-2">
      {actions.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          onClick={() => onAction(id)}
          className="border border-neutral-700 bg-neutral-900 px-2 py-2 text-left text-[11px] tracking-wider text-neutral-100 transition-colors hover:border-green-400 hover:text-green-400"
        >
          {label}
        </button>
      ))}
    </div>
  )
}
