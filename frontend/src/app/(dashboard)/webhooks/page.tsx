"use client"

import { useState, useEffect, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Plus, Trash2, Send, ChevronDown, ChevronUp, RefreshCw, Webhook, CheckCircle, XCircle, Clock } from "lucide-react"

import { apiFetch } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const ALL_EVENTS = [
  "instance.provisioning",
  "instance.running",
  "instance.error",
  "instance.deleted",
  "credentials.rotated",
  "*",
]

interface Endpoint {
  id: string
  url: string
  events: string[]
  is_active: boolean
  created_at: string
}

interface Delivery {
  id: string
  event: string
  status: string
  attempts: number
  response_code: number | null
  response_body: string | null
  last_attempt_at: string | null
  created_at: string
}

export default function WebhooksPage() {
  const [endpoints, setEndpoints] = useState<Endpoint[]>([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState("")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [deliveries, setDeliveries] = useState<Record<string, Delivery[]>>({})
  const [toastMsg, setToastMsg] = useState("")

  const [form, setForm] = useState({ url: "", events: [] as string[], secret: "" })

  const toast = (msg: string) => {
    setToastMsg(msg)
    setTimeout(() => setToastMsg(""), 3000)
  }

  const load = useCallback(async () => {
    try {
      const data = await apiFetch("/webhooks")
      setEndpoints(data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const loadDeliveries = async (endpointId: string) => {
    if (deliveries[endpointId]) return
    try {
      const data = await apiFetch(`/webhooks/${endpointId}/deliveries`)
      setDeliveries(prev => ({ ...prev, [endpointId]: data }))
    } catch { /* ignore */ }
  }

  const toggleExpand = (id: string) => {
    if (expandedId === id) {
      setExpandedId(null)
    } else {
      setExpandedId(id)
      loadDeliveries(id)
    }
  }

  const toggleEvent = (event: string) => {
    setForm(prev => ({
      ...prev,
      events: prev.events.includes(event)
        ? prev.events.filter(e => e !== event)
        : [...prev.events, event],
    }))
  }

  const handleCreate = async () => {
    if (!form.url) { setCreateError("URL is required"); return }
    if (form.events.length === 0) { setCreateError("Select at least one event"); return }
    setCreating(true)
    setCreateError("")
    try {
      const body: any = { url: form.url, events: form.events }
      if (form.secret) body.secret = form.secret
      await apiFetch("/webhooks", { method: "POST", body: JSON.stringify(body) })
      setCreateOpen(false)
      setForm({ url: "", events: [], secret: "" })
      load()
      toast("Webhook created")
    } catch (e: any) {
      setCreateError(e.detail || "Failed to create webhook")
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this webhook endpoint?")) return
    try {
      await apiFetch(`/webhooks/${id}`, { method: "DELETE" })
      setEndpoints(prev => prev.filter(e => e.id !== id))
      toast("Webhook deleted")
    } catch { toast("Delete failed") }
  }

  const handleToggleActive = async (ep: Endpoint) => {
    try {
      const updated = await apiFetch(`/webhooks/${ep.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !ep.is_active }),
      })
      setEndpoints(prev => prev.map(e => e.id === ep.id ? updated : e))
      toast(updated.is_active ? "Webhook enabled" : "Webhook disabled")
    } catch { toast("Update failed") }
  }

  const handleTest = async (id: string) => {
    try {
      await apiFetch(`/webhooks/${id}/test`, { method: "POST" })
      toast("Test event sent")
      setDeliveries(prev => ({ ...prev, [id]: [] }))
      setTimeout(() => loadDeliveries(id), 1500)
    } catch { toast("Test failed") }
  }

  const statusIcon = (status: string) => {
    if (status === "success") return <CheckCircle className="h-4 w-4 text-emerald-500" />
    if (status === "failed") return <XCircle className="h-4 w-4 text-red-400" />
    return <Clock className="h-4 w-4 text-amber-400" />
  }

  const statusBadge = (status: string) => {
    const map: Record<string, string> = {
      success: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
      failed: "bg-red-500/10 text-red-400 border-red-500/20",
      pending: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    }
    return <Badge className={`shadow-none border ${map[status] ?? ""}`}>{status}</Badge>
  }

  return (
    <div className="container mx-auto max-w-5xl space-y-6">
      {toastMsg && (
        <motion.div
          initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}
          className="fixed top-20 right-6 z-50 rounded-lg bg-zinc-800 border border-zinc-700 px-4 py-3 text-sm text-zinc-100 shadow-xl"
        >
          {toastMsg}
        </motion.div>
      )}

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-zinc-100 flex items-center gap-2">
            <Webhook className="h-8 w-8 text-primary" /> Webhooks
          </h1>
          <p className="text-zinc-400 mt-1">Receive HTTP notifications when instance events occur.</p>
        </div>
        <Button onClick={() => { setCreateError(""); setCreateOpen(true) }}>
          <Plus className="mr-2 h-4 w-4" /> Add Endpoint
        </Button>
      </div>

      {/* Events reference */}
      <Card className="border-zinc-800 bg-zinc-900/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium text-zinc-300">Available Events</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2 pt-0">
          {ALL_EVENTS.filter(e => e !== "*").map(e => (
            <Badge key={e} className="bg-zinc-800 text-zinc-300 border-zinc-700 shadow-none font-mono text-xs">{e}</Badge>
          ))}
          <Badge className="bg-primary/10 text-primary border-primary/20 shadow-none font-mono text-xs">* (all events)</Badge>
        </CardContent>
      </Card>

      {/* Endpoints */}
      {loading ? (
        <div className="flex items-center justify-center p-12 text-zinc-400">
          <RefreshCw className="mr-2 h-5 w-5 animate-spin" /> Loading...
        </div>
      ) : endpoints.length === 0 ? (
        <Card className="border-zinc-800 bg-zinc-900/50">
          <CardContent className="flex flex-col items-center justify-center p-16 text-center">
            <div className="mb-4 rounded-full bg-zinc-800/50 p-4">
              <Webhook className="h-8 w-8 text-zinc-400" />
            </div>
            <h3 className="text-lg font-medium text-zinc-200">No webhook endpoints</h3>
            <p className="mt-2 text-sm text-zinc-500">Add an endpoint to start receiving event notifications.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          <AnimatePresence>
            {endpoints.map(ep => (
              <motion.div key={ep.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <Card className="border-zinc-800 bg-zinc-900/50">
                  <CardContent className="p-4">
                    <div className="flex items-center gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-mono text-sm text-zinc-200 truncate">{ep.url}</span>
                          <Badge className={ep.is_active
                            ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20 shadow-none"
                            : "bg-zinc-500/10 text-zinc-500 border-zinc-500/20 shadow-none"
                          }>
                            {ep.is_active ? "active" : "paused"}
                          </Badge>
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {ep.events.map(e => (
                            <Badge key={e} className="bg-zinc-800 text-zinc-400 border-zinc-700 shadow-none font-mono text-xs">{e}</Badge>
                          ))}
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Button variant="outline" size="sm" onClick={() => handleTest(ep.id)}
                          className="border-zinc-700 hover:bg-zinc-800 text-zinc-400 gap-1">
                          <Send className="h-3 w-3" /> Test
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => handleToggleActive(ep)}
                          className="border-zinc-700 hover:bg-zinc-800 text-zinc-400">
                          {ep.is_active ? "Pause" : "Enable"}
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => handleDelete(ep.id)}
                          className="border-red-500/20 hover:bg-red-500/10 hover:text-red-400 text-zinc-400">
                          <Trash2 className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => toggleExpand(ep.id)}
                          className="text-zinc-400 hover:text-zinc-200">
                          {expandedId === ep.id ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                        </Button>
                      </div>
                    </div>

                    {/* Deliveries drawer */}
                    <AnimatePresence>
                      {expandedId === ep.id && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="overflow-hidden"
                        >
                          <div className="mt-4 border-t border-zinc-800 pt-4">
                            <p className="text-xs text-zinc-500 mb-3 font-medium uppercase tracking-wider">Recent Deliveries</p>
                            {!deliveries[ep.id] ? (
                              <div className="text-zinc-500 text-sm flex items-center gap-2">
                                <RefreshCw className="h-3 w-3 animate-spin" /> Loading...
                              </div>
                            ) : deliveries[ep.id].length === 0 ? (
                              <p className="text-zinc-500 text-sm">No deliveries yet.</p>
                            ) : (
                              <Table>
                                <TableHeader>
                                  <TableRow className="border-zinc-800 hover:bg-transparent">
                                    <TableHead className="text-zinc-400 text-xs">Event</TableHead>
                                    <TableHead className="text-zinc-400 text-xs">Status</TableHead>
                                    <TableHead className="text-zinc-400 text-xs">HTTP</TableHead>
                                    <TableHead className="text-zinc-400 text-xs">Attempts</TableHead>
                                    <TableHead className="text-zinc-400 text-xs">Time</TableHead>
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {deliveries[ep.id].map(d => (
                                    <TableRow key={d.id} className="border-zinc-800/50 hover:bg-zinc-800/20">
                                      <TableCell className="font-mono text-xs text-zinc-300">{d.event}</TableCell>
                                      <TableCell>
                                        <div className="flex items-center gap-1">
                                          {statusIcon(d.status)}
                                          {statusBadge(d.status)}
                                        </div>
                                      </TableCell>
                                      <TableCell className="font-mono text-xs text-zinc-400">{d.response_code ?? "—"}</TableCell>
                                      <TableCell className="text-xs text-zinc-400">{d.attempts}</TableCell>
                                      <TableCell className="text-xs text-zinc-500">
                                        {d.last_attempt_at ? new Date(d.last_attempt_at).toLocaleString() : "—"}
                                      </TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            )}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}

      {/* Create dialog */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-[480px] border-zinc-800 bg-zinc-950">
          <DialogHeader>
            <DialogTitle>Add Webhook Endpoint</DialogTitle>
            <DialogDescription className="text-zinc-400">
              Arc will POST a signed JSON payload to this URL when events occur.
            </DialogDescription>
          </DialogHeader>

          {createError && (
            <div className="rounded-md bg-destructive/15 p-3 text-sm text-destructive border border-destructive/20">
              {createError}
            </div>
          )}

          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <Label>Endpoint URL</Label>
              <Input
                placeholder="https://example.com/webhooks/arc"
                value={form.url}
                onChange={e => setForm({ ...form, url: e.target.value })}
                className="bg-zinc-900/50 border-zinc-800 font-mono text-sm"
              />
            </div>

            <div className="grid gap-2">
              <Label>Events</Label>
              <div className="flex flex-wrap gap-2">
                {ALL_EVENTS.map(e => (
                  <button
                    key={e}
                    type="button"
                    onClick={() => toggleEvent(e)}
                    className={`rounded-md px-3 py-1.5 text-xs font-mono border transition-colors
                      ${form.events.includes(e)
                        ? "bg-primary/20 border-primary/40 text-primary"
                        : "bg-zinc-900 border-zinc-700 text-zinc-400 hover:border-zinc-500"
                      }`}
                  >
                    {e}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid gap-2">
              <Label>
                Signing Secret <span className="text-zinc-500 font-normal">(optional — auto-generated if blank)</span>
              </Label>
              <Input
                placeholder="your-secret"
                value={form.secret}
                onChange={e => setForm({ ...form, secret: e.target.value })}
                className="bg-zinc-900/50 border-zinc-800 font-mono text-sm"
              />
              <p className="text-xs text-zinc-500">
                Payloads are signed with HMAC-SHA256. Verify using the <code className="text-zinc-400">X-Arc-Signature</code> header.
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)} className="border-zinc-800">Cancel</Button>
            <Button onClick={handleCreate} disabled={creating}>
              {creating && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}
              Create Endpoint
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
