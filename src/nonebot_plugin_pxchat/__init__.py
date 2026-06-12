from nonebot import on_message, logger, get_driver, require, get_plugin_config, get_bot
require("nonebot_plugin_localstore")
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, Message, MessageSegment
from .chat import should_reply_in_group, get_chat_reply_with_tools, thinking_group_reply
from .context import get_context, add_message, clear_context, load_contexts, get_unjudged_messages, mark_messages_judged, has_unjudged_messages
from .memory import load_memories, record_group_user_message, get_group_memory_hint, record_interaction
from .state import load_state, record_reply as state_record_reply, record_group_message as state_record_group_message, skip_reply as state_skip_reply, get_consecutive_replies
from .admin import execute_mute_if_needed, check_bot_is_admin
from .manager import chat_manager
from .commands import *
from .send2root import *
from .image2txt import *
from .config import *
from .log import logger as pxchat_logger, log_shutdown
import asyncio
import random
import json
import time
import re
from .mcp_manager import *
from typing import Dict, Set

__plugin_meta__ = PluginMetadata(
    name="pxchat",
    description="基于AI的聊天插件，支持大模型任意切换、上下文记忆、群聊智能参与、图片识别、MCP等功能",
    usage="使用px about命令获取插件信息，支持指令配置",
    type="application",
    homepage="https://github.com/whopxxx/nonebot-plugin-pxchat",
    config=PluginConfig,
    supported_adapters={"~onebot.v11"},
)

# 初始化管理器和上下文
load_contexts()
load_memories()
load_state()
# 读取配置文件
get_plugin_config(PluginConfig)
# 创建消息处理器，不限制规则，在handle中自行判断
chat = on_message(priority=50, block=False)

# ============================================================
# 延迟回复机制
# ============================================================

# 每群的延迟回复计时器 {group_id: asyncio.Task}
group_reply_timers: Dict[str, asyncio.Task] = {}
# 每群触发计时器的用户 {group_id: user_id}
group_timer_user: Dict[str, str] = {}
# 每群是否为@触发的计时器 {group_id: bool}
group_timer_is_at: Dict[str, bool] = {}
# 每群当前计时器的初始延迟 {group_id: delay_seconds}
group_timer_delay: Dict[str, float] = {}
# 每群最后一条消息时间 {group_id: timestamp}
group_last_message_time: Dict[str, float] = {}
# 群聊安静窗口：非@消息在最后一条群消息后至少等待这些秒数再判断
GROUP_QUIET_WINDOW = 8.0

# 模型建议的typing延迟映射
_TYPING_DELAY_MAP = {
    "fast": (3.0, 6.0),
    "normal": (8.0, 15.0),
    "slow": (15.0, 25.0),
}


def _typing_delay_range(hint: str) -> tuple[float, float]:
    """根据模型建议返回(最小延迟, 最大延迟)"""
    return _TYPING_DELAY_MAP.get(hint, _TYPING_DELAY_MAP["normal"])


def _extract_user_ids_from_messages(messages: list) -> list[str]:
    user_ids = []
    for msg in messages:
        content = msg.get("content", "")
        for user_id in re.findall(r"用户(\d+)\(", content):
            if user_id not in user_ids:
                user_ids.append(user_id)
    return user_ids


def _get_memory_hint(group_id: str, messages: list) -> str:
    return get_group_memory_hint(group_id, _extract_user_ids_from_messages(messages))


def _extract_at_mentions(event) -> str:
    """从消息中提取@提及的用户（排除机器人自己），返回 '用户123 用户456'"""
    bot_id = None
    try:
        bot_id = str(get_bot().self_id)
    except Exception:
        pass
    at_users = []
    for seg in event.message:
        if seg.type == "at" and seg.data.get("qq") != "all":
            qq = str(seg.data.get("qq", ""))
            if qq and qq != bot_id:
                at_users.append(f"用户{qq}")
    return " ".join(at_users)


def _extract_reply_info(event, key: str) -> str:
    """
    从消息中提取回复/引用信息，返回 '[回复了 用户123: "xxx"]' 或 ''。
    从上下文中查找被回复的消息内容。
    """
    for seg in event.message:
        if seg.type == "reply":
            replied_id = str(seg.data.get("id", ""))
            if not replied_id:
                continue
            # 从上下文中查找原消息
            context = get_context(key)
            for msg in context:
                if msg.get("msg_id", "").startswith(replied_id):
                    content = msg.get("content", "")
                    # 提取消息摘要（前60字）
                    summary = content[:60].replace("\n", " ")
                    if len(content) > 60:
                        summary += "..."
                    return f"[回复了 {summary}]"
            # 上下文中没找到，仅标记
            return f"[回复了消息{replied_id}]"
    return ""


