# nonebot-plugin-pxchat

基于 AI 的 NoneBot 聊天插件，支持大模型任意切换、上下文记忆、群聊智能参与、图片识别、MCP 工具调用等功能。

## 功能特性

- **多模型切换** - 支持配置多个 AI 模型（兼容 OpenAI API），可随时切换聊天/图片识别使用的模型
- **上下文记忆** - 自动维护对话上下文（最近 20 条），支持私聊和群聊独立上下文
- **群聊智能参与** - AI 自动判断是否参与群聊讨论，支持活跃度衰减与 boost 机制
- **延迟回复机制** - 群聊消息延迟 15-30 秒后判断回复，模拟真人打字节奏；被 @ 时 3-5 秒快速回复
- **图片识别** - 支持多模态模型识别图片内容，群聊中延迟识别、私聊中即时识别
- **MCP 工具调用** - 支持 SSE/stdio 两种传输方式的 MCP 服务器，AI 可自主调用外部工具
- **思考模式** - 支持开启 AI 思考模式（reasoning），群聊中可合并判断+回复节省 Token
- **搜索功能** - 可启用 AI 模型的联网搜索能力
- **人设配置** - 自定义 AI 角色人设，始终保持角色不脱戏
- **分段发送** - 回复自动分段发送，模拟真实网友聊天习惯
- **管理员系统** - 支持多管理员，错误信息自动推送给管理员
- **独立日志** - 插件专用日志系统，24 小时自动轮转清理

## 安装

```bash
nb plugin install nonebot-plugin-pxchat
```

或手动安装：

```bash
pip install nonebot-plugin-pxchat
```

然后在 NoneBot 的 `.env` 文件中添加插件加载：

```
PLUGINS=nonebot_plugin_pxchat
```

## 依赖

