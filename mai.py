import os
from fastapi import FastAPI, Request, Response, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Значения из ваших переменных окружения (.env)
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "my_secure_whatsapp_token_2026")
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")


@app.get("/webhook")
async def verify_webhook(request: Request):
    """
    Эндпоинт для подтверждения вебхука со стороны Meta.
    Meta отправляет GET-запрос с параметрами hub.mode, hub.verify_token и hub.challenge.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode and token:
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("WEBHOOK_VERIFIED: Вебхук успешно подтвержден!")
            # Возвращаем полученый challenge в виде plain text
            return Response(content=challenge, media_type="text/plain")
        else:
            raise HTTPException(status_code=403, detail="Verification token mismatch")

    raise HTTPException(status_code=400, detail="Missing parameters")


@app.post("/webhook")
async def receive_webhook(request: Request):
    """
    Эндпоинт для получения входящих сообщений и событий от WhatsApp.
    """
    body = await request.json()
    print("Получено входящее уведомление:", body)

    try:
        # Извлекаем текст входящего сообщения (если оно есть)
        entry = body.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages")

        if messages:
            msg = messages[0]
            sender_phone = msg.get("from")  # Номер отправителя
            msg_body = msg.get("text", {}).get("body")  # Текст сообщения
            print(f"Сообщение от {sender_phone}: {msg_body}")

            # Здесь вы можете добавить логику обработки сообщения или передачи в ваш AI-агент / RAG

    except Exception as e:
        print("Ошибка при обработке webhook:", e)

    # Всегда возвращаем 200 OK, чтобы Meta знала, что запрос доставлен
    return {"status": "success"}