def _extract_structured_text(event) -> str:
    """
    从结构化消息段中提取文本（json/share/markdown/lightapp等）。
    get_plaintext() 对这些类型返回空字符串。
    """
    for seg in event.message:
        t = seg.type
        data = seg.data
        if t == "json" and data.get("data"):
            try:
                import json as _json
                obj = _json.loads(data["data"])
                # 提取常见字段
                for field in ("prompt", "desc", "title", "content", "text", "meta"):
                    v = obj.get(field, "") or (obj.get("meta", {}).get(field, "") if isinstance(obj.get("meta"), dict) else "")
                    if v:
                        return f"[卡片: {str(v)[:100]}]"
            except Exception:
                return "[json卡片]"
        elif t == "share":
            title = data.get("title", "")
            content = data.get("content", "")
            text = f"{title} {content}".strip()
            return f"[分享: {text[:100]}]" if text else "[分享链接]"
        elif t == "markdown" and data.get("content"):
            return f"[markdown: {str(data['content'])[:100]}]"
        elif t == "lightapp":
            return "[小程序卡片]"
        elif t == "music":
            title = data.get("title", "")
            return f"[音乐分享: {title[:80]}]" if title else "[音乐分享]"
        elif t == "contact":
            ctype = data.get("type", "")
            cid = data.get("id", "")
            return f"[推荐{'好友' if ctype == 'qq' else '群'}: {cid}]"
        elif t == "forward":
            return "[转发消息]"
    return ""


async def _handle_mute_recommendation(group_id: str, mute_users: list):
    """处理模型返回的禁言建议"""
    if not mute_users:
        return
    targets = []
    default_duration = 0
    for entry in mute_users:
        if isinstance(entry, dict):
            uid = str(entry.get("user_id", "")).strip()
            hint = entry.get("duration_hint", 0)
            if uid:
                targets.append(uid)
                if hint and (default_duration == 0 or hint < default_duration):
                    default_duration = int(hint)
    if targets:
        pxchat_logger.info(f"[管理] 群{group_id} 禁言建议: {targets}")
        success = await execute_mute_if_needed(group_id, targets, default_duration)
        if success:
            pxchat_logger.info(f"[管理] 群{group_id} 已禁言: {success}")


def _should_reply_by_confidence(model_says_reply: bool, confidence: float, group_id: str) -> tuple[bool, float]:
    """
    综合模型判断、动态门槛、连续回复惩罚决定是否回复。
    模型说"不回" → 直接拒绝
    模型说"回" + confidence ≥ 门槛 → 回复
    连续回复越多 → 门槛额外抬高
    """
    if not model_says_reply:
        return False, 0
    prob = group_manager.get_probability(group_id)
    threshold = round(max(0.50, 1.0 - prob * 0.5), 2)
    # 连续回复惩罚：每多一轮 +0.10
    consecutive = get_consecutive_replies(group_id)
    if consecutive > 0:
        extra = consecutive * 0.10
        threshold = round(min(0.95, threshold + extra), 2)
    should = confidence >= threshold
    if not should:
        extra_info = f" 连续{consecutive}轮" if consecutive > 0 else ""
        pxchat_logger.info(
            f"[延迟] 群{group_id} confidence={confidence:.2f} < 门槛{threshold:.2f}(参与度{prob:.2f}{extra_info})"
        )
    return should, threshold


def _record_reply_interactions(group_id: str, context_messages: list):
    """从上下文中提取参与本轮对话的用户，记录互动"""
    user_ids = _extract_user_ids_from_messages(context_messages[-8:])
    if not user_ids:
        return
    for uid in user_ids[:3]:  # 最多记录3人
        record_interaction(group_id, uid, "群聊参与")


