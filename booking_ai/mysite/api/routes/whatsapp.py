from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, Response

from mysite.config import get_settings
from mysite.database.session import get_sessionmaker
from mysite.integrations.whatsapp import handle_payload, verify_signature

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


# 1. Meta один раз проверяет адрес: присылает hub.challenge, мы должны вернуть его назад
@router.get("/webhook", include_in_schema=False)
async def verify(
    mode: str | None = Query(None, alias="hub.mode"),
    token: str | None = Query(None, alias="hub.verify_token"),
    challenge: str | None = Query(None, alias="hub.challenge"),
):
    wanted = get_settings().whatsapp_verify_token
    if not wanted or mode != "subscribe" or token != wanted or challenge is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    return Response(content=challenge, media_type="text/plain")


# 2. Дальше Meta присылает входящие сообщения, подпись проверяем по секрету приложения
@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, background: BackgroundTasks, x_hub_signature_256: str | None = Header(None)):
    secret = get_settings().whatsapp_app_secret
    client = getattr(request.app.state, "whatsapp", None)
    runtime = getattr(request.app.state, "ai", None)
    if not secret or client is None or runtime is None:
        raise HTTPException(status_code=404, detail="Not found")

    body = await request.body()
    if not verify_signature(secret, body, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad request")

    # отвечаем сразу, иначе Meta будет повторять доставку; обработка идёт в фоне
    background.add_task(handle_payload, payload, runtime=runtime, client=client, maker=get_sessionmaker())
    return {"ok": True}
