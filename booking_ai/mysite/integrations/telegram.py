import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mysite.integrations.ollama import OllamaUnavailable
from mysite.database.ai_models import ChannelAccount, ChannelLinkCode, ProcessedMessage, User
from mysite.schemas.ai import ChatOut
from mysite.agents.runtime import AIRuntime

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger(__name__)

CHANNEL = "telegram"
LINK_TTL = timedelta(minutes=15)
MAX_TEXT = 2000
TG_LIMIT = 4000

HELP = (
    "Привет! Я помогу искать объявления и управлять подписками.\n"
    "Например: «найди отель в Бишкеке до 5000 сом за ночь» или «мои объявления».\n"
    "Для привязки аккаунта получи код через POST /api/channels/telegram/link "
    "и отправь /start КОД.\n"
    "Для отвязки отправь /unlink."
)


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(
        self,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = "https://api.telegram.org",
    ):
        self.url = f"{base_url}/bot{token}"
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(40.0, connect=10.0),
            transport=transport,
        )

    async def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        try:
            response = await self.http.post(
                f"{self.url}/{method}",
                json=payload or {},
                timeout=timeout if timeout else httpx.USE_CLIENT_DEFAULT,
            )
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise TelegramError(
                f"Telegram API недоступен ({type(exc).__name__})"
            ) from None

        if not data.get("ok"):
            raise TelegramError(
                f"Telegram API: {data.get('description', 'ошибка')}"
            )
        return data["result"]

    async def send_message(self, chat_id: int | str, text: str) -> None:
        for i in range(0, max(len(text), 1), TG_LIMIT):
            await self.call(
                "sendMessage",
                {"chat_id": chat_id, "text": text[i:i + TG_LIMIT] or "…"},
            )

    async def get_updates(
        self, offset: int | None = None, timeout: int = 30
    ) -> list[dict]:
        payload = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return await self.call("getUpdates", payload, timeout + 15)

    async def delete_webhook(self) -> None:
        await self.call("deleteWebhook", {"drop_pending_updates": False})

    async def set_webhook(self, url: str, secret: str) -> None:
        await self.call(
            "setWebhook",
            {"url": url, "secret_token": secret, "allowed_updates": ["message"]},
        )

    async def aclose(self) -> None:
        await self.http.aclose()


def format_reply(out: ChatOut) -> str:
    parts = [out.response]
    for item in out.results[:5]:
        price = ""
        if item.get("price"):
            price = f" — {item['price']} {item.get('currency') or ''}".rstrip()

        label = f"№{item['id']}" if item.get("id") is not None else "Из интернета:"
        line = f"{label} {item.get('title', '')}{price}"

        if item.get("source_url"):
            line += f"\n{item['source_url']}"
        parts.append(line)

    if len(out.results) > 5:
        parts.append(f"Ещё результатов: {len(out.results) - 5}")

    return "\n".join(part for part in parts if part)


async def create_link_code(
    session: AsyncSession, user_id: int, channel: str = CHANNEL
) -> tuple[str, int]:
    code = secrets.token_urlsafe(16)
    session.add(
        ChannelLinkCode(
            code=code,
            user_id=user_id,
            channel=channel,
            expires_at=datetime.now(timezone.utc) + LINK_TTL,
        )
    )
    await session.commit()
    return code, int(LINK_TTL.total_seconds())


def make_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def link_account(
    session: AsyncSession,
    code: str,
    tg_user_id: int,
    channel: str = CHANNEL,
) -> str:
    link = await session.scalar(
        select(ChannelLinkCode).where(
            ChannelLinkCode.code == code,
            ChannelLinkCode.channel == channel,
        )
    )

    if link is None or make_aware(link.expires_at) < datetime.now(timezone.utc):
        if link is not None:
            await session.delete(link)
            await session.commit()
        return "Код недействителен или истёк. Получите новый."

    account = await session.scalar(
        select(ChannelAccount).where(
            ChannelAccount.channel == channel,
            ChannelAccount.external_user_id == str(tg_user_id),
        )
    )

    if account is not None and account.user_id != link.user_id:
        return "Этот аккаунт уже привязан к другому пользователю."

    if account is None:
        account = ChannelAccount(
            user_id=link.user_id,
            channel=channel,
            external_user_id=str(tg_user_id),
            is_verified=True,
            is_active=True,
        )
        session.add(account)
    else:
        account.is_verified = True
        account.is_active = True

    await session.delete(link)
    await session.commit()
    return "Аккаунт успешно привязан."


async def unlink_account(
    session: AsyncSession, tg_user_id: int, channel: str = CHANNEL
) -> str:
    account = await session.scalar(
        select(ChannelAccount).where(
            ChannelAccount.channel == channel,
            ChannelAccount.external_user_id == str(tg_user_id),
        )
    )

    if account is None:
        return "Аккаунт не привязан."

    await session.delete(account)
    await session.commit()
    return "Аккаунт отвязан."


async def claim_message(
    session: AsyncSession, external_id: str, channel: str = CHANNEL
) -> bool:
    session.add(
        ProcessedMessage(channel=channel, external_message_id=external_id)
    )
    try:
        await session.commit()
        return True
    except IntegrityError:
        await session.rollback()
        return False


async def linked_user(
    session: AsyncSession, tg_user_id: int, channel: str = CHANNEL
) -> User | None:
    account = await session.scalar(
        select(ChannelAccount).where(
            ChannelAccount.channel == channel,
            ChannelAccount.external_user_id == str(tg_user_id),
            ChannelAccount.is_verified.is_(True),
            ChannelAccount.is_active.is_(True),
        )
    )

    user = await session.get(User, account.user_id) if account else None
    if user is None or not user.is_active:
        return None
    return user


async def process_message(
    session: AsyncSession,
    runtime: AIRuntime,
    *,
    chat_id: int,
    tg_user_id: int,
    text: str,
) -> str:
    command, _, arg = text.partition(" ")
    command = command.split("@")[0].lower()

    if command == "/start":
        if arg.strip():
            return await link_account(session, arg.strip(), tg_user_id)
        return HELP

    if command == "/help":
        return HELP

    if command == "/unlink":
        return await unlink_account(session, tg_user_id)

    user = await linked_user(session, tg_user_id)
    result = await runtime.handle(session, user, CHANNEL, str(chat_id), text)
    return format_reply(result)


async def handle_update(
    update: dict,
    *,
    runtime: AIRuntime,
    client: TelegramClient,
    maker: async_sessionmaker[AsyncSession],
) -> None:
    message = update.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("text"), str):
        return

    chat = message.get("chat") or {}
    sender = message.get("from") or {}

    if (
        chat.get("type") != "private"
        or "id" not in chat
        or "id" not in sender
        or sender.get("is_bot")
    ):
        return

    chat_id = chat["id"]
    text = message["text"].strip()[:MAX_TEXT]
    if not text:
        return

    try:
        async with maker() as session:
            message_id = f"{chat_id}:{message.get('message_id')}"
            if not await claim_message(session, message_id):
                return

            reply = await process_message(
                session,
                runtime,
                chat_id=chat_id,
                tg_user_id=sender["id"],
                text=text,
            )
    except OllamaUnavailable:
        reply = "Ассистент временно недоступен. Попробуйте позже."
    except Exception:
        log.exception("Ошибка обработки сообщения Telegram")
        reply = "Не удалось обработать сообщение. Попробуйте позже."

    try:
        await client.send_message(chat_id, reply)
    except TelegramError:
        log.warning("Не удалось отправить ответ в Telegram")
