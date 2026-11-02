// Check script for frontend/src/dialogKeys.js (without browser): node frontend/tests/dialogKeys.check.mjs
import assert from 'node:assert/strict'

const { escapeShouldClose } = await import('../src/dialogKeys.js')

// Minimal elements: tag, optional value, optional surrounding select with or without open list.
function element(tagName, { value = '', select = null, editable = false } = {}) {
	return {
		tagName,
		value,
		isContentEditable: editable,
		closest: (selector) => (selector === '.v-select' ? select : null),
	}
}
function select(open) {
	return { classList: { contains: (name) => name === 'vs--open' && open } }
}
function key(target, extra = {}) {
	return { key: 'Escape', target, defaultPrevented: false, isComposing: false, ...extra }
}

// Fields NcModal ignores: the dialog closes itself.
assert.equal(escapeShouldClose(key(element('INPUT'))), true, 'switch input')
assert.equal(escapeShouldClose(key(element('input'))), true, 'lower-case tag')
assert.equal(escapeShouldClose(key(element('TEXTAREA'))), true)
assert.equal(escapeShouldClose(key(element('SELECT'))), true)
assert.equal(escapeShouldClose(key(element('DIV', { editable: true }))), true)

// Select search: closed list and empty search closes; open list or typed text is the select's own Escape.
assert.equal(escapeShouldClose(key(element('INPUT', { select: select(false) }))), true, 'closed list')
assert.equal(escapeShouldClose(key(element('INPUT', { select: select(true) }))), false, 'open list first')
assert.equal(escapeShouldClose(key(element('INPUT', { select: select(false), value: 'mi' }))), false, 'search text first')

// Everything else stays with NcModal (no double close) or is no plain Escape.
assert.equal(escapeShouldClose(key(element('BUTTON'))), false, 'button: NcModal closes')
assert.equal(escapeShouldClose(key(element('DIV'))), false)
assert.equal(escapeShouldClose(key(element('INPUT'), { key: 'Enter' })), false)
assert.equal(escapeShouldClose(key(element('INPUT'), { key: 'Esc' })), false)
assert.equal(escapeShouldClose(key(element('INPUT'), { defaultPrevented: true })), false)
assert.equal(escapeShouldClose(key(element('INPUT'), { isComposing: true })), false, 'IME composition')
assert.equal(escapeShouldClose(key(element('INPUT'), { shiftKey: true })), false)
assert.equal(escapeShouldClose(key(element('INPUT'), { ctrlKey: true })), false)
assert.equal(escapeShouldClose(key(null)), false)
assert.equal(escapeShouldClose(null), false)
assert.equal(escapeShouldClose(undefined), false)

console.log('dialogKeys.check: ok')
