"use client"

import { useEffect, useState } from "react"
import { apiFetch } from "@/lib/api"

export interface CurrentUser {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  is_admin: boolean
}

export function useUser() {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiFetch("/users/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  return { user, loading }
}
