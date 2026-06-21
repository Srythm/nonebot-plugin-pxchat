"""
机器人群管理权限模块
- 自动检测机器人在群内的管理员/群主身份
- 提供禁言 API 封装
- 缓存管理员状态避免重复查询
"""
import asyncio
import time

from nonebot import get_bot

from .log import logger as pxchat_logger
from .manager import chat_manager

# 管理员状态缓存 {group_id: (timestamp, is_admin)}
_admin_cache: dict[str, tuple[float, bool]] = {}
_ADMIN_CACHE_TTL = 600  # 10分钟缓存
# 自动禁言冷却 {group_id: last_mute_timestamp}
_mute_cooldown: dict[str, float] = {}


def _get_bot_id() -> int:
    """获取机器人自己的QQ号"""
    try:
        return get_bot().self_id
    except Exception:
        return 0


async def check_bot_is_admin(group_id: str) -> bool:
    """
    检测机器人是否在指定群内拥有管理员/群主权限
    自动缓存结果 10 分钟
    """
    cache_entry = _admin_cache.get(group_id)
    if cache_entry and time.time() - cache_entry[0] < _ADMIN_CACHE_TTL:
        return cache_entry[1]

    bot_id = _get_bot_id()
    if not bot_id:
        pxchat_logger.warning(f"[管理] 无法获取Bot ID，假定无管理权限")
        return False

    try:
        bot = get_bot()
        info = await bot.call_api(
            "get_group_member_info",
            group_id=int(group_id),
            user_id=bot_id,
        )
        role = str(info.get("role", "member")).lower()
        is_admin = role in ("owner", "admin")
        _admin_cache[group_id] = (time.time(), is_admin)
        pxchat_logger.info(f"[管理] 群{group_id} Bot角色={role}, 管理员={is_admin}")
        return is_admin
    except Exception as e:
        pxchat_logger.warning(f"[管理] 检测群{group_id}管理员权限失败: {e}")
        _admin_cache[group_id] = (time.time(), False)
        return False


def set_bot_admin_override(group_id: str, is_admin: bool):
    """手动覆盖管理员状态（用于人工配置）"""
    _admin_cache[group_id] = (time.time(), is_admin)
    pxchat_logger.info(f"[管理] 群{group_id} 手动设置管理员={is_admin}")


def clear_admin_cache(group_id: str | None = None):
    """清除管理员状态缓存"""
    if group_id:
        _admin_cache.pop(str(group_id), None)
    else:
        _admin_cache.clear()


async def set_group_ban(group_id: str, user_id: str, duration: int) -> bool:
    """
    禁言/解禁群成员
    duration: 禁言秒数，0=解禁
    返回是否成功
    """
    try:
        bot = get_bot()
        await bot.call_api(
            "set_group_ban",
            group_id=int(group_id),
            user_id=int(user_id),
            duration=duration,
        )
        if duration > 0:
            pxchat_logger.info(f"[管理] 群{group_id} 禁言用户{user_id} {duration}秒")
        else:
            pxchat_logger.info(f"[管理] 群{group_id} 解禁用户{user_id}")
        return True
    except Exception as e:
        pxchat_logger.error(f"[管理] 群{group_id} 禁言失败: {e}")
        return False


def can_mute_now(group_id: str) -> bool:
    """检查是否超过自动禁言冷却时间"""
    cooldown = chat_manager.get_auto_mute_cooldown()
    last = _mute_cooldown.get(group_id, 0)
    return time.time() - last >= cooldown


def record_mute(group_id: str):
    """记录一次自动禁言，更新冷却时间"""
    _mute_cooldown[group_id] = time.time()


async def execute_mute_if_needed(
    group_id: str,
    mute_targets: list[str],
    duration: int,
) -> list[str]:
    """
    批量执行禁言。
    mute_targets: 需要禁言的用户ID列表
    duration: 禁言时长（秒）
    返回成功禁言的用户ID列表
    """
    if not mute_targets:
        return []
    if not await check_bot_is_admin(group_id):
        pxchat_logger.info(f"[管理] 群{group_id} Bot非管理员，跳过禁言")
        return []
    if not chat_manager.is_auto_mute_enabled():
        return []
    if not can_mute_now(group_id):
        pxchat_logger.info(f"[管理] 群{group_id} 禁言冷却中，跳过")
        return []

    # 限制每次最多禁言3人，避免误伤
    targets = mute_targets[:3]
    min_dur = chat_manager.get_auto_mute_min_duration()
    max_dur = chat_manager.get_auto_mute_max_duration()
    actual_duration = duration if duration > 0 else min_dur
    actual_duration = max(min_dur, min(actual_duration, max_dur))

    success = []
    for uid in targets:
        if await set_group_ban(group_id, uid, actual_duration):
            success.append(uid)
            await asyncio.sleep(0.3)  # 避免API限流

    if success:
        record_mute(group_id)
    return success
