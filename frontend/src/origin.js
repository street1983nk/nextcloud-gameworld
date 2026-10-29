// Confirmation question about the link address of notifications (WR-04, owner 22.10.2026:
// "Erste merken, Wechsel nur bestätigt"). Pure except for the storage, checkable
// with node frontend/tests/origin.check.mjs.
//
// The server decides: it stores only the first address, a different one only
// with confirm, and never replaces https with http (then no question at all).
// The page asks only when the response reports confirm_needed and this new
// address has not already been answered with "Nein" in this browser.

export const DISMISS_KEY = 'gameworld.origin.dismissed'

// Response of POST /api/origin -> { current, proposed } for the question, otherwise null.
export function originQuestion(result, dismissed) {
	if (!result || result.confirm_needed !== true) {
		return null
	}
	if (typeof result.proposed !== 'string' || typeof result.origin !== 'string') {
		return null
	}
	if (result.proposed === dismissed) {
		return null
	}
	return { current: result.origin, proposed: result.proposed }
}

export function readDismissed(storage) {
	try {
		return storage?.getItem(DISMISS_KEY) ?? null
	} catch {
		return null
	}
}

export function rememberDismissed(storage, proposed) {
	try {
		storage?.setItem(DISMISS_KEY, proposed)
	} catch {
		// Without storage the page asks again on the next visit, nothing more happens.
	}
}
