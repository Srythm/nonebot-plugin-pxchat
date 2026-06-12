"""
短期情绪/状态管理模块
跟踪每个群的机器人参与状态：连续回复数、精力值、话题兴趣度
让回复频率和风格更像"人"而不是每条消息独立抽样
"""
import json
import os
import re
import time
from typing import Any, Dict

import nonebot_plugin_localstore as store

from .log import logger as pxchat_logger

STATE_FILE = store.get_plugin_data_file("px_chat_state.json")

# 衰减参数
ENERGY_DECAY_PER_REPLY = 0.12       # 每次回复消耗精力
ENERGY_RECOVERY_PER_300S = 0.10     # 每300秒自然恢复
TOPIC_INTEREST_DECAY_PER_300S = 0.10  # 话题兴趣衰减
TOPIC_INTEREST_BOOST_ON_MATCH = 0.08  # 话题延续时兴趣提升
MIN_ENERGY = 0.10
MAX_ENERGY = 1.0
MIN_INTEREST = 0.05
MAX_INTEREST = 1.0

_state: Dict[str, Dict[str, Any]] = {}


def _default_state() -> Dict[str, Any]:
    return {
        "consecutive_replies": 0,
        "last_reply_time": 0,
        "last_message_time": 0,
        "energy": 0.8,
        "topic_interest": 0.5,
        "topic_keywords": [],
    }


def load_state():
    global _state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                _state = json.load(f)
            pxchat_logger.info(f"Bot状态加载: {len(_state)}个群")
        except Exception as e:
            pxchat_logger.error(f"加载Bot状态失败: {e}")
            _state = {}


def save_state():
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False, indent=2)


def _extract_topic_keywords(content: str) -> list[str]:
    """从消息内容提取话题关键词"""
    text = re.sub(r"用户\d+\([^)]+\)说?[：:]", "", content)
    text = re.sub(r"\[CQ:[^\]]+\]", " ", text)
    text = re.sub(r"你\(px\)[：:]\s*", "", text)
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", text)
    blocked = {
        "这个", "那个", "就是", "然后", "感觉", "可能",
        "什么", "怎么", "可以", "不是", "没有", "一下",
        "我觉得", "应该是", "不知道", "有没有", "是不是",
    }
    return [t for t in tokens if t not in blocked][:5]


def _auto_decay(state: dict):
    """根据时间流逝自动衰减/恢复状态"""
    now = time.time()
    elapsed = max(0, now - state.get("last_message_time", now))

    # 精力恢复
    recovery_cycles = elapsed / 300.0
    if recovery_cycles > 0:
        state["energy"] = round(
            min(MAX_ENERGY, state["energy"] + ENERGY_RECOVERY_PER_300S * recovery_cycles), 2
        )
        # 话题兴趣衰减
        state["topic_interest"] = round(
            max(MIN_INTEREST, state["topic_interest"] - TOPIC_INTEREST_DECAY_PER_300S * recovery_cycles), 2
        )
        # 连续回复超过300秒无新消息视为对话结束
        if elapsed > 300:
            state["consecutive_replies"] = 0


def get_state_hint(group_id: str) -> str:
    """获取当前状态的prompt提示文本"""
    key = str(group_id)
    if key not in _state:
        _state[key] = _default_state()

    state = _state[key]
    _auto_decay(state)

    hints = []

    consecutive = state.get("consecutive_replies", 0)
    if consecutive >= 5:
        hints.append("你已连续回复多轮，可以考虑自然淡出，除非有明确需要你参与的内容")
    elif consecutive >= 3:
        hints.append("你已连续参与几轮，保持简短回应即可，不用每条都接")

    energy = state.get("energy", 0.8)
    if energy < 0.25:
        hints.append("你现在状态比较疲惫，倾向于简短回复或跳过不重要的消息")
    elif energy < 0.5:
        hints.append("你精力一般，如果话题不那么重要可以不多说")

    interest = state.get("topic_interest", 0.5)
    if interest > 0.7:
        hints.append("你对当前话题比较感兴趣，可以积极参与讨论")
    elif interest < 0.2:
        hints.append("你对当前话题兴趣不大，可以等待更有趣的话题")

    if not hints:
        return ""

    return "\n【你当前的状态】\n" + "\n".join(f"- {h}" for h in hints)


def get_consecutive_replies(group_id: str) -> int:
    """获取连续回复轮数"""
    key = str(group_id)
    state = _state.get(key, _default_state())
    _auto_decay(state)
    return state.get("consecutive_replies", 0)


def record_reply(group_id: str):
    """机器人回复后更新状态"""
    key = str(group_id)
    if key not in _state:
        _state[key] = _default_state()

    state = _state[key]
    _auto_decay(state)

    state["consecutive_replies"] = state.get("consecutive_replies", 0) + 1
    state["last_reply_time"] = int(time.time())
    state["energy"] = round(max(MIN_ENERGY, state["energy"] - ENERGY_DECAY_PER_REPLY), 2)
    save_state()
    pxchat_logger.info(
        f"[状态] 群{group_id} 回复: 连续{state['consecutive_replies']}轮 "
        f"精力{state['energy']:.2f} 兴趣{state.get('topic_interest', 0.5):.2f}"
    )


def record_group_message(group_id: str, content: str):
    """群聊有新消息时更新话题追踪"""
    key = str(group_id)
    if key not in _state:
        _state[key] = _default_state()

    state = _state[key]
    _auto_decay(state)

    state["last_message_time"] = int(time.time())

    # 提取关键词并判断话题延续性
    new_keywords = _extract_topic_keywords(content)
    old_keywords = state.get("topic_keywords", [])
    overlap = len(set(new_keywords) & set(old_keywords))

    if overlap >= 2:
        # 话题延续，提升兴趣
        state["topic_interest"] = round(
            min(MAX_INTEREST, state["topic_interest"] + TOPIC_INTEREST_BOOST_ON_MATCH * overlap), 2
        )
    elif overlap == 0 and new_keywords:
        # 话题切换，兴趣有个基础值
        state["topic_interest"] = round(max(0.3, state["topic_interest"] - 0.3), 2)

    state["topic_keywords"] = new_keywords
    save_state()


def skip_reply(group_id: str):
    """机器人本轮不回复时：降低连续回复计数（对话自然中断）"""
    key = str(group_id)
    if key not in _state:
        _state[key] = _default_state()

    state = _state[key]
    _auto_decay(state)

    # 不回复意味着对话可能已自然结束，降低连续计数
    if state.get("consecutive_replies", 0) > 0:
        state["consecutive_replies"] = max(0, state["consecutive_replies"] - 1)
        pxchat_logger.info(
            f"[状态] 群{group_id} 跳过: 连续降为{state['consecutive_replies']}轮"
        )
    save_state()


def clear_state(group_id: str | None = None):
    """清除状态"""
    if group_id:
        _state.pop(str(group_id), None)
    else:
        _state.clear()
    save_state()
