import { useState } from 'react'
import {
  startImport,
  startReconcile,
  type Discrepancy,
  type ImportResult,
  type Report,
} from './api'
import { kopecks, rubles } from './format'

type Phase<T> =
  | { state: 'idle' }
  | { state: 'running' }
  | { state: 'done'; result: T }
  | { state: 'failed'; message: string }

const TYPE_LABELS: Record<string, string> = {
  missing_in_target: 'Нет в PostgreSQL',
  missing_in_source: 'Нет в 1С',
  amount_mismatch: 'Разная сумма',
  account_mismatch: 'Разный лицевой счёт',
  totals_mismatch: 'Итоги месяца',
}

export default function App() {
  const [period, setPeriod] = useState('2026-08')
  const [importPhase, setImportPhase] = useState<Phase<ImportResult>>({ state: 'idle' })
  const [reconPhase, setReconPhase] = useState<Phase<Report>>({ state: 'idle' })
  const busy = importPhase.state === 'running' || reconPhase.state === 'running'

  async function onImport() {
    setImportPhase({ state: 'running' })
    try {
      setImportPhase({ state: 'done', result: await startImport() })
    } catch (error) {
      setImportPhase({ state: 'failed', message: String(error) })
    }
  }

  async function onReconcile() {
    setReconPhase({ state: 'running' })
    try {
      setReconPhase({ state: 'done', result: await startReconcile(period) })
    } catch (error) {
      setReconPhase({ state: 'failed', message: String(error) })
    }
  }

  return (
    <main>
      <h1>Сверка начислений 1С ↔ PostgreSQL</h1>

      <section className="controls">
        <label>
          Месяц{' '}
          <input
            type="month"
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
            required
          />
        </label>
        <button onClick={onImport} disabled={busy}>
          1. Импорт из 1С
        </button>
        <button onClick={onReconcile} disabled={busy || !period}>
          2. Сверка за месяц
        </button>
      </section>
      <p className="hint">
        Импорт загружает все данные из 1С в PostgreSQL. Сверка только читает обе стороны и не
        меняет данные.
      </p>

      <section>
        <h2>Импорт</h2>
        <ImportView phase={importPhase} />
      </section>

      <section>
        <h2>Сверка</h2>
        <ReconView phase={reconPhase} />
      </section>
    </main>
  )
}

function ImportView({ phase }: { phase: Phase<ImportResult> }) {
  if (phase.state === 'idle') return <p className="muted">Импорт ещё не запускался.</p>
  if (phase.state === 'running') return <p className="running">Импорт выполняется…</p>
  if (phase.state === 'failed') return <ErrorBox title="Импорт не выполнен" text={phase.message} />
  const result = phase.result
  if (result.status === 'error')
    return <ErrorBox title="Импорт не выполнен" text={result.error ?? 'неизвестная ошибка'} />
  if (result.status === 'rejected')
    return (
      <div className="box error" role="alert">
        <strong>Импорт отклонён правилами валидации — данные не записаны</strong>
        <ul>
          {result.problems?.map((p, i) => (
            <li key={i}>
              <code>{p.rule}</code> {p.entity}/{p.record_id ?? '—'}: {p.message}
            </li>
          ))}
        </ul>
      </div>
    )
  return (
    <div className="box ok">
      Импорт выполнен: счетов {result.counts?.accounts}, начислений {result.counts?.charges},
      платежей {result.counts?.payments}.{' '}
      <span className="muted">run_id {result.run_id}</span>
    </div>
  )
}

function ReconView({ phase }: { phase: Phase<Report> }) {
  if (phase.state === 'idle') return <p className="muted">Сверка ещё не запускалась.</p>
  if (phase.state === 'running') return <p className="running">Сверка выполняется…</p>
  if (phase.state === 'failed') return <ErrorBox title="Сверка не выполнена" text={phase.message} />
  const report = phase.result
  if (report.status === 'error')
    return (
      <ErrorBox
        title={`Сверка за ${report.period} не выполнена — результат неизвестен`}
        text={report.error ?? 'неизвестная ошибка'}
      />
    )

  const discrepancies = report.discrepancies ?? []
  return (
    <>
      <p>
        Период <strong>{report.period}</strong>, статус{' '}
        <strong className={report.status}>
          {report.status === 'ok' ? 'расхождений нет' : 'найдены расхождения'}
        </strong>
        <span className="muted"> · run_id {report.run_id}</span>
      </p>
      <table>
        <thead>
          <tr>
            <th>Источник</th>
            <th>Начислений</th>
            <th>Сумма</th>
          </tr>
        </thead>
        <tbody>
          {[report.source, report.target].map((side) => (
            <tr key={side?.name}>
              <td>{side?.name}</td>
              <td className="num">{side?.count}</td>
              <td className="num">
                {kopecks(side?.amount_kopecks)}{' '}
                <span className="muted">{rubles(side?.amount_kopecks)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {discrepancies.length === 0 ? (
        <div className="box ok">
          Расхождений нет: записи, суммы и итоги за {report.period} совпадают.
        </div>
      ) : (
        <DiscrepancyTable items={discrepancies} />
      )}
    </>
  )
}

function DiscrepancyTable({ items }: { items: Discrepancy[] }) {
  return (
    <table className="discrepancies">
      <thead>
        <tr>
          <th>Тип</th>
          <th>ID записи</th>
          <th>1С</th>
          <th>PostgreSQL</th>
          <th>Комментарий</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item, i) => (
          <tr key={i}>
            <td>{TYPE_LABELS[item.type] ?? item.type}</td>
            <td>
              <code>{item.record_id ?? 'итого'}</code>
            </td>
            <td>{describe(item.source)}</td>
            <td>{describe(item.target)}</td>
            <td>{item.message}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function describe(value: Discrepancy['source']) {
  if (!value) return <span className="muted">нет записи</span>
  if (value.count !== undefined)
    return (
      <>
        {value.count} шт., {kopecks(value.amount_kopecks)}
      </>
    )
  return (
    <>
      {kopecks(value.amount_kopecks)}
      <br />
      <span className="muted">
        счёт {value.account_id ?? '—'}, {value.period}
      </span>
    </>
  )
}

function ErrorBox({ title, text }: { title: string; text: string }) {
  return (
    <div className="box error" role="alert">
      <strong>{title}</strong>
      <div>{text}</div>
    </div>
  )
}
