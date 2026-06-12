from __future__ import annotations

import hashlib
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DBSession
from typing import List, Optional

from server.database import get_db
from server.models import ApiKey
from server.schemas import ApiKeyCreate, ApiKeyOut

router = APIRouter(prefix="/admin", tags=["admin"])

_bearer = HTTPBearer(auto_error=False)

# 不需要认证的路径：健康检查、WebSocket 握手、移动端静态资源
_EXEMPT_PATHS = {"/", "/ws"}
_EXEMPT_PREFIXES = ("/mobile",)


def _hash_key(plain: str) -> str:
    """对明文 key 做 SHA-256 哈希，用于存储和验证。

    参数:
        plain: 明文 API Key 字符串。

    返回值:
        64 位十六进制哈希字符串。
    """
    return hashlib.sha256(plain.encode()).hexdigest()


def _generate_key() -> str:
    """生成 ct- 前缀的随机 API Key。

    返回值:
        格式为 'ct-' + 64 位十六进制随机字符串。
    """
    return "ct-" + secrets.token_hex(32)


def get_current_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: DBSession = Depends(get_db),
) -> Optional[ApiKey]:
    """
    验证请求的 Bearer Token，返回对应的 ApiKey 记录。

    参数:
        request: 当前请求对象，用于读取路径做豁免判断。
        credentials: HTTP Bearer 凭证，auto_error=False 时无 header 返回 None。
        db: 数据库会话。

    返回值:
        通过验证的 ApiKey ORM 对象；豁免路径返回 None。
    """
    path = request.url.path
    if path in _EXEMPT_PATHS or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return None

    if not credentials:
        raise HTTPException(status_code=401, detail="missing api key")

    key_hash = _hash_key(credentials.credentials)
    api_key = db.query(ApiKey).filter(
        ApiKey.key_hash == key_hash,
        ApiKey.is_active == 1,
    ).first()
    if not api_key:
        raise HTTPException(status_code=401, detail="invalid api key")
    return api_key


def get_admin_key(key: ApiKey = Depends(get_current_key)) -> ApiKey:
    """
    确保当前 key 拥有 admin 权限。

    参数:
        key: 已验证的 ApiKey 对象。

    返回值:
        ApiKey 对象（is_admin 为真）。
    """
    if not key or not key.is_admin:
        raise HTTPException(status_code=403, detail="admin key required")
    return key


@router.post("/keys")
def create_key(
    body: ApiKeyCreate,
    db: DBSession = Depends(get_db),
    _: ApiKey = Depends(get_admin_key),
):
    """
    创建新 API Key，返回明文（仅此一次）。

    参数:
        body: 包含 label 和 is_admin 的请求体。
        db: 数据库会话。

    返回值:
        含 key（明文）、id 和 label 的字典。
    """
    plain = _generate_key()
    api_key = ApiKey(
        key_hash=_hash_key(plain),
        label=body.label,
        is_admin=int(body.is_admin),
        is_active=1,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {"id": api_key.id, "key": plain, "label": api_key.label}


@router.get("/keys", response_model=List[ApiKeyOut])
def list_keys(
    db: DBSession = Depends(get_db),
    _: ApiKey = Depends(get_admin_key),
):
    """
    列出所有 API Key（不含明文）。

    参数:
        db: 数据库会话。

    返回值:
        ApiKeyOut 列表。
    """
    return db.query(ApiKey).all()


@router.delete("/keys/{key_id}", status_code=204)
def delete_key(
    key_id: str,
    db: DBSession = Depends(get_db),
    _: ApiKey = Depends(get_admin_key),
):
    """
    禁用指定 API Key（软删除，置 is_active=0）。

    参数:
        key_id: 目标 ApiKey 的 UUID。
        db: 数据库会话。

    返回值:
        无（204 No Content）。
    """
    api_key = db.get(ApiKey, key_id)
    if not api_key:
        raise HTTPException(status_code=404, detail="key not found")
    api_key.is_active = 0
    db.commit()


def seed_admin_key(db: DBSession) -> None:
    """
    若 ADMIN_KEY 环境变量存在且 api_keys 表为空，写入首个 admin key。

    参数:
        db: 数据库会话。

    返回值:
        无；幂等，重复调用无副作用。
    """
    plain = os.getenv("ADMIN_KEY")
    if not plain:
        return
    if db.query(ApiKey).filter(ApiKey.key_hash == _hash_key(plain)).first():
        return
    db.add(ApiKey(
        key_hash=_hash_key(plain),
        label="admin",
        is_admin=1,
        is_active=1,
    ))
    db.commit()
