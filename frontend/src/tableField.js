export function createTable(rowCount = 2, columnCount = 3) {
  return Array.from({ length: rowCount }, () => Array.from({ length: columnCount }, () => ''))
}

export function parseTable(value) {
  if (!value) return null
  try {
    const data = JSON.parse(value)
    if (!Array.isArray(data.rows) || !data.rows.length || !Array.isArray(data.rows[0])) return null
    const width = data.rows[0].length
    if (!width || data.rows.some((row) => !Array.isArray(row) || row.length !== width || row.some((cell) => typeof cell !== 'string'))) return null
    return data.rows
  } catch {
    return null
  }
}

export function resizeTable(rows, rowCount, columnCount) {
  return Array.from({ length: rowCount }, (_, row) =>
    Array.from({ length: columnCount }, (_, column) => rows[row]?.[column] || ''),
  )
}

export function serializeTable(rows) {
  return JSON.stringify({ rows })
}