async def _delayed_reply_check(group_id: str, key: str, is_at: bool = False, delay: float = 15.0):
    """
    延迟回复检查
    - 被@：等待3-5秒后直接回复
    - 非@：等待15-20秒后结合上下文判断是否回复
    """
    await asyncio.sleep(delay)

    if not is_at:
        elapsed = time.time() - group_last_message_time.get(group_id, 0)
        if elapsed < GROUP_QUIET_WINDOW:
            remaining = max(1.0, GROUP_QUIET_WINDOW - elapsed)
            task = asyncio.create_task(_delayed_reply_check(group_id, key, is_at=False, delay=remaining))
            group_reply_timers[group_id] = task
            group_timer_is_at[group_id] = False
            # 安静窗口续等不重置延迟值，group_timer_delay 保持不变
            pxchat_logger.info(f"[延迟] 群{group_id} 仍在说话，继续等待{remaining:.1f}s")
            return

    # 计时器触发，清理引用（先保存需要的值）
    timer_user_id = group_timer_user.get(group_id)
    if group_id in group_reply_timers:
        del group_reply_timers[group_id]
    if group_id in group_timer_user:
        del group_timer_user[group_id]
    if group_id in group_timer_is_at:
        del group_timer_is_at[group_id]
    if group_id in group_timer_delay:
        del group_timer_delay[group_id]

    # 检查群是否仍然启用
    if not chat_manager.is_group_enabled(group_id):
        pxchat_logger.info(f"[延迟] 群{group_id} 已禁用")
        return

    # 被@触发的计时器：直接回复，不需要判断
    if is_at:
        unjudged = get_unjudged_messages(key)
        unjudged_ids = [msg.get("msg_id") for msg in unjudged if msg.get("msg_id")]

        # 识别图片缓存
        await _recognize_cached_images(key, unjudged)
        memory_hint = _get_memory_hint(group_id, get_context(key))

        # 生成回复
        try:
            reply = await get_chat_reply_with_tools(
                get_context(key),
                True,
                reply_style="short",
                decision_reason="有人直接@你",
                memory_hint=memory_hint,
                group_id=group_id,
            )
            add_message(key, "assistant", reply)
            ctx_before_add = get_context(key)[:-1]
            await send_delayed_group_reply(group_id, reply, ctx_before_add)
            state_record_reply(group_id)
        except Exception as e:
            error_msg = f"@回复生成异常:\n {str(e)}"
            pxchat_logger.error(error_msg)
            await send_error_to_super_users(error_msg, None)

        if unjudged_ids:
            mark_messages_judged(key, unjudged_ids)
        return

    # 非@触发的计时器：需要判断是否回复
    unjudged = get_unjudged_messages(key)
    if not unjudged:
        pxchat_logger.info(f"[延迟] 群{group_id} 无新消息")
        return

    # 收集未判断消息的ID，用于标记
    unjudged_ids = [msg.get("msg_id") for msg in unjudged if msg.get("msg_id")]

    # 按需前置识别图片（仅当未判断消息包含图片时触发）
    await _recognize_cached_images(key, unjudged)

    # 识别后获取最新上下文（确保判断时能看到识别结果）
    full_context = get_context(key)
    memory_hint = _get_memory_hint(group_id, full_context)

    # 根据是否为思考模型走不同逻辑
    is_thinking = chat_manager.is_thinking_enabled()

    if is_thinking:
        # ===== 思考模型：一次调用同时判断+回复 =====
        try:
            result = await thinking_group_reply(full_context, unjudged_ids, memory_hint, group_id=group_id)
        except Exception as e:
            error_msg = f"思考模式延迟回复异常:\n {str(e)}"
            pxchat_logger.error(error_msg)
            await send_error_to_super_users(error_msg, None)
            if unjudged_ids:
                mark_messages_judged(key, unjudged_ids)
            return

        # 处理禁言建议（回复或不回复都可能触发）
        mute_users = result.get("mute_users", [])
        if mute_users:
            await _handle_mute_recommendation(group_id, mute_users)

        # 标记已判断
        if unjudged_ids:
            mark_messages_judged(key, unjudged_ids)

        # 动态置信度门槛（结合活跃度概率，模型判断优先）
        model_says_reply = result.get("should_reply", False)
        confidence = result.get("confidence", 0)
        should_reply, threshold = _should_reply_by_confidence(model_says_reply, confidence, group_id)
        if not should_reply:
            if not model_says_reply:
                pxchat_logger.info(f"[延迟] 群{group_id} 思考:不回复 (模型判断)")
            else:
                pxchat_logger.info(f"[延迟] 群{group_id} 思考:不回复 (conf={confidence:.2f}<{threshold:.2f})")
            state_skip_reply(group_id)
            return

        pxchat_logger.info(f"[延迟] 群{group_id} 思考:回复 (conf={confidence:.2f}≥{threshold:.2f})")
        group_manager.renew_probability(group_id)

        # 直接使用合并调用返回的回复内容
        reply = result.get("reply")
        if reply:
            add_message(key, "assistant", reply)
            await send_delayed_group_reply(group_id, reply, full_context)
            state_record_reply(group_id)
    else:
        # ===== 非思考模型：先判断再回复（两步调用） =====
        try:
            decision = await should_reply_in_group(full_context, unjudged_ids, memory_hint, group_id=group_id)
        except Exception as e:
            error_msg = f"延迟回复判断异常:\n {str(e)}"
            pxchat_logger.error(error_msg)
            await send_error_to_super_users(error_msg, None)
            if unjudged_ids:
                mark_messages_judged(key, unjudged_ids)
            return

        # 处理禁言建议（回复或不回复都可能触发）
        mute_users = decision.get("mute_users", [])
        if mute_users:
            await _handle_mute_recommendation(group_id, mute_users)

        # 无论判断结果如何，标记这些消息为已判断
        if unjudged_ids:
            mark_messages_judged(key, unjudged_ids)

        # 动态置信度门槛（结合活跃度概率，模型判断优先）
        model_says_reply = decision.get("should_reply", False)
        confidence = decision.get("confidence", 0)
        should_reply, threshold = _should_reply_by_confidence(model_says_reply, confidence, group_id)
        if not should_reply:
            if not model_says_reply:
                pxchat_logger.info(f"[延迟] 群{group_id} 判断:不回复 (模型判断)")
            else:
                pxchat_logger.info(f"[延迟] 群{group_id} 判断:不回复 (conf={confidence:.2f}<{threshold:.2f})")
            state_skip_reply(group_id)
            return

        pxchat_logger.info(f"[延迟] 群{group_id} 判断:回复 (conf={confidence:.2f}≥{threshold:.2f}) {decision.get('reason', '')}")
        group_manager.renew_probability(group_id)

        # 生成回复
        try:
            reply = await get_chat_reply_with_tools(
                full_context,
                True,
                reply_style=decision.get("reply_style", "normal"),
                decision_reason=decision.get("reason", ""),
                memory_hint=memory_hint,
                group_id=group_id,
                skip_personality=True,
            )
            add_message(key, "assistant", reply)
            await send_delayed_group_reply(group_id, reply, full_context)
            state_record_reply(group_id)
            # 记录互动（从上下文提取参与用户）
            _record_reply_interactions(group_id, full_context)
        except Exception as e:
            error_msg = f"延迟回复生成异常:\n {str(e)}"
            pxchat_logger.error(error_msg)
            await send_error_to_super_users(error_msg, None)


