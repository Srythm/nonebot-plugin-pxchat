from openai import AsyncOpenAI
from .manager import chat_manager
from .log import logger as pxchat_logger
import asyncio
import json

import base64
import httpx
import traceback

async def recognize_image(
    image_url: str,
    prompt: str = "请简洁描述这张图片的内容"
) -> str:
    """
    使用多模态模型识别图片内容（从URL下载并识别）

    :param image_url: 图片URL
    :param prompt: 识别提示词
    :return: 识别结果文本
    """

    ai_config = chat_manager.get_current_image_recognition_config()

    if not ai_config:
        raise Exception(
            "未配置图片识别服务，请使用 'px image ai add' 命令添加配置"
        )

    try:
        pxchat_logger.info(f"图片识别: {image_url[:50]}...")

        async with httpx.AsyncClient(
            timeout=60,
            follow_redirects=True
        ) as session:
            response = await session.get(image_url)
            response.raise_for_status()
            image_bytes = response.content

        if not image_bytes:
            raise Exception("图片下载成功但内容为空")

        return await _do_recognize(image_bytes, prompt)

    except Exception as e:
        pxchat_logger.error(f"图片识别异常: {e}")
        raise Exception(f"图片识别出现异常: {e}")


async def recognize_image_from_cache(
    image_bytes: bytes,
    prompt: str = "请简洁描述这张图片的内容"
) -> str:
    """
    使用多模态模型识别图片内容（从缓存的bytes识别，无需再次下载）

    :param image_bytes: 图片字节数据
    :param prompt: 识别提示词
    :return: 识别结果文本
    """

    ai_config = chat_manager.get_current_image_recognition_config()

    if not ai_config:
        raise Exception(
            "未配置图片识别服务，请使用 'px image ai add' 命令添加配置"
        )

    try:
        pxchat_logger.info(f"缓存图片识别: {len(image_bytes)/1024:.0f}KB")
        return await _do_recognize(image_bytes, prompt)

    except Exception as e:
        pxchat_logger.error(f"缓存图片识别异常: {e}")
        raise Exception(f"缓存图片识别出现异常: {e}")


async def _do_recognize(
    image_bytes: bytes,
    prompt: str = "请简洁描述这张图片的内容"
) -> str:
    """
    通用图片识别逻辑（从bytes识别）

    :param image_bytes: 图片字节数据
    :param prompt: 识别提示词
    :return: 识别结果文本
    """

    ai_config = chat_manager.get_current_image_recognition_config()

    # 转Base64
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

    # 动态创建客户端
    client = AsyncOpenAI(
        api_key=ai_config.get("api_key", ""),
        base_url=ai_config.get("api_url", ""),
    )

    completion = await client.chat.completions.create(
        model=ai_config.get("model", ""),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (
                                f"data:image/jpeg;base64,"
                                f"{image_base64}"
                            )
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ],
        max_tokens=1000
    )

    result = completion.choices[0].message.content

    if not result:
        raise Exception("图片识别返回了空结果")

    return result
