"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { motion } from "framer-motion"
import {
  Users, Database, Activity, DollarSign,
  Trash2, ShieldCheck, ShieldOff, UserCheck, UserX,
  RefreshCw, Play, AlertTriangle, Server
} from "lucide-react"

import { apiFetch } from "@/lib/api"
import { useUser } from "@/lib/useUser"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

interface Stats {
  total_users: number
  total_instances: number
  running_instances: number
  provisioning_instances: number
  error_instances: number
  total_revenue_usd: number
}

interface AdminUser {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  is_admin: boolean
  instance_count: number
  created_at: string
}

interface AdminInstance {
  id: string
  name: string
  slug: string
  status: string
  pg_version: string
  external_host: string | null
  external_port: number | null
  user_email: string
  storage_size: string
  cpu_request: string
  mem_request: string
  created_at: string
}

type Tab = "overview" | "users" | "instances"

export default function AdminPage() {
  const router = useRouter()
  const { user, loading: userLoading } = useUser()

  const [tab, setTab] = useState<Tab>("overview")
  const [stats, setStats] = useState<Stats | null>(null)
  const [users, setUsers] = useState<AdminUser[]>([])
  const [instances, setInstances] = useState<AdminInstance[]>([])
  const [loading, setLoading] = useState(true)
  const [billingRunning, setBillingRunning] = useState(false)
  const [toastMsg, setToastMsg] = useState("")

  // Redirect non-admins
  useEffect(() => {
    if (!userLoading && user && !user.is_admin) router.push("/app")
  }, [user, userLoading, router])

  const loadStats = useCallback(async () => {
    const data = await apiFetch("/admin/stats")
    setStats(data)
  }, [])

  const loadUsers = useCallback(async () => {
    const data = await apiFetch("/admin/users")
    setUsers(data)
  }, [])

  const loadInstances = useCallback(async () => {
    const data = await apiFetch("/admin/instances")
    setInstances(data)
  }, [])

  useEffect(() => {
    if (!user?.is_admin) return
    setLoading(true)
    Promise.all([loadStats(), loadUsers(), loadInstances()]).finally(() => setLoading(false))
  }, [user, loadStats, loadUsers, loadInstances])

  const toast = (msg: string) => {
    setToastMsg(msg)
    setTimeout(() => setToastMsg(""), 3000)
  }

  const handleToggleActive = async (userId: string, current: boolean) => {
    try {
      await apiFetch(`/admin/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !current }),
      })
      setUsers(prev => prev.map(u => u.id === userId ? { ...u, is_active: !current } : u))
      toast(`User ${!current ? "activated" : "deactivated"}`)
    } catch { toast("Failed to update user") }
  }

  const handleToggleAdmin = async (userId: string, current: boolean) => {
    try {
      await apiFetch(`/admin/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ is_admin: !current }),
      })
      setUsers(prev => prev.map(u => u.id === userId ? { ...u, is_admin: !current } : u))
      toast(`Admin ${!current ? "granted" : "revoked"}`)
    } catch { toast("Failed to update user") }
  }

  const handleDeleteInstance = async (id: string, name: string) => {
    if (!window.confirm(`Force delete "${name}"? This is irreversible.`)) return
    try {
      await apiFetch(`/admin/instances/${id}`, { method: "DELETE" })
      setInstances(prev => prev.map(i => i.id === id ? { ...i, status: "deleting" } : i))
      toast("Deletion initiated")
    } catch { toast("Delete failed") }
  }

  const handleRunBilling = async () => {
    setBillingRunning(true)
    try {
      await apiFetch("/admin/billing/run", { method: "POST" })
      toast("Billing aggregation started")
    } catch { toast("Failed to start billing run") }
    finally { setBillingRunning(false) }
  }

  const getStatusBadge = (status: string) => {
    const map: Record<string, string> = {
      running: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
      provisioning: "bg-amber-500/10 text-amber-500 border-amber-500/20",
      deleting: "bg-red-500/10 text-red-400 border-red-500/20",
      error: "bg-red-500/10 text-red-400 border-red-500/20",
      deleted: "bg-zinc-500/10 text-zinc-500 border-zinc-500/20",
    }
    return (
      <Badge className={`shadow-none border ${map[status] ?? "bg-zinc-500/10 text-zinc-500 border-zinc-500/20"}`}>
        {status}
      </Badge>
    )
  }

  if (userLoading || loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <RefreshCw className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: "overview", label: "Overview", icon: <Activity className="h-4 w-4" /> },
    { id: "users", label: `Users (${users.length})`, icon: <Users className="h-4 w-4" /> },
    { id: "instances", label: `Instances (${instances.length})`, icon: <Database className="h-4 w-4" /> },
  ]

  return (
    <div className="container mx-auto max-w-7xl space-y-6">
      {/* Toast */}
      {toastMsg && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          className="fixed top-20 right-6 z-50 rounded-lg bg-zinc-800 border border-zinc-700 px-4 py-3 text-sm text-zinc-100 shadow-xl"
        >
          {toastMsg}
        </motion.div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-zinc-100 flex items-center gap-2">
            <ShieldCheck className="h-8 w-8 text-primary" />
            Admin Panel
          </h1>
          <p className="text-zinc-400 mt-1">Platform management and oversight</p>
        </div>
        <Button
          variant="outline"
          className="border-zinc-700 hover:bg-zinc-800 gap-2"
          onClick={handleRunBilling}
          disabled={billingRunning}
        >
          {billingRunning ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          Run Billing
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 rounded-lg bg-zinc-900 border border-zinc-800 p-1 w-fit">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-colors
              ${tab === t.id
                ? "bg-zinc-700 text-zinc-100"
                : "text-zinc-400 hover:text-zinc-200"
              }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {/* Overview */}
      {tab === "overview" && stats && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            {[
              { label: "Total Users", value: stats.total_users, icon: <Users className="h-5 w-5" />, color: "text-blue-400" },
              { label: "Total Instances", value: stats.total_instances, icon: <Database className="h-5 w-5" />, color: "text-purple-400" },
              { label: "Running", value: stats.running_instances, icon: <Activity className="h-5 w-5" />, color: "text-emerald-400" },
              { label: "Provisioning", value: stats.provisioning_instances, icon: <Server className="h-5 w-5" />, color: "text-amber-400" },
              { label: "Errors", value: stats.error_instances, icon: <AlertTriangle className="h-5 w-5" />, color: "text-red-400" },
              { label: "Revenue (USD)", value: `$${stats.total_revenue_usd.toFixed(2)}`, icon: <DollarSign className="h-5 w-5" />, color: "text-emerald-400" },
            ].map((stat) => (
              <Card key={stat.label} className="border-zinc-800 bg-zinc-900/50">
                <CardContent className="p-5">
                  <div className={`mb-3 ${stat.color}`}>{stat.icon}</div>
                  <div className="text-2xl font-bold text-zinc-100">{stat.value}</div>
                  <div className="text-xs text-zinc-500 mt-1">{stat.label}</div>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Quick summary tables */}
          <div className="grid md:grid-cols-2 gap-4 mt-4">
            <Card className="border-zinc-800 bg-zinc-900/50">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-zinc-300">Recent Users</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableBody>
                    {users.slice(0, 5).map(u => (
                      <TableRow key={u.id} className="border-zinc-800/50 hover:bg-zinc-800/20">
                        <TableCell className="text-zinc-300 text-sm">{u.email}</TableCell>
                        <TableCell className="text-right">
                          <span className="text-xs text-zinc-500">{u.instance_count} instances</span>
                        </TableCell>
                        <TableCell className="text-right">
                          {u.is_admin && <Badge className="bg-primary/10 text-primary border-primary/20 shadow-none text-xs">admin</Badge>}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>

            <Card className="border-zinc-800 bg-zinc-900/50">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium text-zinc-300">Recent Instances</CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableBody>
                    {instances.slice(0, 5).map(i => (
                      <TableRow key={i.id} className="border-zinc-800/50 hover:bg-zinc-800/20">
                        <TableCell className="text-zinc-300 text-sm">{i.name}</TableCell>
                        <TableCell className="text-xs text-zinc-500">{i.user_email}</TableCell>
                        <TableCell className="text-right">{getStatusBadge(i.status)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>
        </motion.div>
      )}

      {/* Users */}
      {tab === "users" && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <Card className="border-zinc-800 bg-zinc-900/50">
            <CardHeader>
              <CardTitle>All Users</CardTitle>
              <CardDescription className="text-zinc-400">Manage user accounts and permissions</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader className="bg-zinc-900 border-b border-zinc-800">
                  <TableRow className="border-zinc-800 hover:bg-transparent">
                    <TableHead className="text-zinc-300">Email</TableHead>
                    <TableHead className="text-zinc-300">Name</TableHead>
                    <TableHead className="text-zinc-300 text-center">Instances</TableHead>
                    <TableHead className="text-zinc-300 text-center">Status</TableHead>
                    <TableHead className="text-zinc-300 text-center">Role</TableHead>
                    <TableHead className="text-zinc-300">Joined</TableHead>
                    <TableHead className="text-right text-zinc-300">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map(u => (
                    <TableRow key={u.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                      <TableCell className="font-mono text-sm text-zinc-300">{u.email}</TableCell>
                      <TableCell className="text-zinc-400">{u.full_name || "—"}</TableCell>
                      <TableCell className="text-center text-zinc-400">{u.instance_count}</TableCell>
                      <TableCell className="text-center">
                        <Badge className={u.is_active
                          ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20 shadow-none"
                          : "bg-zinc-500/10 text-zinc-500 border-zinc-500/20 shadow-none"
                        }>
                          {u.is_active ? "active" : "disabled"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-center">
                        <Badge className={u.is_admin
                          ? "bg-primary/10 text-primary border-primary/20 shadow-none"
                          : "bg-zinc-500/10 text-zinc-500 border-zinc-500/20 shadow-none"
                        }>
                          {u.is_admin ? "admin" : "user"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-zinc-500 text-sm">
                        {new Date(u.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="outline" size="sm"
                            onClick={() => handleToggleActive(u.id, u.is_active)}
                            className="border-zinc-700 hover:bg-zinc-800 text-zinc-400 gap-1"
                            title={u.is_active ? "Disable user" : "Enable user"}
                          >
                            {u.is_active ? <UserX className="h-3 w-3" /> : <UserCheck className="h-3 w-3" />}
                          </Button>
                          <Button
                            variant="outline" size="sm"
                            onClick={() => handleToggleAdmin(u.id, u.is_admin)}
                            className="border-zinc-700 hover:bg-zinc-800 text-zinc-400 gap-1"
                            title={u.is_admin ? "Revoke admin" : "Grant admin"}
                          >
                            {u.is_admin ? <ShieldOff className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Instances */}
      {tab === "instances" && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <Card className="border-zinc-800 bg-zinc-900/50">
            <CardHeader>
              <CardTitle>All Instances</CardTitle>
              <CardDescription className="text-zinc-400">View and manage all PostgreSQL instances across all users</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader className="bg-zinc-900 border-b border-zinc-800">
                  <TableRow className="border-zinc-800 hover:bg-transparent">
                    <TableHead className="text-zinc-300">Name</TableHead>
                    <TableHead className="text-zinc-300">Owner</TableHead>
                    <TableHead className="text-zinc-300">Status</TableHead>
                    <TableHead className="text-zinc-300">Version</TableHead>
                    <TableHead className="text-zinc-300">Host</TableHead>
                    <TableHead className="text-zinc-300">Resources</TableHead>
                    <TableHead className="text-zinc-300">Created</TableHead>
                    <TableHead className="text-right text-zinc-300">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {instances.map(i => (
                    <TableRow key={i.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                      <TableCell className="font-medium">
                        <div className="text-zinc-200">{i.name}</div>
                        <div className="text-xs text-zinc-500 font-mono mt-0.5">{i.slug}</div>
                      </TableCell>
                      <TableCell className="text-zinc-400 text-sm">{i.user_email}</TableCell>
                      <TableCell>{getStatusBadge(i.status)}</TableCell>
                      <TableCell className="text-zinc-400">PG {i.pg_version}</TableCell>
                      <TableCell className="font-mono text-xs text-zinc-400">
                        {i.external_host ? `${i.external_host}:${i.external_port}` : "—"}
                      </TableCell>
                      <TableCell className="text-xs text-zinc-500">
                        {i.cpu_request} CPU · {i.mem_request} RAM · {i.storage_size}
                      </TableCell>
                      <TableCell className="text-zinc-500 text-sm">
                        {new Date(i.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell className="text-right">
                        {i.status !== "deleting" && i.status !== "deleted" && (
                          <Button
                            variant="outline" size="sm"
                            onClick={() => handleDeleteInstance(i.id, i.name)}
                            className="border-red-500/20 hover:bg-red-500/10 hover:text-red-400 text-zinc-400"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </motion.div>
      )}
    </div>
  )
}
