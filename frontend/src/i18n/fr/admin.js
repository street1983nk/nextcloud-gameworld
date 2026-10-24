// Area "admin" (fr). Filled by plan 06-20 (TalkRoomStatus, OrphanSection, VerwalterGroupsSection, SetupCheck, JoinHostSettings, ReviewSetting, TimeZoneSetting).
// Flat table: every key starts with "admin."; values are plain text, never HTML.
// French typography: a no-break space (\u00a0) before ? ! ; : and inside « ».
export default {
	// Shared by several admin components
	'admin.common.cancel': 'Annuler',

	// VerwalterGroupsSection.vue
	'admin.groups.title': 'Groupes de gestionnaires',
	'admin.groups.alwaysIncluded': 'toujours inclus',
	'admin.groups.removeLabel': 'Retirer le groupe {gid}',
	'admin.groups.remove': 'Retirer',
	'admin.groups.groupLabel': 'Groupe',
	'admin.groups.placeholder': 'Saisis un nom de groupe',
	'admin.groups.add': 'Ajouter le groupe',

	// OrphanSection.vue
	'admin.orphans.title': 'Restes d’installations précédentes',
	'admin.orphans.chipContainer': 'Conteneur',
	'admin.orphans.chipVolume': 'Données de monde',
	'admin.orphans.removeContainerLabel': 'Supprimer le conteneur {name}',
	'admin.orphans.deleteVolumeLabel': 'Supprimer définitivement les données de monde {name}',
	'admin.orphans.remove': 'Supprimer',
	'admin.orphans.delete': 'Supprimer',
	'admin.orphans.rescanLabel': 'Rechercher à nouveau les restes',
	'admin.orphans.rescan': 'Rechercher à nouveau',
	'admin.orphans.docsLink': 'Guide du script de nettoyage',
	'admin.orphans.removeContainer': 'Supprimer le conteneur',
	'admin.orphans.deleteVolumeTitle': 'Supprimer définitivement les données de monde',
	'admin.orphans.deleteVolume': 'Supprimer définitivement',

	// TalkRoomStatus.vue
	'admin.talk.open': 'Ouvrir le salon Talk',
	'admin.talk.readOnly': 'Lecture seule',
	'admin.talk.pending': 'Le salon Talk est en cours de création',
	'admin.talk.recreate': 'Recréer le salon',
	'admin.talk.recreateTitle': 'Recréer le salon Talk',
	'admin.talk.savedLater': 'Enregistré. Talk l’appliquera à la prochaine synchronisation.',
}