async def _recognize_cached_images(key: str, unjudged_messages: list):
    """对未判断消息中缓存的图片进行识别，将识别结果更新到上下文中"""
    if not chat_manager.is_image_recognition_enabled():
        return

    context = get_context(key)
    for msg in unjudged_messages:
        msg_id = msg.get("msg_id")
        if not msg_id:
            continue
        # 检查该消息是否有图片缓存
        cached_images = image_cache.pop(msg_id, None)
        if not cached_images:
            continue

        # 在上下文中找到该消息并追加识别结果
        for ctx_msg in context:
            if ctx_msg.get("msg_id") == msg_id and "[图片待识别]" in ctx_msg.get("content", ""):
                recognition_list = []
                for i, img_data in enumerate(cached_images):
                    try:
                        result = await recognize_image_from_cache(img_data)
                        recognition_list.append(f"[图片{i + 1}的识别结果]{result}")
                    except Exception as e:
                        error_msg = f"图片识别失败: {str(e)}"
                        pxchat_logger.info(error_msg)
                        recognition_list.append(f"[图片{i + 1}识别失败]")

                # 更新上下文中的消息内容
                ctx_msg["content"] = ctx_msg["content"].replace(
                    "[图片待识别]",
                    "\n".join(recognition_list)
                )
                pxchat_logger.info(f"消息{msg_id} 图片识别完成")
                break

    # 保存更新后的上下文
    from .context import save_contexts
    save_contexts()


def start_or_reset_group_timer(group_id: str, user_id: str, key: str, is_at: bool = False):
    """
    启动或重置群级别的延迟回复计时器
    重置时保留原始等待时长，不重新随机
    """
    group_last_message_time[group_id] = time.time()

    if group_id in group_reply_timers and group_id in group_timer_user:
        current_is_at = group_timer_is_at.get(group_id, False)
        if is_at or not current_is_at:
            # @消息使用新随机短延迟；非@重置时复用已存储的延迟
            if is_at:
                delay = random.uniform(3, 5)
                group_timer_delay[group_id] = delay
            else:
                delay = group_timer_delay.get(group_id, random.uniform(15, 20))
            group_reply_timers[group_id].cancel()
            task = asyncio.create_task(_delayed_reply_check(group_id, key, is_at, delay))
            group_reply_timers[group_id] = task
            group_timer_user[group_id] = user_id
            group_timer_is_at[group_id] = is_at
            pxchat_logger.info(f"[延迟] 群{group_id} 新消息重置{'(@)' if is_at else ''}等待{delay:.1f}s")
        else:
            pxchat_logger.info(f"[延迟] 群{group_id} 已有@计时器，保留快速回复")
    else:
        # 无活跃计时器，启动新计时器
        delay = random.uniform(3, 5) if is_at else random.uniform(15, 20)
        group_timer_delay[group_id] = delay
        task = asyncio.create_task(_delayed_reply_check(group_id, key, is_at, delay))
        group_reply_timers[group_id] = task
        group_timer_user[group_id] = user_id
        group_timer_is_at[group_id] = is_at
        pxchat_logger.info(f"[延迟] 群{group_id} 用户{user_id}{'(@)' if is_at else ''}等待{delay:.1f}s")


