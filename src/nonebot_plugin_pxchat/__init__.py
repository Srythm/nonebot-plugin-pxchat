from nonebot import on_message, logger, get_driver, require, get_plugin_config, get_bot
require("nonebot_plugin_localstore")
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import MessageEvent, Bot, Message, MessageSegment
from .chat import should_reply_in_group, get_chat_reply_with_tools, thinking_group_reply
from .context import get_context, add_message, clear_context, load_contexts, get_unjudged_messages, mark_messages_judged, has_unjudged_messages
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
# 每群回复冷却 {group_id: last_reply_timestamp}
group_reply_cooldown: Dict[str, float] = {}
# 每群是否为@触发的计时器 {group_id: bool}
group_timer_is_at: Dict[str, bool] = {}
# 冷却时间（秒）
DELAYED_REPLY_COOLDOWN = 30


async def _delayed_reply_check(group_id: str, key: str, is_at: bool = False, delay: float = 15.0):
    """
    延迟回复检查
    - 被@：等待3-5秒后直接回复
    - 非@：等待15-20秒后结合上下文判断是否回复
    """
    await asyncio.sleep(delay)

    # 计时器触发，清理引用
    if group_id in group_reply_timers:
        del group_reply_timers[group_id]
    if group_id in group_timer_user:
        del group_timer_user[group_id]
    if group_id in group_timer_is_at:
        del group_timer_is_at[group_id]

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

        # 生成回复
        try:
            reply = await get_chat_reply_with_tools(get_context(key), True)
            add_message(key, "assistant", reply)
            await send_delayed_group_reply(group_id, reply)
            group_reply_cooldown[group_id] = time.time()
        except Exception as e:
            error_msg = f"@回复生成异常:\n {str(e)}"
            pxchat_logger.error(error_msg)
            clear_context(key)
            await send_error_to_super_users(error_msg, None)

        if unjudged_ids:
            mark_messages_judged(key, unjudged_ids)
        return

    # 非@触发的计时器：需要判断是否回复
    unjudged = get_unjudged_messages(key)
    if not unjudged:
        pxchat_logger.info(f"[延迟] 群{group_id} 无新消息")
        return

    now = time.time()
    if group_id in group_reply_cooldown and now - group_reply_cooldown[group_id] < DELAYED_REPLY_COOLDOWN:
        pxchat_logger.info(f"[延迟] 群{group_id} 冷却中")
        return

    # 检查概率
    dynamic_probability = group_manager.get_probability(group_id)
    if random.random() >= dynamic_probability:
        pxchat_logger.info(f"[延迟] 群{group_id} 概率未通过({dynamic_probability:.2f})")
        return

    # 收集未判断消息的ID，用于标记
    unjudged_ids = [msg.get("msg_id") for msg in unjudged if msg.get("msg_id")]

    # 按需前置识别图片（仅当未判断消息包含图片时触发）
    await _recognize_cached_images(key, unjudged)

    # 根据是否为思考模型走不同逻辑
    is_thinking = chat_manager.is_thinking_enabled()

    if is_thinking:
        # ===== 思考模型：一次调用同时判断+回复 =====
        try:
            result = await thinking_group_reply(unjudged)
        except Exception as e:
            error_msg = f"思考模式延迟回复异常:\n {str(e)}"
            pxchat_logger.error(error_msg)
            await send_error_to_super_users(error_msg, None)
            if unjudged_ids:
                mark_messages_judged(key, unjudged_ids)
            return

        # 标记已判断
        if unjudged_ids:
            mark_messages_judged(key, unjudged_ids)

        if not result.get("should_reply", False):
            pxchat_logger.info(f"[延迟] 群{group_id} 思考:不回复")
            return

        pxchat_logger.info(f"[延迟] 群{group_id} 思考:回复")
        group_manager.renew_probability(group_id)

        # 直接使用合并调用返回的回复内容
        reply = result.get("reply")
        if reply:
            add_message(key, "assistant", reply)
            await send_delayed_group_reply(group_id, reply)
            group_reply_cooldown[group_id] = time.time()
    else:
        # ===== 非思考模型：先判断再回复（两步调用） =====
        try:
            should_reply = await should_reply_in_group(unjudged)
        except Exception as e:
            error_msg = f"延迟回复判断异常:\n {str(e)}"
            pxchat_logger.error(error_msg)
            await send_error_to_super_users(error_msg, None)
            if unjudged_ids:
                mark_messages_judged(key, unjudged_ids)
            return

        # 无论判断结果如何，标记这些消息为已判断
        if unjudged_ids:
            mark_messages_judged(key, unjudged_ids)

        if not should_reply:
            pxchat_logger.info(f"[延迟] 群{group_id} 判断:不回复")
            return

        pxchat_logger.info(f"[延迟] 群{group_id} 判断:回复")
        group_manager.renew_probability(group_id)

        # 生成回复
        try:
            reply = await get_chat_reply_with_tools(get_context(key), True)
            add_message(key, "assistant", reply)
            await send_delayed_group_reply(group_id, reply)
            group_reply_cooldown[group_id] = time.time()
        except Exception as e:
            error_msg = f"延迟回复生成异常:\n {str(e)}"
            pxchat_logger.error(error_msg)
            clear_context(key)
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
    """
    delay = random.uniform(3, 5) if is_at else random.uniform(15, 20)

    if group_id in group_reply_timers and group_id in group_timer_user:
        if group_timer_user[group_id] == user_id:
            # 同一用户，重置计时器
            group_reply_timers[group_id].cancel()
            task = asyncio.create_task(_delayed_reply_check(group_id, key, is_at, delay))
            group_reply_timers[group_id] = task
            group_timer_is_at[group_id] = is_at
            pxchat_logger.info(f"[延迟] 群{group_id} 用户{user_id}重置{'(@)' if is_at else ''}等待{delay:.1f}s")
        # 不同用户，不重置计时器
    else:
        # 无活跃计时器，启动新计时器
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


def cancel_all_group_timers():
    """取消所有延迟回复计时器"""
    for group_id in list(group_reply_timers.keys()):
        group_reply_timers[group_id].cancel()
    group_reply_timers.clear()
    group_timer_user.clear()
    group_timer_is_at.clear()


async def send_delayed_group_reply(group_id: str, reply: str):
    """发送延迟回复到群聊（不@任何人）"""
    try:
        bot = get_bot()
    except ValueError:
        pxchat_logger.error("[延迟回复] 无法获取Bot实例")
        return

    segments = []
    try:
        data = json.loads(reply)
        if isinstance(data, dict) and "reply" in data and isinstance(data["reply"], list):
            segments = [seg for seg in data["reply"] if seg and seg.strip()]
    except (json.JSONDecodeError, TypeError):
        pxchat_logger.error("[延迟回复] 回复格式解析失败")
        return

    if not segments:
        return

    for i, segment in enumerate(segments):
        try:
            await bot.call_api("send_group_msg", group_id=int(group_id), message=segment)
            if i < len(segments) - 1:
                await asyncio.sleep(random.uniform(8, 15))
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
    分段发送消息，支持@回复
    """
    if not message:
        return

    segments = []

    try:
        data = json.loads(message)
        if isinstance(data, dict) and "reply" in data and isinstance(data["reply"], list):
            segments = [segment for segment in data["reply"] if segment and segment.strip()]
    except (json.JSONDecodeError, TypeError) as e:
        error_msg = f"处理聊天请求时发生异常:\n {str(e)}"
        await send_error_to_super_users(error_msg, event)
        return

    if not segments:
        return

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

