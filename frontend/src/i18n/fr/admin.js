// Area "admin" (fr). Filled by plan 06-20 (TalkRoomStatus, OrphanSection, VerwalterGroupsSection, SetupCheck, JoinHostSettings, ReviewSetting, TimeZoneSetting).
// Flat table: every key starts with "admin."; values are plain text, never HTML.
// French typography: a no-break space (\u00a0) before ? ! ; : and inside « ».
export default {
	// Shared by several admin components
	'admin.common.cancel': 'Annuler',
	'admin.common.save': 'Enregistrer',

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

	// SetupCheck.vue
	'admin.setup.notReady': 'Gameworld n’est pas encore prêt',
	'admin.setup.unreachable': 'Gameworld ne répond pas. Vérifie l’application dans les paramètres de Nextcloud.',
	'admin.setup.proxyWarning': 'Avertissement de sécurité sur le proxy Docker',
	'admin.setup.recheck': 'Vérifier à nouveau',
	'admin.setup.commandsHeading': 'Créer le proxy Docker en une commande',
	'admin.setup.commandsHint': 'Exécute la commande correspondante sur le serveur avec un utilisateur qui a les droits Docker, puis choisis «\u00a0Vérifier à nouveau\u00a0». Elle crée le conteneur gameworld-docker-proxy avec exactement les réglages du guide, sans port sur l’hôte. Si un conteneur porte déjà ce nom, supprime-le d’abord avec docker rm -f gameworld-docker-proxy. Avec ton propre fichier Compose, le réseau gameworld doit déjà exister (il est créé par le fichier Compose de HaRP).',
	'admin.setup.commandCompose': 'Ton propre fichier Compose avec HaRP (réseau gameworld)',
	'admin.setup.commandAio': 'Nextcloud All-in-One (réseau nextcloud-aio)',
	'admin.setup.copyCommand': 'Copier la commande',
	'admin.setup.copied': 'Copié',
	'admin.setup.copyFailed': 'La copie n’a pas fonctionné. Sélectionne la commande et copie-la à la main.',

	// JoinHostSettings.vue
	'admin.joinHost.title': 'Paramètres',
	'admin.joinHost.label': 'Adresse de jeu',
	'admin.joinHost.helper': 'Laisse vide\u00a0: Gameworld utilise l’adresse à laquelle tu ouvres Nextcloud en ce moment.',
	'admin.joinHost.effective': 'Les joueurs voient cette adresse\u00a0:',
	'admin.joinHost.loopback': 'Les autres appareils ne peuvent pas joindre cette adresse. Saisis l’adresse du serveur domestique sur le réseau local.',
	'admin.joinHost.internet': 'Cela ressemble à une adresse Internet. Les jeux passent par UDP et non par un tunnel web\u00a0; saisis l’adresse du serveur domestique sur le réseau local.',
	'admin.joinHost.saved': 'Enregistré. Les joueurs verront la nouvelle adresse à la prochaine actualisation.',

	// ReviewSetting.vue
	'admin.review.title': 'Récap du jour le soir',
	'admin.review.hint': 'S’applique uniquement à toi. Sans temps de jeu ce jour-là, aucun message n’est envoyé.',
	'admin.review.time': 'Heure',
	'admin.review.unsaved': 'Pas encore enregistré.',
	'admin.review.loadError': 'Impossible de charger le réglage\u00a0: {error}',
	'admin.review.savedAt': 'Enregistré. Le récap arrive à {time}.',
	'admin.review.savedOff': 'Enregistré. Tu ne reçois pas de récap du jour.',

	// TimeZoneSetting.vue
	'admin.timeZone.title': 'Fuseau horaire pour les temps de jeu',
	'admin.timeZone.hint': 'Les temps de jeu, les plages horaires et les vacances s’appliquent dans ce fuseau horaire.',
	'admin.timeZone.useBrowser': 'Utiliser le fuseau horaire de ce navigateur',
	'admin.timeZone.browserUses': 'Ce navigateur utilise {zone}.',
	'admin.timeZone.savedLater': 'Enregistré. Les mondes injoignables pour l’instant appliqueront le fuseau horaire à leur prochain démarrage.',
	'admin.timeZone.saved': 'Enregistré. Les temps de jeu sont désormais calculés dans ce fuseau horaire.',
}
