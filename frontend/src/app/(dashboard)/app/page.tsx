"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Plus, RefreshCw, Trash2, KeyRound, Database, Layers } from "lucide-react"

import { apiFetch } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"

interface Instance {
  id: string
  name: string
  slug: string
  status: string
  pg_version: string
  external_host: string | null
  external_port: number | null
  created_at: string
}

export default function InstancesPage() {
  const [instances, setInstances] = useState<Instance[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  
  // Create Modal
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [formData, setFormData] = useState({
    name: "",
    pg_version: "16",
    pg_db_name: "postgres",
    pg_username: "pguser",
    storage_size: "5Gi",
    pool_mode: "transaction",
    pool_size: "20",
    max_client_conn: "100",
  })
  const [createError, setCreateError] = useState("")

  // Creds Modal
  const [credsOpen, setCredsOpen] = useState(false)
  const [credsData, setCredsData] = useState<any>(null)

  const pollTimers = useRef<{ [key: string]: NodeJS.Timeout }>({})

  const loadInstances = useCallback(async () => {
    try {
      const data = await apiFetch("/instances")
      setInstances(data)
    } catch (err: any) {
      setError("Failed to load instances.")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadInstances()
  }, [loadInstances])

  useEffect(() => {
    instances.forEach(i => {
      if (i.status === "provisioning" || i.status === "deleting") {
        if (!pollTimers.current[i.id]) {
          pollTimers.current[i.id] = setInterval(async () => {
            try {
              const s = await apiFetch(`/instances/${i.id}/status`)
              if (s.status !== "provisioning" && s.status !== "deleting") {
                clearInterval(pollTimers.current[i.id])
                delete pollTimers.current[i.id]
                loadInstances()
              }
            } catch {
              clearInterval(pollTimers.current[i.id])
              delete pollTimers.current[i.id]
            }
          }, 4000)
        }
      }
    })

    return () => {
      Object.keys(pollTimers.current).forEach(id => {
        clearInterval(pollTimers.current[id])
      })
    }
  }, [instances, loadInstances])

  const handleCreate = async () => {
    setCreating(true)
    setCreateError("")
    try {
      const data = await apiFetch("/instances", {
        method: "POST",
        body: JSON.stringify(formData),
      })
      setCreateOpen(false)
      // Show credentials
      setCredsData({
        connection_string: data.connection_string || "(available once running)",
        host: data.external_host || "(provisioning...)",
        port: data.external_port || "(provisioning...)",
        username: data.pg_username,
        password: data.password,
      })
      setCredsOpen(true)
      loadInstances()
    } catch (err: any) {
      setCreateError(err.detail || "Failed to create instance")
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string, name: string) => {
    if (!window.confirm(`Delete "${name}"? This is irreversible.`)) return
    try {
      await apiFetch(`/instances/${id}`, { method: "DELETE" })
      loadInstances()
    } catch (err: any) {
      alert(err.detail || "Delete failed")
    }
  }

  const handleRotate = async (id: string) => {
    if (!window.confirm("Rotate credentials? The database will restart briefly.")) return
    try {
      const data = await apiFetch(`/instances/${id}/credentials/rotate`, { method: "POST" })
      setCredsData({
        connection_string: data.connection_string,
        host: data.host || "—",
        port: data.port || "—",
        username: data.username,
        password: data.password,
      })
      setCredsOpen(true)
    } catch (err: any) {
      alert(err.detail || "Rotation failed")
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "running": return <Badge className="bg-emerald-500/10 text-emerald-500 hover:bg-emerald-500/20 shadow-none border border-emerald-500/20">{status}</Badge>
      case "provisioning": return <Badge className="bg-amber-500/10 text-amber-500 hover:bg-amber-500/20 shadow-none border border-amber-500/20">{status}</Badge>
      case "deleting": return <Badge className="bg-destructive/10 text-destructive hover:bg-destructive/20 shadow-none border border-destructive/20">{status}</Badge>
      default: return <Badge variant="secondary">{status}</Badge>
    }
  }

  return (
    <div className="container mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold tracking-tight text-zinc-100">PostgreSQL Instances</h1>
        <Button onClick={() => {
            setFormData({ name: "", pg_version: "16", pg_db_name: "postgres", pg_username: "pguser", storage_size: "5Gi", pool_mode: "transaction", pool_size: "20", max_client_conn: "100" })
            setCreateError("")
            setCreateOpen(true)
        }}>
          <Plus className="mr-2 h-4 w-4" /> New Instance
        </Button>
      </div>

      <Card className="border-zinc-800 bg-zinc-900/50 backdrop-blur-sm">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center p-12 text-zinc-400">
              <RefreshCw className="mr-2 h-5 w-5 animate-spin" /> Loading instances...
            </div>
          ) : error ? (
            <div className="p-12 text-center text-destructive">{error}</div>
          ) : instances.length === 0 ? (
            <div className="flex flex-col items-center justify-center p-16 text-center">
              <div className="mb-4 rounded-full bg-zinc-800/50 p-4">
                <Database className="h-8 w-8 text-zinc-400" />
              </div>
              <h3 className="text-lg font-medium text-zinc-200">No instances yet</h3>
              <p className="mt-2 text-sm text-zinc-500">Create your first database cluster to get started.</p>
            </div>
          ) : (
            <Table>
              <TableHeader className="bg-zinc-900 border-b border-zinc-800">
                <TableRow className="border-zinc-800 hover:bg-transparent">
                  <TableHead className="text-zinc-300">Name</TableHead>
                  <TableHead className="text-zinc-300">Status</TableHead>
                  <TableHead className="text-zinc-300">Version</TableHead>
                  <TableHead className="text-zinc-300">Host</TableHead>
                  <TableHead className="text-zinc-300">Port</TableHead>
                  <TableHead className="text-zinc-300">Pooling</TableHead>
                  <TableHead className="text-zinc-300">Created</TableHead>
                  <TableHead className="text-right text-zinc-300">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <AnimatePresence>
                  {instances.map((i) => (
                    <motion.tr
                      key={i.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, scale: 0.95 }}
                      className="border-b border-zinc-800/50 transition-colors hover:bg-zinc-800/20 data-[state=selected]:bg-muted"
                    >
                      <TableCell className="font-medium">
                        <div>{i.name}</div>
                        <div className="text-xs text-zinc-500 font-mono mt-1">{i.slug}</div>
                      </TableCell>
                      <TableCell>{getStatusBadge(i.status)}</TableCell>
                      <TableCell className="text-zinc-300">PG {i.pg_version}</TableCell>
                      <TableCell className="font-mono text-sm text-zinc-400">{i.external_host || "—"}</TableCell>
                      <TableCell className="font-mono text-sm text-zinc-400">{i.external_port || "—"}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1">
                          <Layers className="h-3 w-3 text-zinc-500" />
                          <span className="text-xs text-zinc-400 font-mono">{(i as any).pool_mode ?? "txn"}</span>
                          <span className="text-xs text-zinc-600">/{(i as any).pool_size ?? 20}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-zinc-400 text-sm">
                        {new Date(i.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          {i.status === "running" && (
                            <Button variant="outline" size="sm" onClick={() => handleRotate(i.id)} className="border-amber-500/20 hover:bg-amber-500/10 hover:text-amber-500 text-zinc-400">
                              <KeyRound className="h-4 w-4" />
                            </Button>
                          )}
                          {i.status !== "deleting" && i.status !== "deleted" && (
                            <Button variant="outline" size="sm" onClick={() => handleDelete(i.id, i.name)} className="border-destructive/20 hover:bg-destructive/10 hover:text-destructive text-zinc-400">
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </motion.tr>
                  ))}
                </AnimatePresence>
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Create Instance Modal */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-[425px] border-zinc-800 bg-zinc-950">
          <DialogHeader>
            <DialogTitle>Create Instance</DialogTitle>
            <DialogDescription className="text-zinc-400">
              Provision a new highly-available PostgreSQL cluster.
            </DialogDescription>
          </DialogHeader>
          
          {createError && (
            <div className="rounded-md bg-destructive/15 p-3 text-sm text-destructive border border-destructive/20">
              {createError}
            </div>
          )}

          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="name">Name</Label>
              <Input 
                id="name" 
                placeholder="my-db" 
                value={formData.name} 
                onChange={(e) => setFormData({ ...formData, name: e.target.value })} 
                className="bg-zinc-900/50 border-zinc-800"
              />
              <span className="text-xs text-zinc-500">Lowercase, hyphens, 2-32 chars</span>
            </div>
            <div className="grid gap-2">
              <Label>PostgreSQL Version</Label>
              <Select value={formData.pg_version} onValueChange={(v) => setFormData({ ...formData, pg_version: v || "16" })}>
                <SelectTrigger className="bg-zinc-900/50 border-zinc-800">
                  <SelectValue placeholder="Select version" />
                </SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-800">
                  <SelectItem value="16">16 (Recommended)</SelectItem>
                  <SelectItem value="15">15</SelectItem>
                  <SelectItem value="14">14</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="dbname">Database Name</Label>
                <Input id="dbname" value={formData.pg_db_name} onChange={(e) => setFormData({ ...formData, pg_db_name: e.target.value })} className="bg-zinc-900/50 border-zinc-800" />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="username">Username</Label>
                <Input id="username" value={formData.pg_username} onChange={(e) => setFormData({ ...formData, pg_username: e.target.value })} className="bg-zinc-900/50 border-zinc-800" />
              </div>
            </div>
            <div className="grid gap-2">
              <Label>Storage</Label>
              <Select value={formData.storage_size} onValueChange={(v) => setFormData({ ...formData, storage_size: v || "5Gi" })}>
                <SelectTrigger className="bg-zinc-900/50 border-zinc-800">
                  <SelectValue placeholder="Select storage" />
                </SelectTrigger>
                <SelectContent className="bg-zinc-900 border-zinc-800">
                  <SelectItem value="1Gi">1 GiB</SelectItem>
                  <SelectItem value="5Gi">5 GiB (Standard)</SelectItem>
                  <SelectItem value="10Gi">10 GiB</SelectItem>
                  <SelectItem value="20Gi">20 GiB</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {/* PgBouncer pooling */}
            <div className="border-t border-zinc-800 pt-4 grid gap-4">
              <p className="text-xs text-zinc-500 font-medium flex items-center gap-1 uppercase tracking-wider">
                <Layers className="h-3 w-3" /> Connection Pooling (PgBouncer)
              </p>
              <div className="grid gap-2">
                <Label>Pool Mode</Label>
                <Select value={formData.pool_mode} onValueChange={(v) => setFormData({ ...formData, pool_mode: v || "transaction" })}>
                  <SelectTrigger className="bg-zinc-900/50 border-zinc-800">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-zinc-900 border-zinc-800">
                    <SelectItem value="transaction">Transaction (recommended)</SelectItem>
                    <SelectItem value="session">Session</SelectItem>
                    <SelectItem value="statement">Statement</SelectItem>
                  </SelectContent>
                </Select>
                <span className="text-xs text-zinc-500">Transaction mode is best for serverless workloads.</span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="grid gap-2">
                  <Label>Pool Size</Label>
                  <Input
                    type="number" min={1} max={200}
                    value={formData.pool_size}
                    onChange={(e) => setFormData({ ...formData, pool_size: e.target.value })}
                    className="bg-zinc-900/50 border-zinc-800"
                  />
                </div>
                <div className="grid gap-2">
                  <Label>Max Client Connections</Label>
                  <Input
                    type="number" min={1} max={10000}
                    value={formData.max_client_conn}
                    onChange={(e) => setFormData({ ...formData, max_client_conn: e.target.value })}
                    className="bg-zinc-900/50 border-zinc-800"
                  />
                </div>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)} className="border-zinc-800 hover:bg-zinc-800">
              Cancel
            </Button>
            <Button onClick={handleCreate} disabled={creating}>
              {creating && <RefreshCw className="mr-2 h-4 w-4 animate-spin" />}
              Create Instance
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Credentials Modal */}
      <Dialog open={credsOpen} onOpenChange={setCredsOpen}>
        <DialogContent className="sm:max-w-[500px] border-zinc-800 bg-zinc-950">
          <DialogHeader>
            <DialogTitle>Connection Details</DialogTitle>
            <DialogDescription className="text-amber-500 font-medium">
              Save these credentials now — the password will not be shown again.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label className="text-zinc-400">Connection String</Label>
              <div className="rounded-md bg-zinc-900 p-3 font-mono text-xs text-zinc-300 break-all border border-zinc-800">
                {credsData?.connection_string}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label className="text-zinc-400">Host</Label>
                <div className="rounded-md bg-zinc-900 p-2 font-mono text-sm border border-zinc-800">{credsData?.host}</div>
              </div>
              <div className="grid gap-2">
                <Label className="text-zinc-400">Port</Label>
                <div className="rounded-md bg-zinc-900 p-2 font-mono text-sm border border-zinc-800">{credsData?.port}</div>
              </div>
              <div className="grid gap-2">
                <Label className="text-zinc-400">Username</Label>
                <div className="rounded-md bg-zinc-900 p-2 font-mono text-sm border border-zinc-800">{credsData?.username}</div>
              </div>
              <div className="grid gap-2">
                <Label className="text-zinc-400">Password</Label>
                <div className="rounded-md bg-zinc-900 p-2 font-mono text-sm border border-zinc-800 text-amber-500/80">{credsData?.password}</div>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setCredsOpen(false)} className="w-full sm:w-auto">Understood</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
