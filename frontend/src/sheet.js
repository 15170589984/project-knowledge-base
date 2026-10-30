export const SHEET_LIMITS = { rows: 200, columns: 30 }

export function createSheet(rowCount = 20, columnCount = 10) {
  return Array.from({ length: rowCount }, () => Array.from({ length: columnCount }, () => ''))
}

export function parseSheet(value) {
  if (!value) return null
  try {
    const data = JSON.parse(value)
    const rows = data?.rows
    if (!Array.isArray(rows) || !rows.length || !Array.isArray(rows[0])) return null
    const width = rows[0].length
    if (!width) return null
    if (rows.length > SHEET_LIMITS.rows || width > SHEET_LIMITS.columns) return null
    if (rows.some((row) => !Array.isArray(row) || row.length !== width || row.some((cell) => typeof cell !== 'string'))) return null
    return rows
  } catch {
    return null
  }
}

export function serializeSheet(rows) {
  return JSON.stringify({ rows })
}

export function columnLabel(index) {
  let label = ''
  let value = index + 1
  while (value > 0) {
    const remainder = (value - 1) % 26
    label = String.fromCharCode(65 + remainder) + label
    value = Math.floor((value - 1) / 26)
  }
  return label
}

export function parseClipboardGrid(text) {
  const lines = text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n')
  return lines.map((line) => line.split('\t'))
}
