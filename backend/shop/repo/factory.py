"""Доступ до бази.

Реалізація одна — Postgres через SQLAlchemy. Раніше тут був вибір між SQL
і Firestore; Firestore прибрано разом із serverless-розгортанням, бо на
власному сервері зовнішня база — це ще один сервіс, який може відмовити
незалежно від магазину, і ще один рахунок.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from shop.repo.base import Repository


@asynccontextmanager
async def open_repo() -> AsyncIterator[Repository]:
    from shop.db import SessionMaker
    from shop.repo.sql import SqlRepository

    async with SessionMaker() as session:
        yield SqlRepository(session)


async def get_repo() -> AsyncIterator[Repository]:
    """Залежність для FastAPI."""
    async with open_repo() as repo:
        yield repo
