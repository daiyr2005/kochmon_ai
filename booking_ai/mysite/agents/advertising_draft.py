from __future__ import annotations

import asyncio

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from mysite.agents.tools.advertising import fill_advertising_campaign_fields
from mysite.config import Settings
from mysite.schemas.advertising import CampaignDraftFields


class AdvertisingDraftError(RuntimeError):
    pass


_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Extract only advertising campaign fields explicitly stated in the user's text. "
            "Call fill_advertising_campaign_fields exactly once. Never invent a price, currency, "
            "image URL, destination URL, placement, or campaign dates. Use null for information "
            "that is missing or ambiguous. For the placement use one of: home, internet_search, "
            "listings, category, listing. Dates must include an explicit timezone; if no timezone "
            "is supplied, leave the date null. Do not create, publish, approve, or claim payment."
        ),
        ("human", "Campaign request:\n{text}"),
    ]
)


async def generate_advertising_draft(text: str, settings: Settings) -> CampaignDraftFields:
    model = ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=0,
        num_predict=500,
    ).bind_tools([fill_advertising_campaign_fields])
    message = await asyncio.wait_for(
        (_PROMPT | model).ainvoke({"text": text}),
        timeout=settings.ollama_timeout_seconds,
    )
    calls = getattr(message, "tool_calls", None) or []
    if len(calls) != 1 or calls[0].get("name") != fill_advertising_campaign_fields.name:
        raise AdvertisingDraftError("AI did not return a valid campaign draft")
    try:
        data = fill_advertising_campaign_fields.invoke(calls[0]["args"])
        return CampaignDraftFields.model_validate(data)
    except Exception as exc:
        raise AdvertisingDraftError("AI returned invalid campaign fields") from exc
