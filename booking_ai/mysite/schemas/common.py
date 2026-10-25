from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class MessageOut(BaseModel, Generic[T]):
    """Ответ на POST / PATCH / DELETE: сообщение и, если есть, сам объект."""
    message: str
    data: T | None = None
