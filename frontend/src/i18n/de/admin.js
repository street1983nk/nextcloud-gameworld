// Area "admin" (de). Filled by plan 06-20 (TalkRoomStatus, OrphanSection, VerwalterGroupsSection, SetupCheck, JoinHostSettings, ReviewSetting, TimeZoneSetting).
// Flat table: every key starts with "admin."; values are plain text, never HTML.
export default {
	// Shared by several admin components
	'admin.common.cancel': 'Abbrechen',

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
}
