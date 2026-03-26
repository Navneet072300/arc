"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { logout } from "@/lib/api"
import { useUser } from "@/lib/useUser"
import { Button } from "@/components/ui/button"
import { Database, ShieldCheck } from "lucide-react"

export function Navigation() {
  const pathname = usePathname()
  const { user } = useUser()

  const linkClass = (href: string) =>
    `transition-colors hover:text-foreground/80 ${pathname === href ? "text-foreground" : "text-foreground/60"}`

  return (
    <nav className="border-b bg-background/95 backdrop-blur supports-backdrop-filter:bg-background/60">
      <div className="container mx-auto flex h-16 items-center px-4">
        <div className="flex items-center gap-2 mr-8">
          <Database className="h-6 w-6 text-primary" />
          <span className="text-xl font-bold tracking-tight">Arc</span>
        </div>

        <div className="flex flex-1 items-center gap-4 text-sm font-medium">
          <Link href="/app" className={linkClass("/app")}>Instances</Link>
          <Link href="/billing" className={linkClass("/billing")}>Billing</Link>
          {user?.is_admin && (
            <Link href="/admin" className={`flex items-center gap-1 ${linkClass("/admin")}`}>
              <ShieldCheck className="h-4 w-4" />
              Admin
            </Link>
          )}
        </div>

        <div className="flex items-center gap-3 ml-auto">
          {user && (
            <span className="text-xs text-zinc-500 hidden sm:block">{user.email}</span>
          )}
          <Button variant="ghost" size="sm" onClick={() => logout()}>
            Sign Out
          </Button>
        </div>
      </div>
    </nav>
  )
}
