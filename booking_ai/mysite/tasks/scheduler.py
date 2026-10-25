"""Фоновый цикл рассылки. Запускается вместе с API (SCHEDULER_ENABLED=1) или отдельно: python -m mysite.tasks.scheduler

Внимание: запускайте цикл только в одном процессе. Дубли уведомлений база не пропустит, но два процесса
могут одновременно отправить одно и то же уведомление."""
import asyncio
import logging

from mysite.config import get_settings
from mysite.database.session import get_sessionmaker
from mysite.tasks.notifier import Sender, run_cycle, run_events_cycle
from mysite.tasks.plan_notices import run_plan_cycle

log = logging.getLogger("booking_ai.scheduler")


def build_senders(telegram, whatsapp) -> dict[str, Sender]:
    senders: dict[str, Sender] = {}
    if telegram is not None:
        senders["telegram"] = telegram.send_message
    if whatsapp is not None:
        senders["whatsapp"] = whatsapp.send_notification
    return senders


async def run_once(maker, senders: dict[str, Sender], provider, days_before: int) -> dict:
    """Один проход: новые объявления, смена цены и снятие, напоминания и продление тарифа.
    Шаги независимы: ошибка в одном не мешает остальным."""
    stats: dict = {}
    steps = (("рассылка", lambda: run_cycle(maker, senders)),
             ("события объявлений", lambda: run_events_cycle(maker, senders)),
             ("тарифы", lambda: run_plan_cycle(maker, senders, provider, days_before)))
    for name, step in steps:
        try:
            stats.update(await step())
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка в шаге «%s», повторим в следующий раз", name)
    return stats


async def run_forever(maker, senders: dict[str, Sender], interval: int, provider=None, days_before: int = 3) -> None:
    if provider is None:  # платёжный провайдер нужен только автопродлению
        from mysite.integrations.payment_providers import build_provider
        provider = build_provider(get_settings())
    while True:
        stats = await run_once(maker, senders, provider, days_before)
        if any(stats.values()):
            log.info("Рассылка: %s", stats)
        await asyncio.sleep(interval)


async def main() -> None:
    from mysite.integrations.telegram import TelegramClient
    from mysite.integrations.whatsapp import WhatsAppClient

    s = get_settings()
    telegram = TelegramClient(s.telegram_bot_token) if s.telegram_bot_token else None
    whatsapp = None
    if s.whatsapp_access_token and s.whatsapp_phone_number_id:
        whatsapp = WhatsAppClient(s.whatsapp_access_token, s.whatsapp_phone_number_id,
                                  template_name=s.whatsapp_template_name, template_lang=s.whatsapp_template_lang,
                                  api_version=s.whatsapp_api_version)
    await run_forever(get_sessionmaker(), build_senders(telegram, whatsapp), s.scheduler_interval_seconds,
                      days_before=s.plan_remind_days_before)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
