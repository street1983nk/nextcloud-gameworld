// Area "kids" (fr). Filled by plan 06-21 (App.vue, player views, playtime and window components).
// Flat table: every key starts with "kids."; values are plain text, never HTML.
// French typography: a no-break space (\u00a0) before ? ! ; : and inside « ».
// Texts children read themselves (player, connection, guide, playtime card) use short, simple sentences.
export default {
	'kids.common.back': 'Retour à l’aperçu',

	'kids.app.loadFailed': 'Gameworld n’a pas pu être chargé. Recharge la page, s’il te plaît.',
	'kids.app.originQuestion': 'Ouvrir désormais les liens des notifications avec cette adresse\u00a0?',
	'kids.app.originCurrent': 'Jusqu’ici\u00a0:',
	'kids.app.originProposed': 'Nouvelle\u00a0:',
	'kids.app.originYes': 'Oui, cette adresse',
	'kids.app.originNo': 'Non',

	'kids.player.title': 'Mes mondes',
	'kids.player.hello': 'Salut {name}\u00a0!',
	'kids.player.emptyName': 'Tu n’as encore aucune invitation pour un monde',
	'kids.player.emptyDescription': 'Quand tes parents t’invitent dans un monde, tu verras ici comment y entrer.',

	'kids.connection.play': 'Jouer dans le navigateur',
	'kids.connection.playFailed': 'Le jeu n’a pas pu démarrer dans le navigateur. {detail}',
	'kids.connection.address': 'Adresse',
	'kids.connection.port': 'Port',
	'kids.connection.playerName': 'Nom de joueur',
	'kids.connection.password': 'Mot de passe',
	'kids.connection.maskedLabel': 'Mot de passe caché',
	'kids.connection.masked': 'Mot de passe\u00a0: ••••-••••-••••',
	'kids.connection.hide': 'Masquer',
	'kids.connection.show': 'Afficher',
	'kids.connection.copied': 'Copié',
	'kids.connection.copyPassword': 'Copier le mot de passe',
	'kids.connection.copyFailed': 'Copier ne marche pas dans ce navigateur. Clique sur Afficher et recopie le mot de passe.',

	'kids.guide.title': 'Comment entrer dans le monde',
	'kids.guide.install': 'Installe Luanti depuis {site}.',
	'kids.guide.platforms': 'Luanti marche sous Windows, macOS et Linux. Pour Android, tu le trouves sur Google Play ou F-Droid.',
	'kids.guide.noIos': 'Il n’y a pas de version officielle pour iPhone et iPad.',
	'kids.guide.openTab': 'Ouvre Luanti et choisis l’onglet «\u00a0Join Game\u00a0».',
	'kids.guide.address': 'Écris {host} dans Address et {port} dans Port.',
	'kids.guide.name': 'Écris {name} dans Name et ton mot de passe dans Password, exactement comme ici.',
	'kids.guide.case': 'Les majuscules et les minuscules comptent.',
	'kids.guide.join': 'Clique sur Login. La première fois, Luanti charge les fichiers du jeu. Avec «\u00a0Aventure (douce)\u00a0», ça peut prendre un moment.',
	'kids.guide.note': 'Ne change pas ton mot de passe dans le jeu, s’il te plaît. Le bon mot de passe est toujours ici.',

	'kids.playtimeCard.title': 'Ton temps de jeu aujourd’hui',

	'kids.pause.title': 'Pause pour tous les enfants',
	'kids.pause.warning': 'Après un avertissement de 30 secondes, tous les enfants sont déconnectés. Les gestionnaires restent dans le monde.',
	'kids.pause.notCounted': 'La pause ne compte pas dans le temps de jeu. Les plages horaires des mondes continuent.',
	'kids.pause.minutes.one': '{count} minute',
	'kids.pause.minutes.other': '{count} minutes',
	'kids.pause.stopToday': 'Fini pour aujourd’hui',
	'kids.pause.stoppedToday': 'C’est fini pour aujourd’hui. Les enfants pourront rejouer demain.',
	'kids.pause.resume': 'Reprendre',
	'kids.pause.restarted': 'Le monde {name} a redémarré pour que la pause s’applique bien.',
	'kids.pause.later': 'Le monde {name} appliquera la pause à son prochain démarrage.',

	'kids.review.title': 'Récap du jour',
	'kids.review.empty': 'Personne n’a joué ce jour-là.',
	'kids.review.limitReached': '(limite atteinte)',
	'kids.review.worldMinutes': '{world}\u00a0: {minutes}',
	'kids.review.hint': 'Seuls les enfants avec des règles de temps de jeu définies ici sont comptés.',

	'kids.attempts.title': 'Tentatives de connexion',
	'kids.attempts.intro': 'Seuls les comptes Nextcloud invités entrent dans Gameworld. Pour laisser quelqu’un jouer avec toi, invite son compte Nextcloud.',
	'kids.attempts.emptyToday': 'Aucune tentative de connexion aujourd’hui.',
	'kids.attempts.emptyDay': 'Aucune tentative de connexion ce jour-là.',
	'kids.attempts.repeated': ', plusieurs fois',
	'kids.attempts.invite': 'Inviter quelqu’un',
	'kids.attempts.inviteWorld': 'Inviter quelqu’un\u00a0: {name}',
}
