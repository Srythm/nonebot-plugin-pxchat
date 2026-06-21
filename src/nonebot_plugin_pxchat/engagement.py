"""
群聊智能参与度管理器
- boost/衰减机制：回复后短期提升参与度，随沉默衰减
- 突发检测：短时间内大量消息自动重置参与度
"""
import asyncio
import time
from typing import Dict

from .manager import chat_manager
from .log import logger as pxchat_logger

# 参与度状态 {group_id: probability}
probability_states: Dict[str, float] = {}
# 衰减任务 {group_id: asyncio.Task}
decay_timers: Dict[str, asyncio.Task] = {}
# 突发检测 {group_id: [timestamp, ...]}
_burst_times: Dict[str, list[float]] = {}
_BURST_WINDOW = 30     # 检测窗口（秒）
_BURST_THRESHOLD = 10  # 触发阈值（条数）


class GroupEngagementManager:
    """群聊智能参与管理器"""

    def __init__(self):
        self._shutting_down = False
        pxchat_logger.info(f"参与度管理器初始化完成，全局基础参与度: {chat_manager.get_group_chat_probability()}")

    def record_message_and_check_burst(self, group_id: str):
        """记录消息时间戳，短时间大量消息时重置参与度到基础值"""
        now = time.time()
        times = _burst_times.setdefault(group_id, [])
        times.append(now)
        cutoff = now - _BURST_WINDOW
        _burst_times[group_id] = [t for t in times if t > cutoff]
        recent = len(_burst_times[group_id])

        if recent >= _BURST_THRESHOLD:
            base_prob = chat_manager.get_group_probability(group_id)
            current = probability_states.get(group_id, base_prob)
            if current < base_prob:
                probability_states[group_id] = base_prob
                if group_id in decay_timers:
                    task = decay_timers[group_id]
                    if not task.done():
                        task.cancel()
                    del decay_timers[group_id]
                pxchat_logger.info(
                    f"[突发] 群{group_id} {_BURST_WINDOW}s内{recent}条消息，参与度 {current:.2f}→{base_prob:.2f}"
                )

    async def _decay_task(self, group_id: str):
        """参与度衰减：先等30秒保持boost，然后每60秒衰减0.1，最低20%"""
        try:
            await asyncio.sleep(30)
            if self._shutting_down:
                base_prob = chat_manager.get_group_probability(group_id)
                probability_states[group_id] = round(base_prob, 2)
                if group_id in decay_timers:
                    del decay_timers[group_id]
                return

            base_prob = chat_manager.get_group_probability(group_id)
            min_prob = round(base_prob * 0.2, 2)
            probability_states[group_id] = round(base_prob, 2)
            pxchat_logger.info(f"群{group_id} boost结束，参与度恢复: {round(base_prob, 2):.2f}")

            while not self._shutting_down:
                await asyncio.sleep(60)
                if self._shutting_down:
                    break
                current = probability_states.get(group_id, 0.0)
                new = max(min_prob, round(current - 0.1, 2))
                probability_states[group_id] = new
                pxchat_logger.info(f"群{group_id} 参与度衰减: {current:.2f}→{new:.2f}")
                if new <= min_prob:
                    pxchat_logger.info(f"群{group_id} 参与度已达下限{min_prob:.2f}")
                    if group_id in decay_timers:
                        del decay_timers[group_id]
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            pxchat_logger.error(f"群{group_id} 衰减异常: {e}")
            if group_id in decay_timers:
                del decay_timers[group_id]
            if group_id in probability_states:
                del probability_states[group_id]

    def renew(self, group_id: str) -> bool:
        """续租参与度，提升到基础值的1.2倍（上限0.80），30秒后恢复"""
        if self._shutting_down:
            return False
        try:
            base_prob = chat_manager.get_group_probability(group_id)
            boosted_prob = min(0.80, round(base_prob * 1.2, 2))
            probability_states[group_id] = boosted_prob
            if group_id in decay_timers:
                task = decay_timers[group_id]
                if not task.done():
                    task.cancel()
                del decay_timers[group_id]
            task = asyncio.create_task(self._decay_task(group_id))
            decay_timers[group_id] = task
            pxchat_logger.info(f"群{group_id} 参与度boost: {boosted_prob:.2f}")
            return True
        except Exception as e:
            pxchat_logger.error(f"群{group_id} 续租失败: {e}")
            return False

    def get_probability(self, group_id: str) -> float:
        """获取参与度，无记录时返回该群的基础值"""
        prob = probability_states.get(group_id, None)
        if prob is None:
            return chat_manager.get_group_probability(group_id)
        return prob

    def has_active_timer(self, group_id: str) -> bool:
        return group_id in decay_timers and not decay_timers[group_id].done()

    async def shutdown(self):
        self._shutting_down = True
        pxchat_logger.info("开始关闭参与度管理器...")
        for group_id, task in list(decay_timers.items()):
            if not task.done():
                task.cancel()
        decay_timers.clear()
        probability_states.clear()
        _burst_times.clear()
        pxchat_logger.info("参与度管理器关闭完成")