def cancel_group_timer(group_id: str):
    """取消群的延迟回复计时器"""
    if group_id in group_reply_timers:
        group_reply_timers[group_id].cancel()
        del group_reply_timers[group_id]
    if group_id in group_timer_user:
        del group_timer_user[group_id]
    if group_id in group_timer_is_at:
        del group_timer_is_at[group_id]
    if group_id in group_timer_delay:
        del group_timer_delay[group_id]
    if group_id in group_last_message_time:
        del group_last_message_time[group_id]


def cancel_all_group_timers():
    """取消所有延迟回复计时器"""
    for group_id in list(group_reply_timers.keys()):
        group_reply_timers[group_id].cancel()
    group_reply_timers.clear()
    group_timer_user.clear()
    group_timer_is_at.clear()
    group_last_message_time.clear()


async def send_delayed_group_reply(group_id: str, reply: str, context_messages: list = None):
    """发送延迟回复到群聊（不@任何人），支持引用回复"""
    try:
        bot = get_bot()
    except ValueError:
        pxchat_logger.error("[延迟回复] 无法获取Bot实例")
        return

    segments = []
    typing_hint = "normal"
    quote_target = None
    try:
        data = json.loads(reply)
        if isinstance(data, dict) and "reply" in data and isinstance(data["reply"], list):
            segments = [seg for seg in data["reply"] if seg and seg.strip()]
            typing_hint = data.get("typing_delay_hint", "normal")
            quote_target = data.get("quote_target")
    except (json.JSONDecodeError, TypeError):
        pxchat_logger.error("[延迟回复] 回复格式解析失败")
        return

    if not segments:
        return

    # 根据id精确查找需要引用的消息
    reply_prefix = ""
    if isinstance(quote_target, str) and quote_target.strip() and context_messages:
        target = quote_target.strip()
        for msg in context_messages:
            msg_id = msg.get("msg_id", "")
            if msg_id and msg_id.startswith(target):
                real_id = msg_id.split("_")[0]
                reply_prefix = f"[CQ:reply,id={real_id}]"
                break

    delay_range = _typing_delay_range(typing_hint)
    for i, segment in enumerate(segments):
        try:
            msg = reply_prefix + segment if i == 0 and reply_prefix else segment
            await bot.call_api("send_group_msg", group_id=int(group_id), message=msg)
            if i < len(segments) - 1:
                await asyncio.sleep(random.uniform(*delay_range))
        except Exception as e:
            pxchat_logger.error(f"[延迟回复] 发送消息失败: {e}")
            break


# ============================================================
# 图片缓存
# ============================================================

# 图片缓存 {msg_id: [image_bytes_1, image_bytes_2, ...]}
image_cache: Dict[str, list] = {}


async def cache_images(event: MessageEvent, msg_id: str) -> bool:
    """
    检测消息中的图片并下载缓存，返回是否包含图片
    """
    if not chat_manager.is_image_recognition_enabled():
        return False

    image_urls = []
    for seg in event.message:
        if seg.type == "image":
            url = seg.data.get("url")
            if url:
                image_urls.append(url)

    if not image_urls:
        return False

    cached_bytes = []
    for url in image_urls:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as session:
                response = await session.get(url)
                response.raise_for_status()
                cached_bytes.append(response.content)
                pxchat_logger.info(f"图片缓存: {url[:50]}... ({len(response.content)/1024:.0f}KB)")
        except Exception as e:
            pxchat_logger.warning(f"图片下载缓存失败: {e}")

    if cached_bytes:
        image_cache[msg_id] = cached_bytes
        return True
    return False


def cleanup_image_cache(msg_id: str = None):
    """清理图片缓存"""
    if msg_id:
        image_cache.pop(msg_id, None)
    else:
        image_cache.clear()


# ============================================================
# 消息分段发送
# ============================================================

