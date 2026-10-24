// Area "admin" (de). Filled by plan 06-20 (TalkRoomStatus, OrphanSection, VerwalterGroupsSection, SetupCheck, JoinHostSettings, ReviewSetting, TimeZoneSetting).
// Flat table: every key starts with "admin."; values are plain text, never HTML.
export default {
	// Shared by several admin components
	'admin.common.cancel': 'Abbrechen',
	'admin.common.save': 'Speichern',

	// VerwalterGroupsSection.vue
	'admin.groups.title': 'Verwalter-Gruppen',
	'admin.groups.alwaysIncluded': 'immer dabei',
	'admin.groups.removeLabel': 'Gruppe {gid} entfernen',
	'admin.groups.remove': 'Entfernen',
	'admin.groups.groupLabel': 'Gruppe',
	'admin.groups.placeholder': 'Gruppenname eingeben',
	'admin.groups.add': 'Gruppe hinzufügen',

	// OrphanSection.vue
	'admin.orphans.title': 'Reste früherer Installationen',
	'admin.orphans.chipContainer': 'Container',
	'admin.orphans.chipVolume': 'Spielstand',
	'admin.orphans.removeContainerLabel': 'Container {name} entfernen',
	'admin.orphans.deleteVolumeLabel': 'Spielstand {name} endgültig löschen',
	'admin.orphans.remove': 'Entfernen',
	'admin.orphans.delete': 'Löschen',
	'admin.orphans.rescanLabel': 'Reste erneut suchen',
	'admin.orphans.rescan': 'Erneut suchen',
	'admin.orphans.docsLink': 'Anleitung zum Aufräum-Skript',
	'admin.orphans.removeContainer': 'Container entfernen',
	'admin.orphans.deleteVolumeTitle': 'Spielstand endgültig löschen',
	'admin.orphans.deleteVolume': 'Endgültig löschen',

	// TalkRoomStatus.vue
	'admin.talk.open': 'Talk-Raum öffnen',
	'admin.talk.readOnly': 'Nur lesen',
	'admin.talk.pending': 'Talk-Raum wird eingerichtet',
	'admin.talk.recreate': 'Raum neu anlegen',
	'admin.talk.recreateTitle': 'Talk-Raum neu anlegen',
	'admin.talk.savedLater': 'Gespeichert. Talk übernimmt es beim nächsten Abgleich.',

	// SetupCheck.vue
	'admin.setup.notReady': 'Gameworld ist noch nicht startklar',
	'admin.setup.unreachable': 'Gameworld antwortet nicht. Bitte die App in den Nextcloud-Einstellungen prüfen.',
	'admin.setup.proxyWarning': 'Sicherheitshinweis zum Docker-Proxy',
	'admin.setup.recheck': 'Erneut prüfen',

	// JoinHostSettings.vue
	'admin.joinHost.title': 'Einstellungen',
	'admin.joinHost.label': 'Adresse für Spieler',
	'admin.joinHost.helper': 'Leer lassen: Gameworld nimmt die Adresse, unter der du Nextcloud gerade öffnest.',
	'admin.joinHost.effective': 'Spieler sehen als Adresse:',
	'admin.joinHost.loopback': 'Andere Geräte erreichen diese Adresse nicht. Trag die Adresse des Heimservers im Heimnetz ein.',
	'admin.joinHost.internet': 'Das sieht nach einer Internetadresse aus. Spiele laufen über UDP und nicht durch einen Web-Tunnel; trag die Adresse des Heimservers im Heimnetz ein.',
	'admin.joinHost.saved': 'Gespeichert. Spieler sehen die neue Adresse beim nächsten Aktualisieren.',

	// ReviewSetting.vue
	'admin.review.title': 'Tagesrückblick am Abend',
	'admin.review.hint': 'Gilt nur für dich. Ohne Spielzeit an dem Tag kommt keine Nachricht.',
	'admin.review.time': 'Uhrzeit',
	'admin.review.unsaved': 'Noch nicht gespeichert.',
	'admin.review.loadError': 'Die Einstellung konnte nicht geladen werden: {error}',
	'admin.review.savedAt': 'Gespeichert. Der Rückblick kommt um {time}.',
	'admin.review.savedOff': 'Gespeichert. Du bekommst keinen Tagesrückblick.',

	// TimeZoneSetting.vue
	'admin.timeZone.title': 'Zeitzone für Spielzeiten',
	'admin.timeZone.hint': 'Spielzeiten, Zeitfenster und Ferien gelten in dieser Zeitzone.',
	'admin.timeZone.useBrowser': 'Zeitzone dieses Browsers übernehmen',
	'admin.timeZone.browserUses': 'Dieser Browser nutzt {zone}.',
	'admin.timeZone.savedLater': 'Gespeichert. Welten, die gerade nicht erreichbar sind, übernehmen die Zeitzone beim nächsten Start.',
	'admin.timeZone.saved': 'Gespeichert. Die Spielzeiten rechnen ab sofort in dieser Zeitzone.',
}
