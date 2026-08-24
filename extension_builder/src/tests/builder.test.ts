import assert from 'node:assert/strict'
import test from 'node:test'
import { resolve } from 'node:path'
import { compatibleDsh, compatibleNode, safeEntry, validSystemTools } from '../builder.js'

test('rejects entry paths escaping the package root', () => {
  const root = resolve('/tmp/extension')
  assert.equal(safeEntry(root, './dist/index.js'), resolve(root, 'dist/index.js'))
  assert.equal(safeEntry(root, '../../etc/passwd'), null)
})

test('checks the fixed Node 22.19 runtime contract', () => {
  assert.equal(compatibleNode('>=22.19 <23'), true)
  assert.equal(compatibleNode('>=20 <22'), false)
  assert.equal(compatibleNode('>=23'), false)
})

test('checks the fixed DSH runtime contract', () => {
  assert.equal(compatibleDsh('0.1.0-rc.5'), true)
  assert.equal(compatibleDsh('>=0.1.0-rc.5 <0.2.0'), true)
  assert.equal(compatibleDsh('>=0.2.0'), false)
})

test('system tool declarations require schema, risk and side-effect metadata', () => {
  assert.equal(validSystemTools([{ name: 'lookup', description: 'lookup', input_schema: {
    type: 'object', properties: {},
  }, risk_level: 'low', required_platform_capabilities: [], side_effects: false }]), true)
  assert.equal(validSystemTools([{ name: 'lookup', description: 'lookup' }]), false)
})
