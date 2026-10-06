// Типы и вызовы backend API (recon/api.py). Импорт и сверка — отдельные действия.

export type Side = { name: string; count: number; amount_kopecks: number }

export type ChargeValue = { account_id: string | null; period: string; amount_kopecks: number }
export type TotalsValue = { count: number; amount_kopecks: number }

export type Discrepancy = {
  type: string
  record_id: string | null
  source: (ChargeValue & Partial<TotalsValue>) | null
  target: (ChargeValue & Partial<TotalsValue>) | null
  message: string
}

export type Report = {
  run_id?: string
  period: string
  status: 'ok' | 'discrepancies' | 'error'
  finished_at?: string | null
  source?: Side | null
  target?: Side | null
  rules?: string[]
  discrepancies?: Discrepancy[]
  error?: string | null
}

export type Problem = { rule: string; entity: string; record_id: string | null; message: string }

export type ImportResult = {
  run_id?: string
  status: 'ok' | 'rejected' | 'error'
  source?: string
  counts?: Record<string, number>
  problems?: Problem[]
  error?: string | null
}

type Job<T> = { job_id: string; status: 'running' | 'finished'; result: T | null }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${await response.text()}`)
  }
  return response.json() as Promise<T>
}

// Запускает задачу и опрашивает её до завершения.
async function runJob<T>(path: string, body?: unknown): Promise<T> {
  const job = await request<Job<T>>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const deadline = Date.now() + 120_000
  while (Date.now() < deadline) {
    const current = await request<Job<T>>(`/api/jobs/${job.job_id}`)
    if (current.status === 'finished' && current.result) return current.result
    await new Promise((resolve) => setTimeout(resolve, 700))
  }
  throw new Error('Задача не завершилась за 2 минуты')
}

export const startImport = () => runJob<ImportResult>('/api/import')
export const startReconcile = (period: string) =>
  runJob<Report>('/api/reconcile', { period })
