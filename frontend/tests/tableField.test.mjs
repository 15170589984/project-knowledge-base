import assert from 'node:assert/strict'
import test from 'node:test'
import { createTable, parseTable, resizeTable, serializeTable } from '../src/tableField.js'

test('resizing a table preserves overlapping cells', () => {
  const rows = createTable(2, 2)
  rows[0][0] = '地址'
  rows[1][0] = 'https://example.test'
  const resized = resizeTable(rows, 3, 3)
  assert.equal(resized[0][0], '地址')
  assert.equal(resized[1][0], 'https://example.test')
  assert.equal(resized[2][2], '')
  assert.deepEqual(parseTable(serializeTable(resized)), resized)
})

test('malformed tables remain visible as invalid instead of empty', () => {
  assert.equal(parseTable('{"rows":[["a"],["b","c"]]}'), null)
})
