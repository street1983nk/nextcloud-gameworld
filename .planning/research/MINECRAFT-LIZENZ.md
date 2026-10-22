# Minecraft-Lizenzprüfung für Gameworld v2

**Frage des Owners:** Erlaubt die Minecraft-Lizenz, dass Gameworld (kostenlose AGPL-ExApp im Nextcloud App Store) auf dem Heimserver einer Familie einen Minecraft-Java-Server per docker-py startet?
**Recherchiert:** 22.10.2026, alle Primärquellen live abgerufen (maxAge 0)
**Ergänzt:** `MINECRAFT-V2.md` (Machbarkeit, 21.10.2026); dieser Bericht ist die vertiefte Rechtsprüfung
**Keine Rechtsberatung.** Mojang sagt selbst: "We are not able to give advice about whether a specific project does or does not comply with these guidelines. If you are unsure, you should speak to an attorney for help." (https://www.minecraft.net/en-us/usage-guidelines)

Konfidenz: **HIGH** = Wortlaut der Primärquelle trägt die Aussage direkt. **MEDIUM** = Primärquelle plus Auslegung oder gelebte Praxis. **LOW** = Einzelquelle, nicht primär oder unverifiziert.

---

## Gesamturteil

| Teilfrage | Antwort | Konfidenz |
|---|---|---|
| Server automatisch von Mojang herunterladen und starten | **erlaubt mit Auflagen** (Zustimmung des Betreibers vorher, nur offizielle Quelle) | HIGH für Wortlaut, MEDIUM für die Übertragung auf eine App |
| server.jar mitliefern / im Image bündeln / umverteilen | **nicht erlaubt** | HIGH |
| Paper-/Fabric-Jar mitliefern | **nicht erlaubt** (Modded Version); Laden zur Laufzeit beim Betreiber erlaubt | HIGH für Verbot, MEDIUM für Laufzeitmuster |
| "Minecraft" im App-Namen | **nicht erlaubt** als Haupt- oder dominanter Name; als beschreibender Zusatz erlaubt | HIGH |
| Logo, Schrift, Texturen, Creeper im Branding | **nicht erlaubt** | HIGH |
| offline-mode (Cracked) anbieten | **nicht erlaubt** | HIGH |
| Spenden für Gameworld als Software | **erlaubt mit Auflagen** (kein Mojang-Material verkaufen) | MEDIUM |
| Pro-Version, deren Mehrwert Minecraft ist | **rechtlich unklar, Risiko**; nicht empfohlen | LOW bis MEDIUM |
| Bedrock Dedicated Server | **erlaubt mit denselben Auflagen**; Konsolen technisch ausgeschlossen | HIGH |
| Eigene Plugins/Mods verteilen | **erlaubt** (ohne nennenswerten Mojang-Code, kostenlos) | HIGH |

**Kurz:** Minecraft Java in Gameworld ist **erlaubt mit Auflagen**. Gameworld darf Werkzeug sein, aber nie Verteiler von Mojang-Software, nie offiziell wirken und nie offline-mode anbieten.

---

## 1. Automatischer Download und Start, Mitliefern

### Befund

**EULA, Server ausdrücklich erlaubt** (HIGH)
https://www.minecraft.net/en-us/eula
> "When you buy our games, that means you can download, install, and play them. For the server version of Minecraft: Java Edition, you can install it on a server and host online play."

**EULA, Tools von Dritten erlaubt** (HIGH)
https://www.minecraft.net/en-us/eula (Summary)
> "You may develop tools, plug-ins and services as long as they do not seem official or approved by us, such as by using our logos."

**EULA, Verbreitungsverbot** (HIGH)
https://www.minecraft.net/en-us/eula
> "However, you must not distribute anything we've made unless we specifically agree to it. By "distribute anything we've made" what we mean is: give copies of our game software or content to anyone else; make commercial use of anything we've made; try to make money from anything we've made; or let other people get access to anything we've made in a way that is unfair or unreasonable."

**EULA, nur autorisierte Downloadquelle** (HIGH)
https://www.minecraft.net/en-us/eula (Abschnitt "Using mods")
> "In order to ensure the integrity of our games, we need all game downloads and updates to come from a source that we authorize."

**Usage Guidelines, Essential guidelines** (HIGH)
https://www.minecraft.net/en-us/usage-guidelines
> "Do **not** redistribute our games or any alterations of our games or game files"

**Downloadseite: Zustimmung durch Herunterladen** (HIGH)
https://www.minecraft.net/en-us/download/server (Stand heute: minecraft_server.26.3, Link auf piston-data.mojang.com)
> "Just so you know, by downloading any of the software on this page, you agree to the Minecraft End User License Agreement and Privacy Policy."
> "Yes, the official Minecraft server software for both **Java and Bedrock** is free to download from the Minecraft website."

**Gelebte Praxis itzg/docker-minecraft-server** (MEDIUM, keine Mojang-Quelle)
https://docker-minecraft-server.readthedocs.io/en/latest/
> "This docker image provides a Minecraft Server that will automatically download the latest stable version at startup."
> "Be sure to always include `-e EULA=TRUE` in your commands and container definitions, as Mojang/Microsoft requires EULA acceptance."
> "By default, the container will download the latest version of the "vanilla" Minecraft: Java Edition server provided by Mojang."

Weitere Praxis: kommerzielle Panels wie CubeCoders AMP verkaufen Lizenzen ("Lifetime Licence: $40 USD", https://cubecoders.com/AMP) und verwalten Minecraft-Server; Hoster wie Nitrado vermieten Minecraft-Server. Mojang verlinkt auf seiner Downloadseite eine eigene Serverliste (findmcserver.com). Ich habe **keine** schriftliche Mojang-Erlaubnis gefunden, die diese Panels namentlich deckt; ihre Duldung über viele Jahre ist ein Indiz, kein Beleg. (MEDIUM)

### Auslegung
- Gameworld selbst enthält und verteilt kein Mojang-Material, wenn der Container das Jar erst auf der Maschine des Betreibers von Mojangs Servern lädt. Das ist das itzg-Muster und entspricht "source that we authorize". (MEDIUM)
- **Mitliefern ist eindeutig verboten:** kein server.jar im ExApp-Image, in einem eigenen Gameworld-Image, einer Registry, einem Cache-Mirror oder in Welt-Backups, die Gameworld zentral anbietet. (HIGH)
- Ein Cache des Jars auf dem Rechner desselben Betreibers (z. B. Docker-Volume, das mehrere Welten derselben Familie teilen) ist keine Weitergabe an "anyone else". (MEDIUM)

## 2. Wer stimmt der EULA zu und wie in der UI

### Befund
**Zustimmung entsteht beim Download** (HIGH), siehe Zitat Downloadseite oben. Die Bedrock-Downloadseite verlangt eine aktive Checkbox (HIGH):
https://www.minecraft.net/en-us/download/server/bedrock
> "I agree to the Minecraft End User License Agreement and Privacy Policy"
https://help.minecraft.net/hc/en-us/articles/4408873961869-Download-Dedicated-Minecraft-Server-Software
> "Check the **Minecraft End User License Agreement and Privacy Policy** box."

**Der Server startet nicht ohne eula=true** (MEDIUM, Sekundärquelle)
https://minecraft.wiki/w/Tutorial:Setting_up_a_Java_Edition_server
> "A file called eula.txt will be generated after you run the server for the first time. Open it in a text editor and change eula=false to eula=true. If you don't do this, the server will shut down immediately when you try to start it."

**Dialoge nicht verstecken** (HIGH, steht im Monetarisierungsabschnitt, gilt dort für alle Server mit Einnahmen)
https://www.minecraft.net/en-us/usage-guidelines (Servers and hosting)
> "You don't hide or alter any of the dialogs or prompts that are part of Minecraft (this includes the End User License Agreement (EULA), warning messages, and error messages)"

**Minderjährige: Eltern akzeptieren für das Kind** (HIGH)
https://www.minecraft.net/en-us/eula (Introduction)
> "If you are a minor ... your parent or legal guardian is responsible for the creation of your Microsoft account and the acceptance all terms on your behalf."

**Microsoft Services Agreement** (HIGH, Stand "Effective: September 30, 2026")
https://www.microsoft.com/en-us/servicesagreement
> "If you are the parent or legal guardian of a minor, you and the minor accept and agree to be bound by these Terms and are responsible for all use of the Microsoft account or Services"

### Auslegung (MEDIUM)
- Zustimmen muss die Person, die den Server betreibt und den Download auslöst: der Nextcloud-Verwalter bzw. das Elternteil, das die Welt anlegt. Gameworld (der Entwickler) kann nicht stellvertretend zustimmen; ein fest eingebautes `EULA=TRUE` wäre genau das.
- Die Form der Checkbox schreibt Mojang nicht vor. Das Bedrock-Vorbild (aktive Checkbox mit Link auf EULA und Privacy Policy, Download erst danach) ist der sicherste Maßstab. Ein vorab gesetzter Haken ist nach EU-Verbraucherrecht für Einwilligungen ohnehin problematisch; ob das für eine Lizenzzustimmung zwingend gilt, habe ich nicht geprüft.
- Kinder als Spieler stimmen nicht in Gameworld zu; das passiert über ihr Microsoft-Konto durch die Eltern.

## 3. Name, Logo, Screenshots

### Befund
**Naming guidelines** (HIGH)
https://www.minecraft.net/en-us/usage-guidelines
> "You may use the Minecraft name in a secondary name, secondary title, or description if you: Do so because it is necessary to describe your creations or their purpose honestly and fairly; Ensure that the secondary title (which includes a Minecraft name) is not the dominant element or the distinctive part of the complete name or title; Don't use any other aspect of any of our brand or assets as part of any related branding, including as a logo or part of a logo; Don't use our name as keywords or search tags for products that have no relationship with them"
> "You may not use the Minecraft name as the primary or dominant name or title."
> "“Minecraft , the ultimate help app” (we’re not cool with this)"

**Definition Brand und Assets** (HIGH)
> "Our brand, we mean any names, related logos, fonts, textures, and any other distinctive characteristics of any part of our name and games"
> "Our assets, we mean the code, software, graphics, textures, images, models, sounds and other audio from any of our games and any videos or screenshots taken from our games"

**Pflicht-Disclaimer und Verantwortlichkeit** (HIGH)
> "Do **not** do anything or include anything that makes people think that what you are sharing could be interpreted as official or approved by, endorsed by, associated with, supported by, or connected to us"
> "Whom to contact about the product, service, or any related purchases and the contact method (chat and forum links are not acceptable methods)"
> "Prominently include the disclaimer similar to the following: “NOT AN OFFICIAL MINECRAFT [PRODUCT/SERVICE/EVENT/etc.]. NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT” on your product, listing, description, website/webpage, and all other related materials."

**Screenshots** (HIGH für die Erlaubnis bei Videos/Streams, MEDIUM für Store-Bilder)
> "You are allowed to create, use, and share videos, streams, and screenshots of you playing or using Minecraft."

Eigene "Brand Guidelines" gibt es nicht mehr separat: https://www.minecraft.net/en-us/brand-guidelines liefert 404 (22.10.2026). Mojang hat sie am 02.08.2023 in die Usage Guidelines überführt (HIGH):
https://www.minecraft.net/en-us/article/minecraft-eula-and-commercial-usage-guidelines-updates
> "we have decided to merge the different guidelines into a brand-new Minecraft Usage Guidelines."

### Auslegung
- App-Name "Gameworld" bleibt. Erlaubt als Beschreibung z. B. "Private Spielwelten für Luanti und Minecraft: Java Edition". Nicht: "Gameworld for Minecraft" als Titel, "MineWorld", "Minecraft Family Server". (HIGH)
- Icon, Farben, Schrift: nichts Blockiges im Minecraft-Stil, kein Grasblock, kein Creeper. (HIGH)
- Store-Screenshots: nur Gameworld-UI. Spielszenen sind laut Guidelines als Screenshots grundsätzlich erlaubt, aber im Store-Listing erhöhen sie den Eindruck "offiziell" und enthalten Texturen; daher weglassen. (MEDIUM)
- Kontaktweg im Listing: E-Mail oder Issue-Tracker, nicht nur Discord/Forum. (HIGH)

## 4. Monetarisierung

### Befund
**Commercial use umfasst auch Kostenloses** (HIGH)
https://www.minecraft.net/en-us/usage-guidelines
> "In these guidelines, commercial use means any uses of our name, brand, or assets that you use and share with others (regardless of whether you receive payment or provide it for free)."
> "When you decide to share your content with the community (whether you plan to make money off it or not), you are doing what we consider to be a commercial thing."

**Server-Monetarisierung** (HIGH) gilt für den Betreiber eines Servers, also die Familie:
> "Asking for donations, so long as you don’t offer the donor something that only they can use However, you may offer all players server wide rewards if donation goals are met."
> "The cost to access the server is the same for everyone"
> "You make it clear that you are responsible for all end user data privacy and protection requirements"

**Zielgruppe** (HIGH)
> "The allowances we give in these guidelines do **not** authorize commercial companies, corporate brands, advertising agencies, non-profits, politicians, political action committees, governments to use or exploit Minecraft for promoting products, services, or agendas unrelated to Minecraft."

**EULA-Verbot** (HIGH): "try to make money from anything we've made" (siehe Abschnitt 1).

### Auslegung
- **Spenden für Gameworld** (GitHub Sponsors o. ä.) vergüten eigene Software, nicht Mojang-Material. Mit den Regeln vereinbar, solange Spenden nicht mit Minecraft beworben werden und keine Minecraft-Vorteile freischalten. (MEDIUM)
- **Pro-Version:** Kommerzielle Panels (AMP) existieren seit Jahren, das spricht für Duldung bei reinen Verwaltungstools. Eine Pro-Version, deren Verkaufsargument Minecraft ist ("Minecraft nur in Pro"), kommt aber nah an "try to make money from anything we've made" und an die Naming-Regeln. Keine Primärquelle erlaubt das ausdrücklich. Empfehlung: Minecraft-Funktion dauerhaft kostenlos, Pro nur mit Minecraft-unabhängigem Mehrwert, vorher Rechtsrat. (LOW bis MEDIUM)
- Familien-Server ohne Eintritt und ohne Verkäufe fallen unter keine Monetarisierungsregel außer den allgemeinen Pflichten. (HIGH)

## 5. Online-Modus, Microsoft-Konten, Kinderkonten

### Befund
**Zugang nur mit gekaufter Lizenz** (HIGH)
https://www.minecraft.net/en-us/usage-guidelines (Servers and hosting)
> "Access to your server: Must only be granted to users who have a genuine paid-for version of Minecraft"

**Was online-mode=false bedeutet** (MEDIUM, Sekundärquelle)
https://minecraft.wiki/w/Server.properties
> "Whether to only allow players verified with the Minecraft account database to join. ... Setting this variable to off purposely is called "cracking" a server, and servers that are present with online mode off are called "cracked" servers, allowing players with unlicensed copies of Minecraft to join."

**Kinderkonten werden über Xbox-Privatsphäre gesteuert, auch für Java** (HIGH)
https://help.minecraft.net/hc/en-us/articles/4408968616077-Set-Up-Microsoft-Family-Accounts-for-Minecraft-Multiplayer-Games
> "Minecraft uses Microsoft and Xbox family safety features to manage parental controls even if you do not play Minecraft on an Xbox."
> "Only parent accounts can modify settings."
https://help.minecraft.net/hc/en-us/articles/24302916594701-Managing-Multiplayer-Game-Access-for-a-Child-Account-in-Minecraft
> "These settings will apply even if you don’t play Minecraft on an Xbox."
> "Manage multiplayer and Realms access: Change the setting under Xbox and Windows 10 devices Online Safety > join multiplayer games ... to manage whether your child can join multiplayer games, Realms, and other servers." (Abschnitt ausdrücklich für Bedrock)
> Java-Abschnitt: "Control multiplayer communication: ... Choosing Friends will limit incoming chat to players on the Friends List."
https://help.minecraft.net/hc/en-us/articles/360042221252-Troubleshooting-Errors-Playing-Minecraft-Multiplayer-Games-with-a-Child-Account
> "If you are playing Minecraft signed in with a child account and receive the error “You cannot play online multiplayer because of how your Microsoft account is setup,” the adult Family Account owner will need to review and change your privacy settings to join multiplayer games or Realms."

**Java blockiert Mehrspieler bei Kinderkonten** (MEDIUM): Die offizielle Hilfe nennt die Meldung "Multiplayer is disabled" (https://help.minecraft.net/hc/en-us/articles/4409236107789), ordnet die Kontoeinstellung im Text aber nur Bedrock zu. Dass Java-Kinderkonten ohne "join multiplayer games = Allow" keinen Server betreten können, belegen nur Nutzerberichte bei Microsoft Q&A (https://learn.microsoft.com/en-us/answers/questions/5811687/minecraft-java-edition-has-multiplayer-disabled, Nutzer: "Just wait a day or two") und eine KI-Antwort dort; die erwähnte Freigabe "third-party apps" für Kinderkonten habe ich nicht primär verifiziert. **Offen, im Spike mit echtem Kinderkonto testen.**

### Auslegung
- **offline-mode darf Gameworld nicht anbieten**, auch nicht als versteckte Option: Gameworld könnte nicht sicherstellen, dass nur Käufer spielen. Dazu kommt das Sicherheitsproblem (Namen frei wählbar, Whitelist umgehbar, siehe MINECRAFT-V2.md). (HIGH für die Regel, MEDIUM für die Folgerung "App darf es nicht anbieten")
- Folge für Familien: jedes Kind braucht ein eigenes Microsoft-Konto mit gekaufter Java Edition; Eltern müssen in den Xbox-Einstellungen Mehrspieler erlauben, Chat ggf. auf "Freunde". Gameworld muss das vor dem Anlegen einer Welt klar sagen. (HIGH für Kontopflicht, MEDIUM für die genauen Schalter bei Java)
- Ausnahme nur für Tests: offline-mode mit Bot nur in CI, nie im ausgelieferten Produkt (wie MINECRAFT-V2.md). (MEDIUM)

## 6. Bedrock Edition

### Befund
- BDS ist kostenlos, Download nur nach Checkbox für EULA und Privacy Policy (Zitate in Abschnitt 2). Eine **separate BDS-Lizenz habe ich nicht gefunden**; es gilt die allgemeine EULA. Der Inhalt der mitgelieferten "bedrock_server_how_to.html" wurde nicht geprüft (Download nicht ausgeführt). (HIGH für Downloadseite, LOW für "keine Zusatzbedingungen")
- **Konsolen können keine eigene Serveradresse eintragen** (HIGH)
  https://help.minecraft.net/hc/en-us/articles/4410316619533-Play-Minecraft-Bedrock-Edition-Online-in-a-Multiplayer-Server
  > "If you play Minecraft on a computer or mobile device, you can modify your server list. Console versions of Minecraft are limited to the featured servers."
- Konsolen brauchen zusätzlich ein Online-Abo der Plattform (HIGH)
  https://help.minecraft.net/hc/en-us/articles/4409236107789-Troubleshoot-Unable-to-Join-Multiplayer-Games-in-Minecraft
  > "If you’re on a console, subscribe to Xbox Game Pass Core or PlayStation Plus to play with friends. Nintendo Switch players must also subscribe to Nintendo Switch Online"
- Mojang veröffentlicht für BDS-Modding Protokolldoku: "If you are interested in modding Bedrock Server, you can find protocol documentation here" (https://www.minecraft.net/en-us/download/server/bedrock). (HIGH)

### Auslegung
- Lizenzrechtlich gilt für BDS dasselbe wie für Java: Laufzeit-Download beim Betreiber erlaubt, nicht mitliefern, Zustimmung per Checkbox. (MEDIUM)
- DNS-Umleitungen (BedrockConnect), damit Konsolen fremde Server erreichen, sind kein Mojang-Weg. Für ein Kinder-Produkt nicht anbieten. (MEDIUM)
- Geyser/Floodgate (Bedrock-Spieler auf Java-Server): Bedrock-Spieler besitzen eine gekaufte "genuine paid-for version of Minecraft", die Regel nennt keine Edition. Keine Primärquelle äußert sich zu Geyser. (LOW)

## 7. Mods und Plugins (Paper, Fabric)

### Befund
**EULA** (HIGH)
https://www.minecraft.net/en-us/eula
> "By "Mods," we mean something original that you or someone else created that doesn't contain a substantial part of our copyrightable code or content."
> "You may not distribute any Modded Versions of our game or software"
> "Basically, Mods are okay to distribute; hacked versions or Modded Versions of the game client or server software are not okay to distribute."
> "Any Mods you create ... you can do whatever you want with them, as long as you don't sell them for money / try to make money from them"

**Usage Guidelines** (HIGH)
> "You may create, use, or distribute a mod if: You distribute the mod **only** and not a modded version of Minecraft; The mod doesn’t create a play-to-earn function ...; The mod cannot be used to directly or indirectly verify whether a player owns or has access to out-of-game content, products, or services that affect in-game features and functions"

**Paper** (HIGH für Mechanik)
https://github.com/PaperMC/Paperclip
> "It uses a bsdiff patch between the vanilla Minecraft server and the modified Paper server to generate the Paper Minecraft server immediately upon first run."
Hinweis: Paperclip begründet das selbst mit der GPL ("This avoids the legal problems of the GPL's linking clause"), nicht mit der EULA. Dass das Patch-Verfahren auch das EULA-Problem löst, ist Auslegung. (MEDIUM)

**Fabric** (HIGH für Mechanik)
https://fabricmc.net/use/server/
> "The executable jar is a small launcher that will start the Fabric enabled Minecraft server using the versions specified above."

### Auslegung
- Paper/Fabric nur über ihre offiziellen Launcher zur Laufzeit beim Betreiber erzeugen lassen; das fertige gepatchte Server-Jar nie in Images, Releases oder Backups weitergeben. (HIGH Verbot, MEDIUM Muster)
- Eigene Gameworld-Plugins (z. B. Whitelist/Spielzeit-Plugin für Paper) dürfen unter AGPL verteilt werden, solange sie keinen nennenswerten Mojang-Code enthalten und kostenlos bleiben. (HIGH)
- Ein Plugin, das Spielzeit über Nextcloud steuert, prüft keinen "out-of-game" Besitz für In-Game-Inhalte; die Scarcity-Regel greift nicht. (MEDIUM)
- Nicht geprüft: Lizenzverträglichkeit Paper-API (GPL/MIT) mit AGPL; vor dem Plugin-Bau klären.

## 8. Risiken für den Nextcloud-Store-Eintrag

### Befund
https://docs.nextcloud.com/server/stable/developer_manual/app_publishing_maintenance/publishing.html (NC 35 Manual)
> "Apps do not violate any laws; it has to comply with copyright- and trademark law."
> "Apps clearly communicate their intended purpose and active features, including features introduced through updates."
> "Apps must respect user privacy. IF user data is sent anywhere, this must be clearly explained and be kept to a minimum for the functioning of an app."
> "Apps which break the guidelines will lose their ‘approved’ or ‘official’ state; and might be blocked from the app store altogether."

### Risiken
1. **Marken-Takedown durch Microsoft/Mojang** bei Namens- oder Logo-Verstoß; Nextcloud müsste reagieren. Mittel durch Naming und Disclaimer beherrschbar. (MEDIUM)
2. **Mitgelieferte Mojang-Dateien** im Image wären eine Urheberrechtsverletzung und ein Grund zur Sperre. Durch Laufzeit-Download vermeidbar. (HIGH)
3. **Datenfluss nach außen:** Minecraft-Server sprechen mit Mojang/Microsoft (Authentifizierung, Download). Muss in Store-Text und privacy.md stehen, sonst Verstoß gegen "Respect the users". (HIGH für Regel, MEDIUM für konkreten Umfang)
4. **Guidelines können sich ohne Ankündigung ändern** ("we have the right to withdraw the permissions given in them at any time without notice", EULA). Regelmäßige Neuprüfung nötig. (HIGH)
5. **Support-Last:** Kontoprobleme der Kinder (Kauf, Xbox-Einstellungen) landen bei Gameworld, obwohl Gameworld sie nicht lösen kann. Kein Rechtsrisiko, aber ein Reputationsrisiko im Store. (MEDIUM)

---

## Auflagen-Liste für das Produkt

**Verteilung**
1. Kein server.jar, kein Paper-/Fabric-Jar, kein BDS im ExApp-Image, in Gameworld-Images, Registries, Releases oder zentralen Backups.
2. Download ausschließlich zur Laufzeit von Mojang (piston-data.mojang.com bzw. über itzg) oder vom offiziellen Paper-/Fabric-Launcher, auf der Maschine des Betreibers.
3. Version pinnen und Prüfsumme gegen Mojangs Metadaten prüfen (Integrität, "source that we authorize").

**EULA-Zustimmung**
4. Vor dem ersten Download: eigener Schritt im Create-Flow, aktive Checkbox ohne Vorbelegung, Text sinngemäß "Ich stimme der Minecraft-EULA und der Microsoft-Datenschutzerklärung zu", beide verlinkt (https://www.minecraft.net/en-us/eula, https://go.microsoft.com/fwlink/?LinkId=521839).
5. Zustimmung pro Nextcloud-Konto mit Zeitstempel speichern; `EULA=TRUE` erst danach setzen; nie als Default im Code.
6. Nur Verwalter/Eltern-Rolle darf zustimmen, nie ein Kinderkonto.
7. Bei geänderter EULA (Hash der Seite oder Versionswechsel) Hinweis zeigen; EULA- und Server-Meldungen nicht unterdrücken.

**Marke**
8. App-Name bleibt "Gameworld"; "Minecraft: Java Edition" nur in Beschreibung und Spielauswahl.
9. Kein Minecraft-Logo, keine Minecraft-Schrift, keine Texturen, kein Creeper in Icon, UI oder Store-Bildern; Store-Screenshots nur Gameworld-UI.
10. Disclaimer prominent in Store-Beschreibung, README, Website und im Minecraft-Create-Dialog: "NOT AN OFFICIAL MINECRAFT PRODUCT. NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT." (deutsch zusätzlich: "Kein offizielles Minecraft-Produkt. Nicht von Mojang oder Microsoft genehmigt oder mit ihnen verbunden.")
11. Verantwortlicher und Kontakt (E-Mail oder Issue-Tracker) im Listing; nicht nur Chat/Forum.
12. "Minecraft" nicht als Keyword-Spam in Tags/Beschreibung.

**Konten und Kinder**
13. `online-mode=true` fest, im UI nicht abschaltbar; offline-mode nur in CI-Tests.
14. Vor dem Anlegen klar sagen: jedes Kind braucht ein Microsoft-Konto mit gekaufter Java Edition; Eltern müssen Mehrspieler in den Xbox-Einstellungen erlauben; Link auf die offiziellen Hilfeartikel.
15. Whitelist an, Einladungen über Gameworld; Chat-Empfehlung "Freunde".

**Geld**
16. Minecraft-Funktion kostenlos; Spenden nur für Gameworld als Software, ohne Minecraft-Vorteile und ohne Minecraft-Werbung.
17. Keine Pro-Version mit Minecraft als Verkaufsargument ohne vorherigen Rechtsrat.

**Datenschutz/Store**
18. Store-Text und privacy.md nennen den Datenaustausch mit Mojang/Microsoft (Download, Login-Prüfung, Chat-Signaturen).
19. Hinweis, dass der Betreiber (die Familie) für Spielerdaten auf seinem Server verantwortlich ist.

**Bedrock (falls später)**
20. Gleiche Auflagen 1 bis 7; Konsolen ausdrücklich "nicht unterstützt", keine DNS-Tricks anbieten.

## Offen / nicht verifiziert
- Genaue Kinderkonto-Schalter für **Java**-Mehrspieler (offizieller Artikel nennt sie nur für Bedrock); im Spike mit echtem Kinderkonto prüfen.
- Inhalt der in BDS mitgelieferten Anleitung (eventuelle Zusatzbedingungen) nicht gelesen.
- Keine Mojang-Aussage, die Drittpanels oder Geyser ausdrücklich erlaubt; Duldung ist Praxis, kein Recht.
- Ob deutsche AGB-Kontrolle einzelne EULA-Klauseln einschränkt ("Your local law may give you rights that this EULA cannot change"), nicht geprüft.
- Bei Pro-Version oder Unsicherheit: Mojang bietet nur Partnerschaftsanfragen an (https://aka.ms/mc-partnerships), keine Einzelfallprüfung.

## Quellen (alle abgerufen 22.10.2026)
- Minecraft EULA: https://www.minecraft.net/en-us/eula (HIGH)
- Minecraft Usage Guidelines: https://www.minecraft.net/en-us/usage-guidelines (HIGH)
- Zusammenlegung der Guidelines 02.08.2023: https://www.minecraft.net/en-us/article/minecraft-eula-and-commercial-usage-guidelines-updates (HIGH)
- Brand Guidelines alt: https://www.minecraft.net/en-us/brand-guidelines (404) (HIGH)
- Java-Server-Download: https://www.minecraft.net/en-us/download/server (HIGH)
- Bedrock Dedicated Server: https://www.minecraft.net/en-us/download/server/bedrock (HIGH)
- Hilfe Server-Download: https://help.minecraft.net/hc/en-us/articles/4408873961869-Download-Dedicated-Minecraft-Server-Software (HIGH)
- Hilfe Familiengruppen: https://help.minecraft.net/hc/en-us/articles/4408968616077-Set-Up-Microsoft-Family-Accounts-for-Minecraft-Multiplayer-Games (HIGH)
- Hilfe Mehrspieler Kinderkonto: https://help.minecraft.net/hc/en-us/articles/24302916594701-Managing-Multiplayer-Game-Access-for-a-Child-Account-in-Minecraft (HIGH)
- Hilfe Fehler Kinderkonto: https://help.minecraft.net/hc/en-us/articles/360042221252-Troubleshooting-Errors-Playing-Minecraft-Multiplayer-Games-with-a-Child-Account (HIGH)
- Hilfe Social Settings: https://help.minecraft.net/hc/en-us/articles/6985971367309 (HIGH)
- Hilfe Java-Freundesliste: https://help.minecraft.net/hc/en-us/articles/46662761433357-Learn-more-about-the-Minecraft-Java-Edition-Friends-List (HIGH)
- Hilfe Mehrspieler-Probleme: https://help.minecraft.net/hc/en-us/articles/4409236107789-Troubleshoot-Unable-to-Join-Multiplayer-Games-in-Minecraft (HIGH)
- Hilfe Bedrock-Server: https://help.minecraft.net/hc/en-us/articles/4410316619533-Play-Minecraft-Bedrock-Edition-Online-in-a-Multiplayer-Server (HIGH)
- Microsoft Services Agreement (Effective 30.09.2026): https://www.microsoft.com/en-us/servicesagreement (HIGH)
- Nextcloud App Store Rules: https://docs.nextcloud.com/server/stable/developer_manual/app_publishing_maintenance/publishing.html (HIGH)
- itzg/docker-minecraft-server: https://docker-minecraft-server.readthedocs.io/en/latest/ (MEDIUM, Praxis)
- Paperclip: https://github.com/PaperMC/Paperclip (HIGH für Mechanik)
- Fabric Server Launcher: https://fabricmc.net/use/server/ (HIGH für Mechanik)
- Minecraft Wiki server.properties: https://minecraft.wiki/w/Server.properties (MEDIUM)
- Minecraft Wiki Server-Tutorial: https://minecraft.wiki/w/Tutorial:Setting_up_a_Java_Edition_server (MEDIUM)
- Microsoft Q&A Java Multiplayer disabled: https://learn.microsoft.com/en-us/answers/questions/5811687/minecraft-java-edition-has-multiplayer-disabled (LOW)
- CubeCoders AMP: https://cubecoders.com/AMP (MEDIUM, Praxis)
