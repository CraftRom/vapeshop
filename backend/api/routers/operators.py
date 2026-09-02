"""Керування обліковими записами панелі. Доступно лише адміністратору."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import Principal, require_admin
from api.schemas import OperatorCreate, OperatorOut, OperatorUpdate
from shop import security_log as security
from shop.entities import OperatorRole
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.passwords import WeakPassword, hash_password, validate

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("", response_model=list[OperatorOut])
async def list_operators(repo: Repository = Depends(get_repo)):
    return await repo.list_operators()


@router.post("", response_model=OperatorOut, status_code=201)
async def create_operator(
    data: OperatorCreate,
    who: Principal = Depends(require_admin),
    repo: Repository = Depends(get_repo),
):
    login = data.login.strip().lower()
    if await repo.get_operator_by_login(login):
        raise HTTPException(409, "Такий логін уже зайнятий")

    try:
        validate(data.password)
    except WeakPassword as exc:
        raise HTTPException(422, str(exc))

    created = await repo.create_operator({
        "login": login,
        "name": data.name.strip(),
        "password_hash": hash_password(data.password),
        "role": data.role.value,
        "is_active": True,
    })
    # Поява нового доступу до панелі — подія безпеки незалежно від того,
    # хто його створив. Саме такі записи потрібні, коли за місяць треба
    # відповісти на питання «звідки тут узявся цей менеджер».
    security.record("security.operator.created", actor=who.login,
                    login=login, role=data.role.value)
    return created


@router.get("/{operator_id}", response_model=OperatorOut)
async def get_operator(operator_id: int, repo: Repository = Depends(get_repo)):
    found = await repo.get_operator(operator_id)
    if not found:
        raise HTTPException(404, "Менеджера не знайдено")
    return found


@router.put("/{operator_id}", response_model=OperatorOut)
async def update_operator(
    operator_id: int,
    data: OperatorUpdate,
    who: Principal = Depends(require_admin),
    repo: Repository = Depends(get_repo),
):
    target = await repo.get_operator(operator_id)
    if not target:
        raise HTTPException(404, "Менеджера не знайдено")

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
        payload.get("role") == OperatorRole.MANAGER.value or payload.get("is_active") is False
    ):
        raise HTTPException(409, "Не можна забрати доступ у себе — попросіть іншого адміністратора")

    updated = await repo.update_operator(operator_id, payload)
    # Перелічуємо, що саме змінили, але без значень: пароль у журнал не
    # потрапляє навіть у вигляді хеша.
    changed = sorted(k for k in payload if k != "password_hash")
    if "password_hash" in payload:
        changed.append("пароль")
    security.record("security.operator.changed", actor=who.login,
                    login=target.login, reason=", ".join(changed) or "без змін")
    return updated


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
        raise HTTPException(404, "Менеджера не знайдено")

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
    target = await repo.get_operator(operator_id)
    if not await repo.delete_operator(operator_id):
        raise HTTPException(404, "Менеджера не знайдено")
    security.record("security.operator.deleted", actor=who.login,
                    login=target.login if target else str(operator_id))