- [nonebot2](https://github.com/nonebot/nonebot2)
- [nonebot-adapter-onebot](https://github.com/nonebot/adapter-onebot) (v11)
- [nonebot-plugin-localstore](https://github.com/nonebot/plugin-localstore)
- [openai](https://github.com/openai/openai-python)
- [mcp](https://github.com/modelcontextprotocol/python-sdk)
- [httpx](https://github.com/encode/httpx)

## 配置

在 NoneBot 的 `.env` 配置文件中添加以下配置项：

### 必填配置

```env
# 超级用户（管理员）QQ 号列表
pxchat_super_users=["123456789"]
```

### MCP 配置（可选）

```env
# MCP 服务器配置，支持 SSE 和 stdio 两种传输方式
pxchat_mcp={"server_name":{"type":"sse","url":"http://localhost:8080/sse","enabled":true}}
```

MCP 服务器配置示例：

**SSE 方式：**
```json
{
  "my_sse_server": {
    "type": "sse",
    "url": "http://localhost:8080/sse",
    "headers": {},
    "enabled": true
  }
}
```

**stdio 方式：**
```json
{
  "my_stdio_server": {
    "type": "stdio",
    "command": "python",
    "args": ["server.py"],
    "env": {},
    "enabled": true
  }
}
```

## 使用方法

### 基本使用

- **私聊**：直接发送消息即可与 AI 对话
- **群聊**：@机器人 或等待 AI 自动判断是否参与讨论
- **清除对话**：发送 `清除对话` 或 `重置对话` 清除当前上下文

### 管理命令

所有管理命令需要 @机器人 发送，且仅管理员可用。

#### 系统状态

| 命令 | 说明 |
|------|------|
| `px status` | 查看系统完整状态 |
| `px activity` | 查看群活跃度和延迟计时器状态 |

#### 群组管理

| 命令 | 说明 |
|------|------|
| `px group` | 查看已启用群组 |
| `px group add <群号>` | 启用群组 |
| `px group del <群号>` | 禁用群组 |
| `px group prob <群号>` | 查看群独立活跃度概率 |
| `px group prob <群号> set <0.0-1.0>` | 设置群独立概率 |
| `px group prob <群号> reset` | 恢复使用全局概率 |

#### AI 配置管理

| 命令 | 说明 |
|------|------|
| `px ai` | 查看所有 AI 配置 |
| `px ai add <名称> <key> <url> <模型> [thinking]` | 添加 AI 配置（可选开启思考模式） |
| `px ai del <名称>` | 删除 AI 配置 |
| `px ai switch <名称>` | 切换聊天使用的 AI 配置 |

#### 功能开关

| 命令 | 说明 |
|------|------|
| `px chat on/off` | 聊天功能总开关 |
| `px search on/off` | 搜索功能开关 |
| `px image on/off` | 图片识别功能开关 |
| `px image switch <名称>` | 切换图片识别使用的 AI 配置 |
| `px mcp on/off` | MCP 功能总开关 |
| `px mcp server <服务器名> on/off` | 开关单个 MCP 服务器 |
| `px mcp refresh` | 刷新 MCP 工具缓存 |
| `px mcp tools` | 查看可用 MCP 工具列表 |

#### 人设配置

| 命令 | 说明 |
|------|------|
| `px personality` | 查看当前人设 |
| `px personality set <内容>` | 设置新人设 |

#### 活跃度概率

| 命令 | 说明 |
|------|------|
| `px prob` | 查看全局群聊触发概率 |
| `px prob set <0.0-1.0>` | 设置全局群聊触发概率 |

## 群聊机制说明

### 延迟回复

群聊消息不会立即回复，而是采用延迟机制模拟真人行为：

- **被 @ 时**：等待 3-5 秒后回复
- **非 @ 消息**：同一用户连续发送消息时，计时器会在每次收到新消息后重置；用户停止发送 15-20 秒后触发判断
- **回复冷却**：两次回复之间至少间隔 30 秒

### 活跃度系统

- 被 @ 或触发回复时，活跃度提升至基础值的 2 倍（上限 1.0）
- 60 秒 boost 期后恢复基础值，之后每 300 秒衰减 0.1
- 衰减下限为基础概率的 20%
- 支持为每个群设置独立的活跃度概率

### 思考模式

添加 AI 配置时可开启思考模式（传入第 6 个参数 `1`）：

```
px ai add my_model sk-xxx https://api.example.com gpt-4 1
```

思考模式下群聊会将「是否回复判断」和「生成回复」合并为一次 API 调用，节省 Token 消耗。

## 项目结构

```
nonebot_plugin_pxchat/
├── v3/                     # v3 版本（当前版本）
│   ├── __init__.py         # 插件入口、消息处理、延迟回复、活跃度管理
│   ├── chat.py             # AI 对话、工具调用、群聊判断
│   ├── commands.py         # 管理命令处理
│   ├── config.py           # 插件配置定义
│   ├── context.py          # 上下文管理（消息记录、已判断标记）
│   ├── image2txt.py        # 图片识别（多模态模型）
│   ├── log.py              # 日志系统
│   ├── manager.py          # 配置管理器（群组、AI、MCP、人设等）
│   ├── mcp_manager.py      # MCP 客户端（SSE/stdio 连接、工具调用）
│   └── send2root.py        # 消息发送（合并转发、错误推送）
├── v2/                     # v2 版本（旧版）
├── __init__.py             # v2 入口
├── chat.py
├── commands.py
├── config.py
├── context.py
├── image2txt.py
├── manager.py
├── mcp_manager.py
└── send2root.py
```

## 注意事项

1. 需要配置至少一个超级用户（`pxchat_super_users`），否则插件无法正常运行
2. 使用前需通过 `px ai add` 命令添加至少一个 AI 模型配置
3. 图片识别需要单独配置支持多模态的模型，并通过 `px image switch` 切换
4. MCP 功能需要在 `.env` 中配置 `pxchat_mcp` 并通过 `px mcp on` 开启
5. 群聊功能需要先通过 `px group add <群号>` 启用对应群组
6. 适配器仅支持 OneBot v11

## License

MIT
