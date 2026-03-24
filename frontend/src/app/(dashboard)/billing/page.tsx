"use client"

import { useState, useEffect, useCallback } from "react"
import { Bar, BarChart, CartesianGrid, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer } from "recharts"
import { RefreshCw, Activity, DollarSign } from "lucide-react"

import { apiFetch } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"

interface Instance {
  id: string
  name: string
}

interface Summary {
  period_start: string
  period_end: string
  cpu_core_hours: number
  mem_gb_hours: number
  storage_gb_days: number
  amount_usd: number
  status: string
}

export default function BillingPage() {
  const [instances, setInstances] = useState<Instance[]>([])
  const [selectedInstance, setSelectedInstance] = useState<string>("all")
  const [granularity, setGranularity] = useState<string>("day")
  const [usageData, setUsageData] = useState<any[]>([])
  const [summaries, setSummaries] = useState<Summary[]>([])
  
  const [loadingUsage, setLoadingUsage] = useState(false)
  const [loadingSummaries, setLoadingSummaries] = useState(true)

  const loadInit = useCallback(async () => {
    try {
      const inst = await apiFetch("/instances")
      setInstances(inst)
      if (inst.length > 0) {
        setSelectedInstance(inst[0].id)
      }
      
      const sums = await apiFetch("/billing/summaries")
      setSummaries(sums)
    } catch {
      // ignore
    } finally {
      setLoadingSummaries(false)
    }
  }, [])

  useEffect(() => {
    loadInit()
  }, [loadInit])

  const loadUsage = useCallback(async () => {
    if (!selectedInstance || selectedInstance === "all") return
    setLoadingUsage(true)
    
    const end = new Date().toISOString().split('T')[0]
    const startDate = new Date()
    startDate.setDate(startDate.getDate() - 30)
    const start = startDate.toISOString().split('T')[0]
    
    try {
      const data = await apiFetch(`/billing/usage?instance_id=${selectedInstance}&start=${start}&end=${end}&granularity=${granularity}`)
      
      const formattedData = data.data.map((d: any) => ({
        ...d,
        periodDisplay: d.period.split('T')[0],
      }))
      setUsageData(formattedData)
    } catch {
      setUsageData([])
    } finally {
      setLoadingUsage(false)
    }
  }, [selectedInstance, granularity])

  useEffect(() => {
    loadUsage()
  }, [loadUsage])

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "running": 
      case "finalized": return <Badge className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20 shadow-none">Finalized</Badge>
      case "draft": 
      case "provisioning": return <Badge className="bg-amber-500/10 text-amber-500 border-amber-500/20 shadow-none">Draft</Badge>
      default: return <Badge variant="secondary">{status}</Badge>
    }
  }

  return (
    <div className="container mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-zinc-100">Billing & Usage</h1>
          <p className="text-zinc-400 mt-1">Monitor your resource consumption across instances.</p>
        </div>
      </div>

      <Card className="border-zinc-800 bg-zinc-900/50 backdrop-blur-sm">
        <CardHeader className="flex flex-row items-center justify-between pb-2">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5 text-primary" /> Resource Usage
            </CardTitle>
            <CardDescription className="text-zinc-400">View CPU and Memory usage trends over time.</CardDescription>
          </div>
          <div className="flex gap-2">
            <Select value={selectedInstance} onValueChange={(v) => setSelectedInstance(v || "all")} disabled={instances.length === 0}>
              <SelectTrigger className="w-[180px] bg-zinc-900/50 border-zinc-800">
                <SelectValue placeholder="Select instance" />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-800">
                {instances.length === 0 && <SelectItem value="all">No instances</SelectItem>}
                {instances.map(i => (
                  <SelectItem key={i.id} value={i.id}>{i.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={granularity} onValueChange={(v) => setGranularity(v || "day")}>
              <SelectTrigger className="w-[120px] bg-zinc-900/50 border-zinc-800">
                <SelectValue placeholder="Granularity" />
              </SelectTrigger>
              <SelectContent className="bg-zinc-900 border-zinc-800">
                <SelectItem value="day">Daily</SelectItem>
                <SelectItem value="hour">Hourly</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent className="pt-6">
          {loadingUsage ? (
            <div className="flex h-[300px] items-center justify-center text-zinc-400">
              <RefreshCw className="mr-2 h-5 w-5 animate-spin" /> Loading usage data...
            </div>
          ) : usageData.length === 0 ? (
            <div className="flex h-[300px] items-center justify-center text-zinc-500 border border-dashed border-zinc-800 rounded-lg bg-zinc-900/20">
              No usage data available for this selection.
            </div>
          ) : (
            <div className="h-[300px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={usageData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
                  <XAxis dataKey="periodDisplay" stroke="#71717a" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#71717a" fontSize={12} tickLine={false} axisLine={false} />
                  <Tooltip 
                    cursor={{ fill: '#27272a', opacity: 0.4 }}
                    contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a', borderRadius: '8px', color: '#f4f4f5' }} 
                  />
                  <Legend wrapperStyle={{ paddingTop: '10px' }} />
                  <Bar dataKey="cpu_core_hours" name="CPU Core-hours" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="mem_gb_hours" name="Memory GB-hours" fill="#10b981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-zinc-800 bg-zinc-900/50 backdrop-blur-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DollarSign className="h-5 w-5 text-emerald-500" /> Monthly Summaries
          </CardTitle>
          <CardDescription className="text-zinc-400">Aggregated usage metrics and estimated costs per billing period.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {loadingSummaries ? (
            <div className="flex items-center justify-center p-12 text-zinc-400">
              <RefreshCw className="mr-2 h-5 w-5 animate-spin" /> Loading summaries...
            </div>
          ) : summaries.length === 0 ? (
            <div className="p-12 text-center text-zinc-500 border-t border-zinc-800">
              No billing data yet.
            </div>
          ) : (
            <Table>
              <TableHeader className="bg-zinc-900 border-y border-zinc-800">
                <TableRow className="border-zinc-800 hover:bg-transparent">
                  <TableHead className="text-zinc-300">Period</TableHead>
                  <TableHead className="text-zinc-300 text-right">CPU (hrs)</TableHead>
                  <TableHead className="text-zinc-300 text-right">Memory (GB-hrs)</TableHead>
                  <TableHead className="text-zinc-300 text-right">Storage (GB-days)</TableHead>
                  <TableHead className="text-zinc-300 text-right font-medium text-emerald-500">Amount (USD)</TableHead>
                  <TableHead className="text-center text-zinc-300">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {summaries.map((s, i) => (
                  <TableRow key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/20">
                    <TableCell className="font-medium text-zinc-300">
                      {s.period_start} <span className="text-zinc-600 mx-1">→</span> {s.period_end}
                    </TableCell>
                    <TableCell className="text-right font-mono text-zinc-400">{(s.cpu_core_hours || 0).toFixed(4)}</TableCell>
                    <TableCell className="text-right font-mono text-zinc-400">{(s.mem_gb_hours || 0).toFixed(4)}</TableCell>
                    <TableCell className="text-right font-mono text-zinc-400">{(s.storage_gb_days || 0).toFixed(4)}</TableCell>
                    <TableCell className="text-right font-mono font-bold text-zinc-200">
                      ${(s.amount_usd || 0).toFixed(4)}
                    </TableCell>
                    <TableCell className="text-center">{getStatusBadge(s.status)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
