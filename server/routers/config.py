"""服务端运行时配置路由。

GET /config 返回全部配置（所有登录用户可读，api_key 脱敏）。
PUT /config 更新配置（仅 admin key 可操作），更新后实时写入 extractor 运行时变量。
"""
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from server.database import get_db
from server.models import ApiKey, ServerConfig as ServerConfigModel
from server.routers.auth import get_admin_key, get_current_key
from server.schemas import ConfigItemOut, ConfigUpdate

router = APIRouter(prefix="/config", tags=["config"])

_DEFAULT_CONFIG = {
    "extractor_api_key": "",
    "extractor_base_url": "https://oneapi-comate.baidu-int.com/v1",
    "extractor_model": "gpt-5.4",
}


def _mask_api_key(value: str) -> str:
    """
    对 API Key 值进行脱敏，只显示最后 4 位。

    参数:
        value: 原始 API Key 字符串。

    返回值:
        脱敏后的字符串；为空时返回空字符串。
    """
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


def seed_default_config(db: DBSession) -> None:
    """
    若 server_config 表中缺少默认配置项，写入默认值。

    参数:
        db: 数据库会话。

    返回值:
        无；幂等，重复调用无副作用。
    """
    for key, value in _DEFAULT_CONFIG.items():
        if not db.get(ServerConfigModel, key):
            db.add(ServerConfigModel(key=key, value=value))
    db.commit()


@router.get("", response_model=List[ConfigItemOut])
def get_config(
    db: DBSession = Depends(get_db),
    _key: Optional[ApiKey] = Depends(get_current_key),
):
    """
    返回全部配置项，api_key 值脱敏。

    参数:
        db: 数据库会话。

    返回值:
        ConfigItemOut 列表。
    """
    rows = db.query(ServerConfigModel).all()
    result = []
    for row in rows:
        value = row.value or ""
        if row.key == "extractor_api_key":
            value = _mask_api_key(value)
        result.append(ConfigItemOut(key=row.key, value=value))
    return result


@router.put("")
def update_config(
    body: ConfigUpdate,
    db: DBSession = Depends(get_db),
    _key: ApiKey = Depends(get_admin_key),
):
    """
    更新配置项，更新后实时写入 extractor 运行时变量。仅 admin key 可调用。

    参数:
        body: 包含可选配置字段的请求体。
        db: 数据库会话。

    返回值:
        {"ok": true}
    """
    from server.services import extractor as _extractor

    updates = {
        "extractor_api_key": body.extractor_api_key,
        "extractor_base_url": body.extractor_base_url,
        "extractor_model": body.extractor_model,
    }
    for key, value in updates.items():
        if value is None:
            continue
        row = db.get(ServerConfigModel, key)
        if row:
            row.value = value
        else:
            db.add(ServerConfigModel(key=key, value=value))

    db.commit()

    # 实时更新 extractor 运行时变量
    if body.extractor_api_key is not None:
        _extractor._api_key = body.extractor_api_key
    if body.extractor_base_url is not None:
        _extractor._base_url = body.extractor_base_url
    if body.extractor_model is not None:
        _extractor._model = body.extractor_model

    return {"ok": True}