@chat.handle()
async def _(bot: Bot, event: MessageEvent):
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
        user_info = f"用户{user_id}({event.sender.nickname if event.sender else '未知用户'})说："
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
        # 私聊：立即识别图片
        user_msg = await event_proc(event)
        add_message(key, "user", user_msg)

    # 调用聊天接口（仅私聊走到这里，群聊都走延迟回复）
    try:
        reply = await get_chat_reply_with_tools(get_context(key), is_group)
        add_message(key, "assistant", reply)
        await send_split_messages(chat, reply, event if is_group else None)

    except Exception as e:
        error_msg = f"处理聊天请求时发生异常:\n {str(e)}"
        clear_context(key)
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

class GroupProbabilityManager:
    """群聊智能参与管理器"""

    def __init__(self):
        self._shutting_down = False
        pxchat_logger.info(f"活跃度管理器初始化完成，全局基础活跃度: {chat_manager.get_group_chat_probability()}")

    async def _decay_task(self, group_id: str):
        """活跃度衰减任务：先等60秒保持boost，然后每300秒衰减0.1，最低保持基础概率的20%"""
        try:
            # 60秒boost期，保持2倍活跃度
            await asyncio.sleep(60)

            if self._shutting_down:
                # boost期结束，恢复基础概率
                base_prob = chat_manager.get_group_probability(group_id)
                group_probability_states[group_id] = round(base_prob, 2)
                if group_id in group_timers:
                    del group_timers[group_id]
                return

            # boost期结束，恢复基础概率，开始衰减
            base_prob = chat_manager.get_group_probability(group_id)
            min_prob = round(base_prob * 0.2, 2)
            group_probability_states[group_id] = round(base_prob, 2)
            pxchat_logger.info(f"群{group_id} boost结束，活跃度恢复: {round(base_prob, 2):.2f}")

            while not self._shutting_down:
                await asyncio.sleep(300)

                if self._shutting_down:
                    break

                current_prob = group_probability_states.get(group_id, 0.0)
                new_prob = max(min_prob, round(current_prob - 0.1, 2))

                group_probability_states[group_id] = new_prob
                pxchat_logger.info(f"群{group_id} 活跃度: {current_prob:.2f}→{new_prob:.2f}")

                if new_prob <= min_prob:
                    pxchat_logger.info(f"群{group_id} 活跃度下限{min_prob:.2f}")
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
        """续租活跃度，提升到基础概率的2倍（上限1.0），60秒后恢复"""
        if self._shutting_down:
            return False
        try:
            base_prob = chat_manager.get_group_probability(group_id)
            boosted_prob = min(1.0, round(base_prob * 2.0, 2))
            group_probability_states[group_id] = boosted_prob

            if group_id in group_timers:
                task = group_timers[group_id]
                if not task.done():
                    task.cancel()
                del group_timers[group_id]

            task = asyncio.create_task(self._decay_task(group_id))
            group_timers[group_id] = task

            pxchat_logger.info(f"群{group_id} 活跃度boost: {boosted_prob:.2f}")
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
