"""Webhook des Gameworld-Bots: POST /talk/bot (TALK-02, T-04.1-29, T-04.1-30).

Talk schickt jede Chatnachricht der Räume, in denen der Bot aktiv ist, an
AppAPIs ``talk_proxy``. Dort prüft AppAPI die Talk-Signatur (HMAC über
Zufallswert und Body mit dem Bot-Geheimnis, ``hash_equals``, Bruteforce-Drossel)
und ruft erst dann diese Route mit AppAPI-Authentifizierung auf. Die prüft hier
``AppAPIAuthMiddleware`` (geteiltes Geheimnis, sonst 401).

Gameworld braucht die Inhalte nicht. Es sind Chats von Kindern: Der Body wird
nicht gelesen, nicht gespeichert, nicht geloggt und nicht weiterverarbeitet.
Darum auch kein ``atalk_bot_msg``, das den Body nur parsen würde.

Nur der Aufruf von AppAPI selbst gilt (IN-01): ``talk_proxy`` ruft ohne Nutzer
(``requestToExApp`` mit userId null, AppAPI-Quelltext TalkBotController im
Dev-Stack geprüft). Über den Nutzer-Proxy (``/exapps/gameworld/talk/bot``, Route
USER in info.xml) käme jedes angemeldete Konto hierher, auch ein Kind; mit Nutzer
gibt es darum 403. Prüfpunkt für Phase 6 (HaRP): Ruft HaRP den Webhook ebenfalls
ohne Nutzer auf? Sonst sperrt diese Prüfung den Bot-Empfang (der Bot sendet
weiter, er liest ohnehin nichts).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

router = APIRouter()

MSG_ONLY_APPAPI = "Diese Adresse ist nur für Talk über AppAPI."


@router.post("/talk/bot")
async def talk_bot_webhook(request: Request) -> Response:
    """Bestätigt den Empfang und verwirft die Nachricht ungelesen; mit Nutzer 403 (IN-01)."""
    if request.scope.get("username"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=MSG_ONLY_APPAPI)
    return Response(status_code=200)
