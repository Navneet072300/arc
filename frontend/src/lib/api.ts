export const BASE = ''; // same origin

export async function apiFetch(path: string, options: RequestInit = {}) {
  const token = localStorage.getItem('access_token');
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const res = await fetch(BASE + path, { ...options, headers });

  if (res.status === 401) {
    // Try refresh
    const refreshed = await tryRefresh();
    if (refreshed) {
      headers.set('Authorization', `Bearer ${localStorage.getItem('access_token')}`);
      const retry = await fetch(BASE + path, { ...options, headers });
      if (!retry.ok) {
        throw await retry.json().catch(() => ({ detail: retry.statusText }));
      }
      return retry.status === 204 ? null : retry.json();
    } else {
      localStorage.clear();
      window.location.href = '/ui/';
      return;
    }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

async function tryRefresh(): Promise<boolean> {
  const rt = localStorage.getItem('refresh_token');
  if (!rt) return false;
  try {
    const res = await fetch('/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem('access_token', data.access_token);
    return true;
  } catch {
    return false;
  }
}

export function isLoggedIn(): boolean {
  if (typeof window === 'undefined') return false;
  return !!localStorage.getItem('access_token');
}

export function logout() {
  if (typeof window === 'undefined') return;
  const rt = localStorage.getItem('refresh_token');
  if (rt) {
    fetch('/auth/logout', { 
      method: 'POST', 
      headers: { 'Content-Type': 'application/json' }, 
      body: JSON.stringify({ refresh_token: rt }) 
    }).catch(() => {});
  }
  localStorage.clear();
  window.location.href = '/ui/';
}
