"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { logout } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Database } from "lucide-react"

export function Navigation() {
  const pathname = usePathname()

  return (
    <nav className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto flex h-16 items-center px-4">
        <div className="flex items-center gap-2 mr-8">
          <Database className="h-6 w-6 text-primary" />
          <span className="text-xl font-bold tracking-tight">ServerlessDB</span>
        </div>
        
        <div className="flex flex-1 items-center gap-4 text-sm font-medium">
          <Link
            href="/app"
            className={`transition-colors hover:text-foreground/80 ${
              pathname === "/app" ? "text-foreground" : "text-foreground/60"
            }`}
          >
            Instances
          </Link>
          <Link
            href="/billing"
            className={`transition-colors hover:text-foreground/80 ${
              pathname === "/billing" ? "text-foreground" : "text-foreground/60"
            }`}
          >
            Billing
          </Link>
        </div>

        <div className="flex items-center ml-auto">
          <Button variant="ghost" onClick={() => logout()}>
            Sign Out
          </Button>
        </div>
      </div>
    </nav>
  )
}
