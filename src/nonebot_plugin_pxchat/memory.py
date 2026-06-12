import json
import os
import re
import time
from collections import Counter
from typing import Any, Dict, List

import nonebot_plugin_localstore as store

from .log import logger as pxchat_logger

MEMORY_FILE = store.get_plugin_data_file("px_chat_memory.json")
MAX_RECENT_MESSAGES = 5
MAX_KEYWORDS = 12
MAX_MESSAGE_AGE = 6 * 3600  # 保留6小时内的消息

_memories: Dict[str, Dict[str, Any]] = {}


def load_memories():
    global _memories
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                _memories = json.load(f)
            pxchat_logger.info(f"群记忆加载: {len(_memories)}个")
        except Exception as e:
            pxchat_logger.error(f"加载群记忆失败: {e}")
            _memories = {}


def save_memories():
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(_memories, f, ensure_ascii=False, indent=2)


def _extract_keywords(content: str) -> List[str]:
    text = re.sub(r"\[CQ:[^\]]+\]", " ", content)
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_+#.-]{3,}", text)
    blocked = {
        "这个",
        "那个",
        "就是",
        "然后",
        "感觉",
        "可能",
        "什么",
        "怎么",
        "可以",
        "不是",
        "没有",
        "一下",
    }
    return [token[:20] for token in tokens if token not in blocked][:8]


def record_group_user_message(group_id: str, user_id: str, nickname: str, content: str):
    group_key = str(group_id)
    user_key = str(user_id)
    now = int(time.time())

    group_memory = _memories.setdefault(group_key, {"users": {}, "updated_at": now})
    users = group_memory.setdefault("users", {})
    user_memory = users.setdefault(
        user_key,
        {
            "nickname": nickname,
            "message_count": 0,
            "interaction_count": 0,
            "last_seen": 0,
            "last_interaction_time": 0,
            "last_interaction_summary": "",
            "recent_messages": [],
            "timed_messages": [],  # [{"t": timestamp, "m": "内容"}, ...] 6小时窗口
            "keywords": {},
        },
    )

    user_memory["nickname"] = nickname or user_memory.get("nickname") or "未知用户"
    user_memory["message_count"] = int(user_memory.get("message_count", 0)) + 1
    user_memory["last_seen"] = now

    recent = user_memory.setdefault("recent_messages", [])
    clean_content = content.strip()
    if clean_content:
        recent.append(clean_content[:120])
        user_memory["recent_messages"] = recent[-MAX_RECENT_MESSAGES:]

    # 带时间戳的消息记录（6小时窗口）
    timed = user_memory.setdefault("timed_messages", [])
    if clean_content:
        timed.append({"t": now, "m": clean_content[:120]})
        # 清理超过6小时的旧记录
        cutoff = now - MAX_MESSAGE_AGE
        user_memory["timed_messages"] = [e for e in timed if e.get("t", 0) > cutoff]

    keyword_counts = Counter(user_memory.get("keywords", {}))
    keyword_counts.update(_extract_keywords(clean_content))
    user_memory["keywords"] = dict(keyword_counts.most_common(MAX_KEYWORDS))

    group_memory["updated_at"] = now
    save_memories()


def record_interaction(group_id: str, user_id: str, summary: str = ""):
    """记录一次有效互动（机器人回复了该用户或与之交互）"""
    group_key = str(group_id)
    user_key = str(user_id)
    now = int(time.time())

    group_memory = _memories.setdefault(group_key, {"users": {}, "updated_at": now})
    users = group_memory.setdefault("users", {})
    user_memory = users.setdefault(
        user_key,
        {
            "nickname": "未知用户",
            "message_count": 0,
            "interaction_count": 0,
            "last_seen": now,
            "last_interaction_time": 0,
            "last_interaction_summary": "",
            "recent_messages": [],
            "timed_messages": [],
            "keywords": {},
        },
    )

    user_memory["interaction_count"] = int(user_memory.get("interaction_count", 0)) + 1
    user_memory["last_interaction_time"] = now
    if summary:
        user_memory["last_interaction_summary"] = summary[:200]
    save_memories()


def get_group_memory_hint(group_id: str, user_ids: List[str] | None = None, limit: int = 4) -> str:
    group_memory = _memories.get(str(group_id), {})
    users = group_memory.get("users", {})
    if not users:
        return ""

    selected_items = []
    # 优先选取最近互动过的用户
    if user_ids:
        seen = set()
        for user_id in user_ids:
            user_id = str(user_id)
            if user_id in users and user_id not in seen:
                selected_items.append((user_id, users[user_id]))
                seen.add(user_id)

    if len(selected_items) < limit:
        # 按互动时间排序：优先最近互动过的，其次最近发言的
        recent_items = sorted(
            users.items(),
            key=lambda item: (
                item[1].get("last_interaction_time", 0) or 0,
                item[1].get("last_seen", 0),
            ),
            reverse=True,
        )
        for user_id, user_memory in recent_items:
            if len(selected_items) >= limit:
                break
            if any(existing_id == user_id for existing_id, _ in selected_items):
                continue
            selected_items.append((user_id, user_memory))

    lines = []
    for user_id, user_memory in selected_items[:limit]:
        nickname = user_memory.get("nickname", "未知用户")
        msg_count = user_memory.get("message_count", 0)
        interaction_count = user_memory.get("interaction_count", 0)
        keywords = list(user_memory.get("keywords", {}).keys())[:2]
        interaction_summary = user_memory.get("last_interaction_summary", "")

        # 最近消息：优先从timed_messages取6h内的，fallback到recent_messages
        recent_msgs = []
        timed = user_memory.get("timed_messages", [])
        if timed:
            recent_msgs = [e["m"] for e in timed[-3:]]  # 最近3条
        if not recent_msgs:
            recent_msgs = user_memory.get("recent_messages", [])[-1:]
        recent_text = " | ".join(m[:30] for m in recent_msgs) if recent_msgs else ""

        parts = [f"用户{user_id}({nickname})"]
        if interaction_count > 0:
            parts.append(f"互动{interaction_count}次/发言{msg_count}")
        else:
            parts.append(f"发言{msg_count}次")
        if keywords:
            parts.append("|".join(keywords))
        if recent_text:
            parts.append(recent_text)
        if interaction_summary:
            parts.append(interaction_summary[:50])
        lines.append("- " + " ".join(parts))

    return "\n".join(lines)


def clear_group_memory(group_id: str):
    if str(group_id) in _memories:
        del _memories[str(group_id)]
        save_memories()


def prune_old_messages():
    """清理所有群中超过6小时的timed_messages"""
    now = int(time.time())
    cutoff = now - MAX_MESSAGE_AGE
    cleaned = 0
    for group_memory in _memories.values():
        for user_memory in group_memory.get("users", {}).values():
            old_len = len(user_memory.get("timed_messages", []))
            user_memory["timed_messages"] = [
                e for e in user_memory.get("timed_messages", [])
                if e.get("t", 0) > cutoff
            ]
            cleaned += old_len - len(user_memory["timed_messages"])
    if cleaned:
        pxchat_logger.info(f"记忆清理: 移除{cleaned}条过期消息")
        save_memories()
