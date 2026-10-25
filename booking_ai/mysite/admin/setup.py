from fastapi import FastAPI
from sqladmin import Admin

from mysite.db.db import engine

from .views import (
    UserAdmin,
    CountryAdmin,
    CityAdmin,
    CategoryAdmin,
    ListingAdmin,
    SearchSubscriptionAdmin,
    NotificationAdmin,
    BlockedWordAdmin,
    ChannelAccountAdmin,
    ProcessedMessageAdmin,
    ChannelLinkCodeAdmin,
)


def setup_admin(user_app: FastAPI) -> None:
    admin = Admin(user_app, engine)

    admin.add_view(UserAdmin)
    admin.add_view(CountryAdmin)
    admin.add_view(CityAdmin)
    admin.add_view(CategoryAdmin)
    admin.add_view(ListingAdmin)
    admin.add_view(SearchSubscriptionAdmin)
    admin.add_view(NotificationAdmin)
    admin.add_view(BlockedWordAdmin)
    admin.add_view(ChannelAccountAdmin)
    admin.add_view(ProcessedMessageAdmin)
    admin.add_view(ChannelLinkCodeAdmin)
