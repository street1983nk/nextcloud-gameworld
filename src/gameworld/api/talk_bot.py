"""Webhook of the Gameworld bot: POST /talk/bot (TALK-02, T-04.1-29, T-04.1-30).

Talk sends every chat message of the rooms in which the bot is active to
AppAPI's ``talk_proxy``. There AppAPI checks the Talk signature (HMAC over
the random value and body with the bot secret, ``hash_equals``, brute-force throttle)
and only then calls this route with AppAPI authentication. That is checked here
by ``AppAPIAuthMiddleware`` (shared secret, otherwise 401).

Gameworld does not need the contents. These are chats of children: the body is
not read, not stored, not logged and not processed further.
Hence also no ``atalk_bot_msg``, which would only parse the body.

Only the call from AppAPI itself counts (IN-01): ``talk_proxy`` calls without a user
(``requestToExApp`` with userId null, AppAPI source TalkBotController checked on the
dev stack). Via the user proxy (``/exapps/gameworld/talk/bot``, route
USER in info.xml) every signed-in account would arrive here, including a child; with a user
the answer is therefore 403. Check point for phase 6 (HaRP): does HaRP call the webhook
without a user as well? Otherwise this check blocks bot reception (the bot keeps
sending, it reads nothing anyway).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

router = APIRouter()

MSG_ONLY_APPAPI = "Diese Adresse ist nur für Talk über AppAPI."


@router.post("/talk/bot")
async def talk_bot_webhook(request: Request) -> Response:
    """Confirms receipt and discards the message unread; with a user 403 (IN-01)."""
    if request.scope.get("username"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=MSG_ONLY_APPAPI)
    return Response(status_code=200)
