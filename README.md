<div align="center">
    <a href="https://v2.nonebot.dev/store">
    <img src="https://raw.githubusercontent.com/fllesser/nonebot-plugin-template/refs/heads/resource/.docs/NoneBotPlugin.svg" width="310" alt="logo"></a>

## ✨ nonebot-plugin-pxchat ✨
[![python](https://img.shields.io/badge/python-3.10|3.11|3.12|3.13-blue.svg)](https://www.python.org)
[![uv](https://img.shields.io/badge/package%20manager-uv-black?style=flat-square&logo=uv)](https://github.com/astral-sh/uv)
</div>

## 📖 介绍

基于AI大模型的聊天插件，支持大模型任意切换、上下文记忆、群聊智能参与、图片识别、MCP等功能

安装插件后，请先配置超级用户信息，然后使用`px about`命令获取插件信息，使用指令配置相关配置

### ✨ 核心特性

- **多模型切换** - 支持配置多个AI模型（兼容OpenAI API），聊天和图片识别可分别指定模型
- **上下文记忆** - 自动维护对话上下文（最近20条），私聊和群聊独立上下文
- **群聊智能参与** - AI 自主判断是否参与群聊，置信度驱动 + 动态参与度门槛
- **短期状态系统** - 追踪连续回复轮数、精力值、话题兴趣度，模拟真人情绪波动
- **群成员记忆** - 记录每群每用户的发言统计、关键词、互动摘要，回复时注入记忆
- **延迟回复** - 群聊非@消息延迟15-20s判断，被@时3-5s快速回复，延迟值复用不重新随机
- **打字节奏** - 模型自主选择 fast(3-6s)/normal(8-15s)/slow(15-25s) 分段间隔
- **思考模式** - 支持AI思考模式（reasoning），群聊合并判断+回复节省Token
- **图片识别** - 多模态模型识别图片内容，群聊延迟识别、私聊即时识别
- **MCP工具调用** - 支持SSE/stdio传输方式的MCP服务器，工具调用与回复合并为一请求
- **联网搜索** - 可启用AI模型的联网搜索能力
- **自动禁言** - 模型判断违规行为 → 检测Bot管理员权限 → 自动禁言（支持冷却和时长配置）
- **突发检测** - 30s内≥10条消息自动重置参与度，群聊突然活跃时快速跟进
- **消息感知** - 识别@提及、回复引用、结构化卡片（json/分享/小程序等）
- **人设配置** - 自定义AI角色人设，始终保持角色不脱戏
- **分段发送** - 回复自动分段发送，模拟真实网友聊天习惯

## 💿 安装

<details open>
<summary>[推荐] 使用 nb-cli 安装</summary>
在 Bot 的根目录下打开命令行, 输入以下指令即可安装

```shell
nb plugin install nonebot-plugin-pxchat
```

</details>
<details>
<summary>使用包管理器安装</summary>
在 nonebot2 项目的插件目录下, 打开命令行, 根据你使用的包管理器, 输入相应的安装命令

```shell
pip install nonebot-plugin-pxchat
# or, use uv
uv add nonebot-plugin-pxchat
```

打开 nonebot2 项目根目录下的 `pyproject.toml` 文件, 在 `[tool.nonebot]` 部分追加写入

```toml
plugins = ["nonebot_plugin_pxchat"]
```
</details>



## ⚙️ 配置

项目启动会加配置文件，除了超级用户配置和mcp服务器配置需要手动配置外，其余配置均可使用聊天命令配置

配置超级用户，启动后使用`px about`命令获取插件信息，支持使用指令配置相关配置

在 nonebot2 项目的`.env`文件中添加下表中的必填配置

| 配置项  | 必填  | 默认值 |   说明   |
| :-----: | :---: | :----: | :------: |
| pxchat_super_users |  是   |   无   | 超级用户列表 eg:["你的QQ号"] |
| pxchat_mcp |  否   |   无   | mcp服务配置 |


配置示例
```shell
pxchat_super_users=["123456"]

pxchat_mcp='{
 "web_parser": {
        "url": "https://dashscope.aliyuncs.com/api/v1/mcps/WebParser/sse",
        "headers": {
            "Authorization": "Bearer your-api-key"
        },
        "enabled": false
    },
    "web_search": {
        "url": "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse",
        "headers": {
            "Authorization": "Bearer your-api-key"
        },
        "enabled": true
    }

}'

```



维护配置结构大致如下（不需要配置，按照`px about`命令指导操作）:
```json
{
  "super_users": [
    "你的QQ号"
  ], // 超级用户列表配置
  "enabled_groups": [
    "QQ群号"
  ], // 启用QQ群
  "group_chat_probability": 1, // 群聊活跃度基础值
  "group_probabilities": {
    "QQ群号": 0.5
  }, // 每群独立活跃度配置（可选）
  "chat_enabled": true, // 是否开启聊天
  "enable_search": false, // 是否开启搜索
  "image_recognition_enabled": true, // 是否开启图片识别
  "mcp_enabled": true, // 是否开启mcp功能
  "mcp_servers": {
    "web_search": {
      "type": "sse",
      "url": "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse",
      "headers": {
        "Authorization": "Bearer your-api-key"
      },
      "enabled": true
    },
    "web_parser": {
      "type": "sse",
      "url": "https://dashscope.aliyuncs.com/api/v1/mcps/WebParser/sse",
      "headers": {
        "Authorization": "Bearer your-api-key"
      },
      "enabled": false
    }
  },
  "personality": "你叫px，是被困在服务器中的ai程序。在聊天中回答问题要保持简洁直接。情绪随心情波动，回答长短看情况。任何问题都只给关键信息，不啰嗦", // 默认人设
  "ai_configs": [
    {
      "name": "ds-chat",
      "api_key": "{your-api-key}",
      "api_url": "https://api.deepseek.com",
      "model": "deepseek-chat",
      "thinking": false
    }
  ],
  "current_ai_config": 0, // 对话模型索引
  "current_image_recognition_config": 0, // 识图模型索引

  // 自动禁言配置
  "auto_mute_enabled": false,   // 自动禁言开关
  "auto_mute_min_duration": 60,  // 最短禁言秒数
  "auto_mute_max_duration": 600, // 最长禁言秒数
  "auto_mute_cooldown": 300,    // 群内禁言冷却秒数
  "auto_mute_admin_groups": {}  // 手动指定Bot为管理员的群
}
```

## 🎉 使用
### 指令表
```
📋 系统状态
• px status - 查看完整状态
• px activity - 群活跃度和延迟计时器

👥 群组管理
• px group - 查看已启用群组
• px group add <群号> - 启用群组
• px group del <群号> - 禁用群组
• px group prob <群号> - 查看群独立参与度
• px group prob <群号> set <0.0-1.0> - 设置群独立参与度
• px group prob <群号> reset - 恢复使用全局参与度

🔧 AI配置管理
• px ai - 查看AI配置
• px ai add <名称> <key> <url> <模型> [thinking] - 添加配置（可选开启思考模式）
• px ai del <名称> - 删除配置
• px ai switch <名称> - 切换聊天配置
• px image switch <名称> - 切换图片识别配置

⚙️ 功能开关
• px chat on/off - 聊天功能
• px search on/off - 搜索功能  
• px image on/off - 图片识别
• px mcp on/off - MCP功能
• px mcp server <服务器名> on/off - 开关单个MCP服务器
• px mcp refresh - 刷新MCP工具缓存
• px mcp tools - 查看可用MCP工具

🔇 自动禁言
• px mute - 查看禁言状态
• px mute on/off - 开关自动禁言
• px mute duration <最小秒> <最大秒> - 设置禁言时长范围
• px mute cooldown <秒> - 设置群冷却时间
• px mute check - 检测当前群 Bot 管理员权限

🎭 人设配置
• px personality - 查看人设
• px personality set <内容>

📊 群参与度设置
• px prob - 查看全局参与度
• px prob set <0.0-1.0> - 设置全局参与度

💡 延迟回复机制
• 群聊非@消息会在用户停止发送15-20秒后判断是否回复
• 被@时3-5秒快速回复
• 任何新消息都会重置计时器，但保留初始延迟值不重新随机
• 8秒安静窗口：窗口内有新消息则续等
```

### 🧠 思考模式

添加AI配置时可开启思考模式（第6个参数传`1`），开启后群聊会将「是否回复判断」和「生成回复」合并为一次API调用，节省Token消耗：

```
px ai add my_model sk-xxx https://api.example.com gpt-4 1
```

### 📈 智能参与机制

**置信度驱动**：模型的 `should_reply` 和 `confidence` 共同决定是否回复。模型说"不回"→直接拒绝；模型说"回"+ 置信度达标→回复。动态门槛公式：`threshold = max(0.40, 1.0 - 参与度 × 0.6)`。参与度越高门槛越低（越容易开口），参与度越低门槛越高（越谨慎）。

**参与度 boost/衰减**：
- 被@或触发回复时，提升至基础值的2倍（上限1.0）
- 60秒boost期后恢复基础值，之后每300秒衰减0.1
- 衰减下限为基础值的20%

**突发检测**：30秒内收到≥10条消息时，参与度立刻重置到基础值。群突然热闹时不因衰减错过参与时机。

### 🎭 短期状态系统

每群独立追踪机器人的"情绪"状态：
- **连续回复轮数**：≥3轮提示简短，≥5轮提示淡出
- **精力值**：每次回复消耗0.12，每300秒恢复0.10，低精力时倾向跳过
- **话题兴趣度**：话题延续时提升，切换时重置，影响参与意愿

### 👤 群成员记忆

自动记录每群每用户的发言统计、高频关键词、最近消息、互动次数和摘要。回复判断时优先注入近期互动过的用户记忆，让对话更有"认识你"的真实感。

### 🔇 自动禁言

当 Bot 拥有群管理员权限时，模型可在判断过程中建议禁言违规用户（刷屏/辱骂/广告）。系统自动检测权限、执行禁言、控制冷却（默认300秒）和时长范围（默认60~600秒）。支持 `px mute check` 实时检测权限状态。

### ⚡ Token 优化

- 所有 Prompt 文本已压缩约45%（去除冗余编号和重复表述）
- 判断上下文从14条缩减到12条
- 记忆提示从6人缩减到4人，输出格式精简
- 非思考模型判断后回复时跳过重复的人设指令
- 工具调用与回复生成合并为一请求，无工具时不额外消耗

## 🎨 效果图
### 群聊参与
![](img/群聊参与.png)
### 图片/表情包识别
![](img/识图.png)
### 借助MCP联网
![](img/MCP工具联网.png)
### 模型切换
![](img/大模型配置切换.png)
### 群活跃度状态
![](img/群活跃状态.png)


## 📋 相关设计
![](img/主流程.png)