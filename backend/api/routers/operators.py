"""Керування обліковими записами панелі. Доступно лише адміністратору."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import Principal, require_admin
from api.schemas import OperatorCreate, OperatorOut, OperatorUpdate
from shop.entities import OperatorRole
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.passwords import WeakPassword, hash_password, validate

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("", response_model=list[OperatorOut])
async def list_operators(repo: Repository = Depends(get_repo)):
    return await repo.list_operators()


@router.post("", response_model=OperatorOut, status_code=201)
async def create_operator(data: OperatorCreate, repo: Repository = Depends(get_repo)):
    login = data.login.strip().lower()
    if await repo.get_operator_by_login(login):
        raise HTTPException(409, "Такий логін уже зайнятий")

    try:
        validate(data.password)
    except WeakPassword as exc:
        raise HTTPException(422, str(exc))

    return await repo.create_operator({
        "login": login,
        "name": data.name.strip(),
        "password_hash": hash_password(data.password),
        "role": data.role.value,
        "is_active": True,
    })


@router.put("/{operator_id}", response_model=OperatorOut)
async def update_operator(
    operator_id: int,
    data: OperatorUpdate,
    who: Principal = Depends(require_admin),
    repo: Repository = Depends(get_repo),
):
    target = await repo.get_operator(operator_id)
    if not target:
        raise HTTPException(404, "Оператора не знайдено")

    payload: dict = {}
    if data.name is not None:
        payload["name"] = data.name.strip()
    if data.role is not None:
        payload["role"] = data.role.value
    if data.is_active is not None:
        payload["is_active"] = data.is_active
    if data.password:
        try:
            validate(data.password)
        except WeakPassword as exc:
            raise HTTPException(422, str(exc))
        payload["password_hash"] = hash_password(data.password)

    # Не даємо адміністратору зняти права з себе самого: інакше можна
    # залишити систему без жодного адміністратора
    if who.operator_id == operator_id and (
        payload.get("role") == OperatorRole.OPERATOR.value or payload.get("is_active") is False
    ):
        raise HTTPException(409, "Не можна забрати доступ у себе — попросіть іншого адміністратора")

    return await repo.update_operator(operator_id, payload)


@router.delete("/{operator_id}/purge", status_code=204)
async def purge_operator(
    operator_id: int,
    who: Principal = Depends(require_admin),
    repo: Repository = Depends(get_repo),
):
    """Остаточне видалення. Історія замовлень зберігає імʼя рядком."""
    if who.operator_id == operator_id:
        raise HTTPException(409, "Не можна стерти власний обліковий запис")

    target = await repo.get_operator(operator_id)
    if not target:
        raise HTTPException(404, "Оператора не знайдено")

    # Останнього адміністратора стерти нікому: система лишилась би без
    # доступу до керування, якби пароль із .env теж загубився
    if target.is_admin:
        admins = [o for o in await repo.list_operators() if o.is_admin and o.is_active]
        if len(admins) <= 1:
            raise HTTPException(409, "Це єдиний адміністратор — спершу призначте іншого")

    await repo.purge_operator(operator_id)


@router.delete("/{operator_id}", status_code=204)
async def delete_operator(
    operator_id: int,
    who: Principal = Depends(require_admin),
    repo: Repository = Depends(get_repo),
):
    """Вимикає доступ. Запис лишається — він потрібен історії дій."""
    if who.operator_id == operator_id:
        raise HTTPException(409, "Не можна вимкнути власний обліковий запис")
    if not await repo.delete_operator(operator_id):
        raise HTTPException(404, "Оператора не знайдено")