async def send_split_messages(chat_handler, message: str, event: MessageEvent = None, delay_range: tuple = (8, 15)):
    """
    分段发送消息，支持@回复。延迟优先使用模型建议的 typing_delay_hint
    """
    if not message:
        return

    segments = []
    typing_hint = "normal"

    try:
        data = json.loads(message)
        if isinstance(data, dict) and "reply" in data and isinstance(data["reply"], list):
            segments = [segment for segment in data["reply"] if segment and segment.strip()]
            typing_hint = data.get("typing_delay_hint", "normal")
    except (json.JSONDecodeError, TypeError) as e:
        error_msg = f"处理聊天请求时发生异常:\n {str(e)}"
        await send_error_to_super_users(error_msg, event)
        return

    if not segments:
        return

    delay_range = _typing_delay_range(typing_hint)

    if event and hasattr(event, 'group_id') and event.group_id and event.is_tome():
        first_segment = segments[0]
        at_message = Message(f"[CQ:at,qq={event.user_id}] {first_segment}")
        await chat_handler.send(at_message)

        for segment in segments[1:]:
            await asyncio.sleep(random.uniform(*delay_range))
            await chat_handler.send(segment)
    else:
        for i, segment in enumerate(segments):
            await chat_handler.send(segment)
            if i < len(segments) - 1:
                await asyncio.sleep(random.uniform(*delay_range))


# ============================================================
# 消息处理主逻辑
# ============================================================

# 私聊无意义消息快速过滤（纯emoji、单标点、单字无意义、空消息）
_PRIVATE_MEANINGLESS_PATTERNS = re.compile(
    r"^[\s\x00-\x2f\x3a-\x40\x5b-\x60\x7b-\x7f\u2000-\u206f\ufe00-\ufe0f\uff00-\uffef]*$"
)
_PRIVATE_SKIP_SINGLE_CHARS = {"嗯", "哦", "好", "行", "是", "对", "啊", "呀", "哈", "呵", "嘿", "诶", "?", "？", "!", "！", ".", "。"}


def _is_meaningless_private_message(text: str) -> bool:
    """判断私聊消息是否无意义，可跳过回复"""
    if not text:
        return True
    # 纯标点/空白/特殊字符
    if _PRIVATE_MEANINGLESS_PATTERNS.match(text):
        return True
    # 单字无意义
    if len(text) <= 1 and text in _PRIVATE_SKIP_SINGLE_CHARS:
        return True
    return False


@chat.handle()
async def _(bot: Bot, event: MessageEvent):
    # 忽略机器人自己的消息（避免回复-触发-回复循环）
    if str(event.user_id) == str(event.self_id):
        return

    # 检查全局开关
    if not chat_manager.is_chat_enabled():
        return

    if not chat_manager.get_super_users():
        await chat.finish("请在配置文件中添加管理员账号")

    # 获取群聊ID
    group_id = getattr(event, "group_id", None)
    user_id = str(event.user_id)

    # 构建上下文key
    if group_id:
        group_id_str = str(group_id)
        if not chat_manager.is_group_enabled(group_id_str):
            return
        key = f"group_{group_id}"
        is_group = True
    else:
        key = user_id
        is_group = False

    user_msg2 = str(event.get_plaintext())
    if user_msg2.startswith("px "):
        return

    if user_msg2 in ["清除对话", "重置对话"]:
        clear_context(key)
        await chat.finish("已清除对话历史")

    # 生成消息唯一ID（使用消息ID+用户ID+时间戳）
    msg_id = f"{getattr(event, 'message_id', '')}_{user_id}_{int(time.time() * 1000)}"

    # 群聊特殊处理
    if is_group:
        # 检测并缓存图片（仅下载，不识别）
        has_images = await cache_images(event, msg_id)

        # 构建消息内容
        user_text = event.get_plaintext().strip()
        # 纯文本为空时尝试从结构化消息段提取（json卡片/分享/小程序等）
        if not user_text:
            user_text = _extract_structured_text(event)
        # 群昵称优先于QQ昵称
        if event.sender:
            nickname = event.sender.card or event.sender.nickname or '未知用户'
        else:
            nickname = '未知用户'
        # 提取消息中的@提及（get_plaintext会丢失@信息）
        at_mentions = _extract_at_mentions(event)
        record_group_user_message(group_id_str, user_id, nickname, user_text)
        state_record_group_message(group_id_str, user_text)
        # 突发检测：短时间大量消息时重置参与度
        group_manager.record_message_and_check_burst(group_id_str)
        user_info = f"用户{user_id}({nickname})说："
        if at_mentions:
            user_info += f"[@{at_mentions}] "
        # 提取回复/引用信息（get_plaintext会丢失CQ:reply）
        reply_info = _extract_reply_info(event, key)
        if reply_info:
            user_info += f"{reply_info} "
        if has_images:
            user_message_with_info = f"{user_info}: {user_text}\n[图片待识别]"
        else:
            user_message_with_info = f"{user_info}: {user_text}"

        # 添加到上下文（带msg_id）
        add_message(key, "user", user_message_with_info, msg_id)

        # 判断是否被@
        is_at = event.is_tome()

        if is_at:
            pxchat_logger.info(f"群聊被@")
            group_manager.renew_probability(group_id_str)
            # 被@也走延迟计时器，但用更短的时间
            start_or_reset_group_timer(group_id_str, user_id, key, is_at=True)
            return
        else:
            # 非@，启动/重置延迟回复计时器
            start_or_reset_group_timer(group_id_str, user_id, key, is_at=False)
            return
    else:
        # 私聊：过滤无意义消息后处理
        user_text = event.get_plaintext().strip()
        # 跳过纯表情/单标点/空消息等无意义内容
        if _is_meaningless_private_message(user_text):
            pxchat_logger.info(f"[私聊] 跳过无意义消息: {user_text[:30]}")
            return

        # 私聊延迟1-3秒，模拟阅读/思考
        await asyncio.sleep(random.uniform(1.0, 3.0))

        user_msg = await event_proc(event)
        add_message(key, "user", user_msg)

    # 调用聊天接口（仅私聊走到这里，群聊都走延迟回复）
    try:
        reply = await get_chat_reply_with_tools(get_context(key), is_group)
        add_message(key, "assistant", reply)
        await send_split_messages(chat, reply, event if is_group else None)

    except Exception as e:
        error_msg = f"处理聊天请求时发生异常:\n {str(e)}"
        await send_error_to_super_users(error_msg, event)
        await chat.send("抱歉，处理消息时出现了问题，已通知管理员")


