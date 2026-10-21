"""Webhook des Gameworld-Bots: POST /talk/bot (TALK-02, T-04.1-29, T-04.1-30).

Talk schickt jede Chatnachricht der Räume, in denen der Bot aktiv ist, an
AppAPIs ``talk_proxy``. Dort prüft AppAPI die Talk-Signatur (HMAC über
Zufallswert und Body mit dem Bot-Geheimnis, ``hash_equals``, Bruteforce-Drossel)
und ruft erst dann diese Route mit AppAPI-Authentifizierung auf. Die prüft hier
``AppAPIAuthMiddleware`` (geteiltes Geheimnis, sonst 401).

Gameworld braucht die Inhalte nicht. Es sind Chats von Kindern: Der Body wird
nicht gelesen, nicht gespeichert, nicht geloggt und nicht weiterverarbeitet.
Darum auch kein ``atalk_bot_msg``, das den Body nur parsen würde.
Keine Verwalter-Sperre: AppAPI ruft ohne Nutzer auf.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter()


@router.post("/talk/bot")
async def talk_bot_webhook() -> Response:
    """Bestätigt den Empfang und verwirft die Nachricht ungelesen."""
    return Response(status_code=200)
