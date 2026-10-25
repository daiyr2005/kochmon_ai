
from __future__ import annotations
import asyncio
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from mysite.config import get_settings
from mysite.database.ai_models import Category,City,Country,Plan,User
from mysite.database.session import get_sessionmaker
from mysite.services.security import hash_password

COUNTRIES={
    "KG":("Кыргызстан",["Бишкек","Ош","Каракол","Чолпон-Ата","Джалал-Абад"]),
    "KZ":("Казахстан",["Алматы","Астана","Шымкент"]),
    "RU":("Россия",["Москва","Санкт-Петербург"]),
    "UZ":("Узбекистан",["Ташкент","Самарканд"]),
    "TR":("Турция",["Стамбул","Анталья"]),
}
CATEGORIES=[
    ("real_estate","Недвижимость",None),
    ("real_estate_rent","Аренда","real_estate"),
    ("apartment_rent","Квартиры","real_estate_rent"),
    ("room_rent","Комнаты","real_estate_rent"),
    ("house_rent","Дома и коттеджи","real_estate_rent"),
    ("real_estate_sale","Продажа","real_estate"),
    ("apartment_sale","Квартиры на продажу","real_estate_sale"),
    ("house_sale","Дома на продажу","real_estate_sale"),
    ("hotel","Отели и гостиницы",None),
    ("tourist_services","Туристические услуги",None),
]
PLANS=[
    {"code":"free","name":"Free","price":Decimal("0"),"max_subscriptions":1,"min_frequency_minutes":1440,"channels":["api"]},
    {"code":"pro","name":"Pro","price":Decimal("299"),"max_subscriptions":20,"min_frequency_minutes":15,"channels":["api","telegram","whatsapp"]},
    {"code":"business","name":"Business","price":Decimal("799"),"max_subscriptions":100,"min_frequency_minutes":5,"channels":["api","telegram","whatsapp"]},
]

async def seed_catalog(session:AsyncSession)->None:
    for code,(name,cities) in COUNTRIES.items():
        country=await session.scalar(select(Country).where(Country.code==code))
        if country is None:
            country=Country(name=name,code=code,is_active=True)
            session.add(country)
            await session.flush()
        existing=set((await session.scalars(select(City.name).where(City.country_id==country.id))).all())
        for city_name in cities:
            if city_name not in existing:
                session.add(City(name=city_name,country_id=country.id,is_active=True))
    await session.flush()
    categories={x.slug:x for x in (await session.scalars(select(Category))).all()}
    for slug,name,parent_slug in CATEGORIES:
        if slug in categories:
            continue
        parent=categories.get(parent_slug) if parent_slug else None
        if parent_slug and parent is None:
            raise ValueError(f"Не найдена родительская категория: {parent_slug}")
        item=Category(name=name,slug=slug,parent_id=parent.id if parent else None,is_active=True)
        session.add(item)
        await session.flush()
        categories[slug]=item
    await session.commit()

async def seed_plans(session:AsyncSession)->None:
    for item in PLANS:
        exists=await session.scalar(select(Plan.id).where(Plan.code==item["code"]))
        if exists is None:
            session.add(Plan(**item,currency="KGS",duration_days=30,is_active=True))
    await session.commit()

async def seed_admin(session:AsyncSession)->bool:
    settings=get_settings()
    if not settings.admin_email or not settings.admin_password:
        return False
    email=settings.admin_email.strip().lower()
    exists=await session.scalar(select(User.id).where(User.email==email))
    if exists is not None:
        return False
    password_hash=await asyncio.to_thread(hash_password,settings.admin_password)
    session.add(User(full_name="Administrator",email=email,role="admin",password_hash=password_hash,is_active=True))
    await session.commit()
    return True

async def seed_all()->bool:
    async with get_sessionmaker()() as session:
        await seed_catalog(session)
        await seed_plans(session)
        return await seed_admin(session)

async def main()->None:
    created=await seed_all()
    print("Начальные данные проверены.")
    print("Администратор создан." if created else "Администратор уже существует или не настроен.")

if __name__=="__main__":
    asyncio.run(main())