# ============================================================
# 图片识别（私聊/被@时立即使用）
# ============================================================

async def event_proc(event: MessageEvent):
    """私聊消息预处理：立即识别图片"""
    user_text = event.get_plaintext().strip()
    recognition_msg = f"{user_text}\n"
    if chat_manager.is_image_recognition_enabled():
        image_urls = []
        for seg in event.message:
            if seg.type == "image":
                image_urls.append(seg.data.get("url"))
        if image_urls:
            try:
                recognition_list = []
                for i, image_url in enumerate(image_urls):
                    result = await recognize_image(image_url)
                    recognition_list.append(f"[图片{i + 1}的识别结果]{result}")
                recognition_msg += "\n".join(recognition_list)
            except Exception as e:
                pxchat_logger.info(f"图片识别失败: {e}")
                await send_error_to_super_users(f"图片识别失败: {e}", event)
                recognition_msg += f"\n[图片识别失败](你现在还没有图片识别的能力)"
    return recognition_msg


# ============================================================
# 活跃度管理器
# ============================================================

group_timers: Dict[str, asyncio.Task] = {}
group_probability_states: Dict[str, float] = {}
# 消息突发检测：{group_id: [timestamp, ...]}
_group_burst_times: Dict[str, list[float]] = {}
_BURST_WINDOW = 30     # 检测窗口（秒）
_BURST_THRESHOLD = 10  # 触发阈值（条数）

