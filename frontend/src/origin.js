// Rückfrage zur Link-Adresse der Benachrichtigungen (WR-04, Owner 22.10.2026:
// "Erste merken, Wechsel nur bestätigt"). Rein bis auf den Speicher, prüfbar
// mit node frontend/tests/origin.check.mjs.
//
// Der Server entscheidet: Er speichert nur die erste Adresse, eine abweichende
// erst mit confirm, und ersetzt https nie durch http (dann gar keine Rückfrage).
// Die Seite fragt nur, wenn die Antwort confirm_needed meldet und diese neue
// Adresse in diesem Browser nicht schon mit "Nein" beantwortet wurde.

export const DISMISS_KEY = 'gameworld.origin.dismissed'

// Antwort von POST /api/origin -> { current, proposed } für die Rückfrage, sonst null.
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
		// Ohne Speicher fragt die Seite beim nächsten Besuch erneut, mehr passiert nicht.
	}
}
