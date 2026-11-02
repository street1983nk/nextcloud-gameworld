// In-page probe (runs inside page.evaluate): horizontal scrolling of the page or
// of a scroll container, and clipped texts. Self-contained, no closures.
export function layoutProbe() {
	const doc = document.documentElement
	const out = { pageScroll: doc.scrollWidth > doc.clientWidth + 1, scrollers: [], clipped: [] }
	// Visually hidden helpers (e.g. the table head in the card view: 1 px, clip) do not count.
	const visible = (el) => {
		for (let node = el; node && node !== document.body; node = node.parentElement) {
			const r = node.getBoundingClientRect()
			const cs = getComputedStyle(node)
			if (r.width <= 2 || r.height <= 2 || (cs.clip && cs.clip !== 'auto') || (cs.clipPath && cs.clipPath !== 'none')) return false
		}
		return true
	}
	for (const el of document.querySelectorAll('main *, [role=dialog] *')) {
		if (!visible(el)) continue
		const cs = getComputedStyle(el)
		const over = el.scrollWidth > el.clientWidth + 1
		if (!over) continue
		if (/(auto|scroll)/.test(cs.overflowX) && el.clientWidth > 0) {
			out.scrollers.push({ tag: el.tagName, cls: String(el.className).slice(0, 80), sw: el.scrollWidth, cw: el.clientWidth })
		} else if ((cs.overflowX === 'hidden' || cs.textOverflow === 'ellipsis') && el.innerText?.trim()) {
			out.clipped.push({ tag: el.tagName, cls: String(el.className).slice(0, 80), text: el.innerText.trim().slice(0, 120), sw: el.scrollWidth, cw: el.clientWidth })
		}
	}
	// The page itself also counts when the app content scrolls sideways.
	const content = document.querySelector('#app-content, #app-content-vue, .app-content')
	if (content && content.scrollWidth > content.clientWidth + 1) out.pageScroll = true
	return out
}
