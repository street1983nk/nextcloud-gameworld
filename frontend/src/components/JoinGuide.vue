<!-- Anleitung in fünf Schritten für den Luanti-Client (Pattern 7). Werte nur per Textinterpolation. -->
<template>
	<div class="join-guide">
		<h4>So kommst du in die Welt</h4>
		<ol>
			<li>
				Installiere Luanti von
				<a href="https://www.luanti.org/downloads/" target="_blank" rel="noopener noreferrer">luanti.org</a>.
				Es gibt Luanti für Windows, macOS und Linux, für Android über Google Play oder F-Droid.
				Für iPhone und iPad gibt es keine offizielle Version.
			</li>
			<li>Öffne Luanti und wähle den Reiter zum Beitreten eines Servers.</li>
			<li>
				Trag als Adresse <strong>{{ host }}</strong> und als Port <strong>{{ port }}</strong> ein.
			</li>
			<li>
				Trag als Name <strong>{{ playerName }}</strong> und dein Passwort genau so ein.
				Groß- und Kleinschreibung zählt.
			</li>
			<li>
				Klick auf Beitreten. Beim ersten Mal lädt Luanti die Spieldateien,
				das kann bei „Abenteuer (sanft)“ etwas dauern.
			</li>
		</ol>
		<p class="join-guide__note">
			Ändere dein Passwort bitte nicht im Spiel; hier steht immer das gültige.
		</p>
	</div>
</template>

<script setup>
// Das Passwort selbst steht nur in der Karte (verdeckt, kopierbar), nicht im Anleitungstext.
defineProps({
	host: {
		type: String,
		required: true,
	},
	port: {
		type: Number,
		required: true,
	},
	playerName: {
		type: String,
		required: true,
	},
})
</script>

<style scoped>
.join-guide h4 {
	margin: 12px 0 4px;
}

.join-guide ol {
	padding-inline-start: 24px;
	list-style: decimal;
}

.join-guide li {
	margin-bottom: 6px;
}

.join-guide__note {
	color: var(--color-text-maxcontrast);
}
</style>
