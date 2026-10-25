from sqladmin import ModelView

from mysite.database.ai_models import *

class UserAdmin(ModelView, model=User):
    name = "Пользователь"
    name_plural = "Пользователи"
    column_list = [
        User.id,
        User.full_name,
        User.email,
        User.role,
        User.is_active,
        User.created_at,
    ]
    column_searchable_list = [User.full_name, User.email]
    column_sortable_list = [User.id, User.created_at]
    can_create = True
    can_edit = True
    can_delete = False


class CountryAdmin(ModelView, model=Country):
    name = "Страна"
    name_plural = "Страны"
    column_list = [
        Country.id,
        Country.name,
        Country.code,
        Country.is_active,
    ]
    column_searchable_list = [Country.name, Country.code]
    can_delete = False


class CityAdmin(ModelView, model=City):
    name = "Город"
    name_plural = "Города"
    column_list = [
        City.id,
        City.name,
        City.country_id,
        City.is_active,
    ]
    column_searchable_list = [City.name]
    can_delete = False


class CategoryAdmin(ModelView, model=Category):
    name = "Категория"
    name_plural = "Категории"
    column_list = [
        Category.id,
        Category.name,
        Category.slug,
        Category.parent_id,
        Category.is_active,
    ]
    column_searchable_list = [Category.name, Category.slug]
    can_delete = False


class ListingAdmin(ModelView, model=Listing):
    name = "Объявление"
    name_plural = "Объявления"
    column_list = [
        Listing.id,
        Listing.title,
        Listing.category_id,
        Listing.country_id,
        Listing.city_id,
        Listing.price,
        Listing.currency,
        Listing.status,
        Listing.owner_id,
        Listing.created_at,
    ]
    column_searchable_list = [
        Listing.title,
        Listing.description,
        Listing.address,
    ]
    column_sortable_list = [
        Listing.id,
        Listing.price,
        Listing.created_at,
        Listing.updated_at,
    ]
    can_delete = False


class SearchSubscriptionAdmin(ModelView, model=SearchSubscription):
    name = "Подписка"
    name_plural = "Подписки"
    column_list = [
        SearchSubscription.id,
        SearchSubscription.user_id,
        SearchSubscription.channel,
        SearchSubscription.category_id,
        SearchSubscription.country_id,
        SearchSubscription.city_id,
        SearchSubscription.is_active,
        SearchSubscription.frequency_minutes,
        SearchSubscription.created_at,
    ]
    can_delete = False


class NotificationAdmin(ModelView, model=Notification):
    name = "Уведомление"
    name_plural = "Уведомления"
    column_list = [
        Notification.id,
        Notification.user_id,
        Notification.listing_id,
        Notification.subscription_id,
        Notification.channel,
        Notification.status,
        Notification.attempts,
        Notification.sent_at,
    ]
    column_searchable_list = [
        Notification.error_message,
    ]
    can_delete = False


class BlockedWordAdmin(ModelView, model=BlockedWord):
    name = "Запрещённое слово"
    name_plural = "Запрещённые слова"
    column_list = [
        BlockedWord.id,
        BlockedWord.word,
        BlockedWord.normalized_word,
        BlockedWord.match_type,
        BlockedWord.is_active,
        BlockedWord.reason,
        BlockedWord.created_at,
    ]
    column_searchable_list = [
        BlockedWord.word,
        BlockedWord.normalized_word,
    ]
    can_delete = False


class ChannelAccountAdmin(ModelView, model=ChannelAccount):
    name = "Аккаунт мессенджера"
    name_plural = "Аккаунты мессенджеров"
    column_list = [
        ChannelAccount.id,
        ChannelAccount.user_id,
        ChannelAccount.channel,
        ChannelAccount.external_user_id,
        ChannelAccount.is_verified,
        ChannelAccount.is_active,
        ChannelAccount.created_at,
    ]
    can_delete = False


class ProcessedMessageAdmin(ModelView, model=ProcessedMessage):
    name = "Обработанное сообщение"
    name_plural = "Обработанные сообщения"
    column_list = [
        ProcessedMessage.id,
        ProcessedMessage.channel,
        ProcessedMessage.external_message_id,
        ProcessedMessage.created_at,
    ]
    can_create = False
    can_edit = False
    can_delete = False


class ChannelLinkCodeAdmin(ModelView, model=ChannelLinkCode):
    name = "Код привязки"
    name_plural = "Коды привязки"
    column_list = [
        ChannelLinkCode.id,
        ChannelLinkCode.user_id,
        ChannelLinkCode.channel,
        ChannelLinkCode.code,
        ChannelLinkCode.expires_at,
    ]
    can_create = False
    can_edit = False
    can_delete = False