class GroupProbabilityManager:
    """群聊智能参与管理器"""

    def __init__(self):
        self._shutting_down = False
        pxchat_logger.info(f"参与度管理器初始化完成，全局基础参与度: {chat_manager.get_group_chat_probability()}")

    def record_message_and_check_burst(self, group_id: str):
        """
        记录消息时间戳，如果短时间大量消息（突发），重置参与度到基础值。
        群聊突然活跃时不用等待衰减恢复，立刻回到积极状态。
        """
        now = time.time()
        times = _group_burst_times.setdefault(group_id, [])
        times.append(now)
        # 清理过期时间戳
        cutoff = now - _BURST_WINDOW
        _group_burst_times[group_id] = [t for t in times if t > cutoff]
        recent = len(_group_burst_times[group_id])

        if recent >= _BURST_THRESHOLD:
            base_prob = chat_manager.get_group_probability(group_id)
            current = group_probability_states.get(group_id, base_prob)
            if current < base_prob:
                group_probability_states[group_id] = base_prob
                # 取消正在进行的衰减任务，因为已经重置
                if group_id in group_timers:
                    task = group_timers[group_id]
                    if not task.done():
                        task.cancel()
                    del group_timers[group_id]
                pxchat_logger.info(
                    f"[突发] 群{group_id} {_BURST_WINDOW}s内{recent}条消息，"
                    f"参与度 {current:.2f}→{base_prob:.2f}"
                )

    async def _decay_task(self, group_id: str):
        """参与度衰减：先等30秒保持boost，然后每120秒衰减0.1，最低保持基础值的20%"""
        try:
            # 30秒boost期
            await asyncio.sleep(30)

            if self._shutting_down:
                base_prob = chat_manager.get_group_probability(group_id)
                group_probability_states[group_id] = round(base_prob, 2)
                if group_id in group_timers:
                    del group_timers[group_id]
                return

            # boost期结束，恢复基础值，开始衰减
            base_prob = chat_manager.get_group_probability(group_id)
            min_prob = round(base_prob * 0.2, 2)
            group_probability_states[group_id] = round(base_prob, 2)
            pxchat_logger.info(f"群{group_id} boost结束，参与度恢复: {round(base_prob, 2):.2f}")

            while not self._shutting_down:
                await asyncio.sleep(60)

                if self._shutting_down:
                    break

                current_prob = group_probability_states.get(group_id, 0.0)
                new_prob = max(min_prob, round(current_prob - 0.1, 2))

                group_probability_states[group_id] = new_prob
                pxchat_logger.info(f"群{group_id} 参与度衰减: {current_prob:.2f}→{new_prob:.2f}")

                if new_prob <= min_prob:
                    pxchat_logger.info(f"群{group_id} 参与度已达下限{min_prob:.2f}")
                    if group_id in group_timers:
                        del group_timers[group_id]
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            pxchat_logger.error(f"群{group_id} 衰减异常: {e}")
            if group_id in group_timers:
                del group_timers[group_id]
            if group_id in group_probability_states:
                del group_probability_states[group_id]

    def renew_probability(self, group_id: str):
        """续租参与度，提升到基础值的1.5倍（上限0.9），30秒后恢复"""
        if self._shutting_down:
            return False
        try:
            base_prob = chat_manager.get_group_probability(group_id)
            boosted_prob = min(0.80, round(base_prob * 1.2, 2))
            group_probability_states[group_id] = boosted_prob

            if group_id in group_timers:
                task = group_timers[group_id]
                if not task.done():
                    task.cancel()
                del group_timers[group_id]

            task = asyncio.create_task(self._decay_task(group_id))
            group_timers[group_id] = task

            pxchat_logger.info(f"群{group_id} 参与度boost: {boosted_prob:.2f}")
            return True

        except Exception as e:
            pxchat_logger.error(f"群{group_id} 续租失败: {e}")
            return False

    def get_probability(self, group_id: str) -> float:
        """获取活跃度，无记录时返回该群的基础概率"""
        prob = group_probability_states.get(group_id, None)
        if prob is None:
            return chat_manager.get_group_probability(group_id)
        return prob

    def has_active_timer(self, group_id: str) -> bool:
        return group_id in group_timers and not group_timers[group_id].done()

    async def shutdown(self):
        self._shutting_down = True
        pxchat_logger.info("开始关闭活跃度管理器...")

        for group_id, task in list(group_timers.items()):
            if not task.done():
                task.cancel()

        group_timers.clear()
        group_probability_states.clear()
        _group_burst_times.clear()

        pxchat_logger.info("活跃度管理器关闭完成")

group_manager: GroupProbabilityManager = GroupProbabilityManager()


# ============================================================
# 调试命令
# ============================================================

debug_cmd = on_command("px activity", priority=5, block=True)

@debug_cmd.handle()
async def handle_debug_cmd(event: MessageEvent):
    if not await check_super_user(event):
        await mcp_cmd.finish("你没有权限")

    tasks = asyncio.all_tasks()
    current_task = asyncio.current_task()

    delayed_timer_count = len(group_reply_timers)
    delayed_timer_details = []
    for gid, task in group_reply_timers.items():
        delayed_timer_details.append(f"  群{gid}: {'运行中' if not task.done() else '已结束'}")

    status_lines = [
        "🤖 任务调试信息:",
        f"📊 总任务数: {len(tasks)}",
        f"🎯 活跃度管理器任务数: {len(group_timers)}",
        f"📈 活跃度状态数: {len(group_probability_states)}",
        f"⏱️ 延迟回复计时器数: {delayed_timer_count}",
        f"🖼️ 图片缓存数: {len(image_cache)}",
        "",
        "📋 活跃度管理器状态:",
        f"  活跃群组: {list(group_timers.keys())}",
        f"  活跃度状态: {group_probability_states}",
        "",
        "📋 延迟回复计时器状态:",
    ]
    if delayed_timer_details:
        status_lines.extend(delayed_timer_details)
    else:
        status_lines.append("  无活跃计时器")

    await debug_cmd.finish("\n".join(status_lines))


# ============================================================
# 关闭钩子
# ============================================================

driver = get_driver()

@driver.on_shutdown
async def shutdown_hook():
    cancel_all_group_timers()

    cleanup_image_cache()

    if group_manager:
        await group_manager.shutdown()

    log_shutdown(pxchat_logger)
