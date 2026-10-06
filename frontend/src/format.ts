// Суммы приходят целыми копейками; форматируем без дробной арифметики.
const group = (value: number) => value.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')

export function kopecks(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${group(value)} коп.`
}

export function rubles(value: number | null | undefined): string {
  if (value === null || value === undefined) return ''
  const sign = value < 0 ? '−' : ''
  const abs = Math.abs(value)
  const rub = (abs - (abs % 100)) / 100
  const kop = (abs % 100).toString().padStart(2, '0')
  return `${sign}${group(rub)},${kop} ₽`
}
