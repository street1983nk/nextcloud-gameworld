// Escape in dialogs whose focus sits in a form field (B3, volltest 261102).
//
// NcModal (@nextcloud/vue 9.13.1) closes on Escape through useHotKey, which ignores every
// key event whose target is an input, textarea, select or contenteditable element. A
// dialog that opens with the focus in a field (invite search, first time window switch)
// therefore never closed with Escape. The dialog content calls escapeShouldClose in the
// capture phase and closes itself through its own close path; all other targets stay
// with NcModal, so nothing closes twice.

function isField(target) {
	if (!target || typeof target !== 'object') {
		return false
	}
	if (target.isContentEditable === true) {
		return true
	}
	const tag = String(target.tagName ?? '').toUpperCase()
	return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

// The select (vue-select) uses the first Escape itself: it closes its list or clears the search.
function selectUsesEscape(target) {
	const select = typeof target.closest === 'function' ? target.closest('.v-select') : null
	if (!select) {
		return false
	}
	return select.classList?.contains('vs--open') === true || String(target.value ?? '') !== ''
}

/** True if this keydown (capture phase) should close the dialog through its own close path. */
export function escapeShouldClose(event) {
	if (!event || event.key !== 'Escape' || event.defaultPrevented || event.isComposing) {
		return false
	}
	if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) {
		return false
	}
	const target = event.target
	if (!isField(target)) {
		return false
	}
	return !selectUsesEscape(target)
}
