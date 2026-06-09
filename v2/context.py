import json
import os
from typing import List, Dict
import nonebot_plugin_localstore as store
from .log import logger as pxchat_logger

CONTEXT_FILE = store.get_plugin_data_file("px_chat_context.json")
MAX_CONTEXT_LENGTH = 20  # 每个对话最大消息数

# { "user_id_or_group_id": [{"role": "user|assistant|system", "content": "...", "msg_id": "..."}] }
_contexts: Dict[str, List[Dict[str, str]]] = {}

# 记录每个群已经判断过的消息ID，避免重复判断
# { "group_xxx": set(msg_id_1, msg_id_2, ...) }
_judged_msg_ids: Dict[str, set] = {}

def load_contexts():
    global _contexts
    if os.path.exists(CONTEXT_FILE):
        try:
            with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
                _contexts = json.load(f)
            pxchat_logger.info(f"上下文加载成功，共 {len(_contexts)} 个对话")
        except Exception as e:
            pxchat_logger.error(f"加载上下文失败: {e}")
            _contexts = {}

def save_contexts():
    with open(CONTEXT_FILE, "w", encoding="utf-8") as f:
        json.dump(_contexts, f, ensure_ascii=False, indent=2)

def get_context(key: str) -> List[Dict[str, str]]:
    return _contexts.get(key, [])

def add_message(key: str, role: str, content: str, msg_id: str = None):
    """添加消息到上下文，可附带消息ID用于去重判断"""
    context = _contexts.get(key, [])
    msg = {"role": role, "content": content}
    if msg_id:
        msg["msg_id"] = msg_id
    context.append(msg)
    if len(context) > MAX_CONTEXT_LENGTH:
        context = context[-MAX_CONTEXT_LENGTH:]
    _contexts[key] = context
    save_contexts()

def clear_context(key: str):
    if key in _contexts:
        del _contexts[key]
        save_contexts()
    # 同时清理该key的已判断记录
    if key in _judged_msg_ids:
        del _judged_msg_ids[key]

def get_unjudged_messages(key: str) -> List[Dict[str, str]]:
    """获取该key下尚未被判断过的消息列表"""
    context = _contexts.get(key, [])
    judged = _judged_msg_ids.get(key, set())
    return [msg for msg in context if msg.get("msg_id") not in judged]

def mark_messages_judged(key: str, msg_ids: list):
    """将指定消息ID标记为已判断"""
    if key not in _judged_msg_ids:
        _judged_msg_ids[key] = set()
    _judged_msg_ids[key].update(msg_ids)
    # 清理已不在上下文中的msg_id，防止内存泄漏
    context = _contexts.get(key, [])
    current_ids = {msg.get("msg_id") for msg in context if msg.get("msg_id")}
    _judged_msg_ids[key] = _judged_msg_ids[key] & current_ids

def has_unjudged_messages(key: str) -> bool:
    """检查是否有未判断过的消息"""
    return len(get_unjudged_messages(key)) > 0

def add_user_message_to_group(group_id: str, user_id: str, nickname: str, content: str, msg_id: str = None):
    """
    专门用于群聊环境添加用户消息
    """
    key = f"group_{group_id}"
    user_info = f"用户{user_id}({nickname})"
    user_message = f"{user_info}: {content}"
    add_message(key, "user", user_message, msg_id)
