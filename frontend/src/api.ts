const base = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${base}/api${path}`, body === undefined ? {} : {
    method: 'POST', headers: body instanceof FormData ? {} : {'Content-Type': 'application/json'},
    body: body instanceof FormData ? body : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `Request failed (${response.status}).`);
  }
  return response.json();
}
