from nonebot import on_command, get_bot
from nonebot.adapters.onebot.v11 import MessageEvent, Message
from nonebot.params import CommandArg
from nonebot.rule import to_me
from .manager import chat_manager
from .send2root import send_forward_message, create_text_node, send_long_message
from .mcp_manager import mcp_client

# 权限检查函数
async def check_super_user(event: MessageEvent) -> bool:
    """检查用户是否为管理员"""
    user_id = str(event.user_id)
    return chat_manager.is_super_user(user_id)

# 命令定义 - 重新组织命令结构
about_cmd = on_command("px about", aliases={"px help"}, rule=to_me(), priority=10, block=True)
group_cmd = on_command("px group", rule=to_me(), priority=10, block=True)
ai_cmd = on_command("px ai", rule=to_me(), priority=10, block=True)
switch_cmd = on_command("px chat", rule=to_me(), priority=10, block=True)
personality_cmd = on_command("px personality", rule=to_me(), priority=10, block=True)
status_cmd = on_command("px status", rule=to_me(), priority=10, block=True)
probability_cmd = on_command("px prob", rule=to_me(), priority=10, block=True)
search_cmd = on_command("px search", rule=to_me(), priority=10, block=True)
image_cmd = on_command("px image", rule=to_me(), priority=10, block=True)
mcp_cmd = on_command("px mcp", rule=to_me(), priority=10, block=True)


@about_cmd.handle()
async def handle_about(event: MessageEvent, args: Message = CommandArg()):
    """显示插件帮助信息"""
    help_content = """
PX Chat 管理命令

📋 系统状态
• px status - 查看状态
• px activity - 群活跃度

👥 群组管理
• px group - 查看已启用群组
• px group add <群号> - 启用群组
• px group del <群号> - 禁用群组
• px group prob <群号> - 查看群独立概率
• px group prob <群号> set <0.0-1.0> - 设置群独立概率
• px group prob <群号> reset - 恢复使用全局概率

🔧 AI配置管理
• px ai - 查看AI配置
• px ai add <名称> <key> <url> <模型>
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

🎭 人设配置
• px personality - 查看人设
• px personality set <内容>

📊 群活跃概率设置
• px prob - 查看全局触发概率
• px prob set <0.0-1.0> - 设置全局触发概率

使用 'px <命令>' 查看详细用法
        """.strip()

    await send_long_message("PX Chat 帮助", help_content, user_id=event.user_id, group_id=getattr(event, "group_id", None))

@group_cmd.handle()
async def handle_group_manage(event: MessageEvent, args: Message = CommandArg()):
    if not await check_super_user(event):
        await group_cmd.finish("你没有权限")
    
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text:
        enabled_groups = chat_manager.get_enabled_groups()
        if not enabled_groups:
            await group_cmd.finish("当前没有启用的群聊")
        
        content = "👥 已启用群聊\n\n" + "\n".join(enabled_groups)
        await send_long_message("群组管理", content, user_id=event.user_id, group_id=getattr(event, "group_id", None))
        return
    
    parts = arg_text.split()
    action = parts[0]
    
    if action == "add":
        if len(parts) < 2:
            await group_cmd.finish("用法: px group add <群号>")
        group_id = parts[1]
        if chat_manager.enable_group(group_id):
            group_manager.renew_probability(group_id)
            await group_cmd.finish(f"✅ 已启用群聊 {group_id}")
        else:
            await group_cmd.finish(f"⚠️ 群聊 {group_id} 已启用")
    elif action == "del":
        if len(parts) < 2:
            await group_cmd.finish("用法: px group del <群号>")
        group_id = parts[1]
        if chat_manager.disable_group(group_id):
            await group_cmd.finish(f"✅ 已禁用群聊 {group_id}")
        else:
            await group_cmd.finish(f"⚠️ 群聊 {group_id} 未启用")
    elif action == "prob":
        # 每群独立概率管理
        if len(parts) < 2:
            await group_cmd.finish("用法:\n• px group prob <群号> - 查看群概率\n• px group prob <群号> set <0.0-1.0> - 设置群独立概率\n• px group prob <群号> reset - 恢复全局概率")
        
        group_id = parts[1]
        
        # 检查群是否已启用
        if not chat_manager.is_group_enabled(group_id):
            await group_cmd.finish(f"⚠️ 群聊 {group_id} 未启用，请先使用 px group add {group_id}")
        
        if len(parts) < 3:
            # 查看群概率
            group_prob = chat_manager.get_group_probability(group_id)
            global_prob = chat_manager.get_group_chat_probability()
            has_custom = group_id in chat_manager.get_all_group_probabilities()
            
            if has_custom:
                await group_cmd.finish(f"群聊 {group_id} 独立概率: {group_prob:.1%}（全局概率: {global_prob:.1%}）")
            else:
                await group_cmd.finish(f"群聊 {group_id} 使用全局概率: {global_prob:.1%}\n\n使用 px group prob {group_id} set <概率> 设置独立概率")
        
        sub_action = parts[2]
        
        if sub_action == "set":
            if len(parts) < 4:
                await group_cmd.finish("用法: px group prob <群号> set <0.0-1.0>")
            try:
                probability = float(parts[3])
                if not 0 <= probability <= 1:
                    await group_cmd.finish("概率值必须在 0.0 到 1.0 之间")
                if chat_manager.set_group_probability(group_id, probability):
                    await group_cmd.finish(f"✅ 已设置群聊 {group_id} 独立概率为: {probability:.1%}")
                else:
                    await group_cmd.finish("⚠️ 设置失败")
            except ValueError:
                await group_cmd.finish("概率值必须是一个数字")
        elif sub_action == "reset":
            if chat_manager.remove_group_probability(group_id):
                global_prob = chat_manager.get_group_chat_probability()
                await group_cmd.finish(f"✅ 已移除群聊 {group_id} 的独立概率，恢复使用全局概率: {global_prob:.1%}")
            else:
                await group_cmd.finish(f"⚠️ 群聊 {group_id} 未设置独立概率")
        else:
            await group_cmd.finish("用法:\n• px group prob <群号> set <0.0-1.0>\n• px group prob <群号> reset")
    else:
        await group_cmd.finish("用法:\n• px group add <群号>\n• px group del <群号>\n• px group prob <群号> [set <概率>|reset]")


@ai_cmd.handle()
async def handle_ai_config(event: MessageEvent, args: Message = CommandArg()):
    if not await check_super_user(event):
        await ai_cmd.finish("你没有权限")
    
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text:
        configs = chat_manager.get_ai_configs()
        current_config = chat_manager.get_current_ai_config()
        
        if not configs:
            await ai_cmd.finish("当前没有AI配置")
        
        messages = []
        messages.append(await create_text_node("AI配置", get_bot().self_id, 
                     f"AI配置管理\n\n当前使用: {current_config.get('name', '无')}\n共 {len(configs)} 个配置"))
        
        for i, config in enumerate(configs):
            is_current = " ✅" if config.get("name") == current_config.get("name") else ""
            safe_key = config['api_key'][:6] + '***' if len(config['api_key']) > 6 else '***'
            content = f"{config['name']}{is_current}\n接口: {config['api_url']}\n模型: {config['model']}\n密钥: {safe_key}"
            messages.append(await create_text_node("配置详情", get_bot().self_id, content))
        
        await send_forward_message(user_id=event.user_id, group_id=getattr(event, "group_id", None), messages=messages)
        return
    
    parts = arg_text.split()
    action = parts[0]
    
    if action == "add" and len(parts) >= 5:
        name, api_key, api_url, model = parts[1], parts[2], parts[3], parts[4]
        
        if chat_manager.add_ai_config(name, api_key, api_url, model):
            await ai_cmd.finish(f"✅ 已添加配置: {name}")
        else:
            await ai_cmd.finish(f"⚠️ 配置名称 {name} 已存在")
    
    elif action == "del" and len(parts) >= 2:
        name = parts[1]
        success, was_chat_config, was_image_config = chat_manager.remove_ai_config(name)
        if success:
            message = f"✅ 已删除配置: {name}"
            if was_chat_config:
                current_config = chat_manager.get_current_ai_config()
                message += f"\n⚠️ 该配置是当前聊天配置，已自动切换到: {current_config.get('name', '无')}"
            if was_image_config:
                current_image_config = chat_manager.get_current_image_recognition_config()
                message += f"\n⚠️ 该配置是当前图片识别配置，已自动切换到: {current_image_config.get('name', '无')}"
            await ai_cmd.finish(message)
        else:
            await ai_cmd.finish(f"⚠️ 未找到配置: {name}")
    
    elif action == "switch" and len(parts) >= 2:
        name = parts[1]
        if chat_manager.switch_ai_config(name):
            await ai_cmd.finish(f"✅ 已切换到配置: {name}")
        else:
            await ai_cmd.finish(f"⚠️ 未找到配置: {name}")
    else:
        await ai_cmd.finish("用法:\n• px ai - 查看配置\n• px ai add <名称> <key> <url> <模型>\n• px ai del <名称>\n• px ai switch <名称>")


@switch_cmd.handle()
async def handle_switch(event: MessageEvent, args: Message = CommandArg()):
    if not await check_super_user(event):
        await switch_cmd.finish("你没有权限")
    
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text:
        status = "✅开启" if chat_manager.is_chat_enabled() else "❌关闭"
        await switch_cmd.finish(f"聊天功能状态: {status}")
    
    if arg_text == "on":
        if chat_manager.set_chat_enabled(True):
            await switch_cmd.finish("✅ 已开启聊天功能")
        else:
            await switch_cmd.finish("⚠️ 聊天功能已是开启状态")
    elif arg_text == "off":
        if chat_manager.set_chat_enabled(False):
            await switch_cmd.finish("✅ 已关闭聊天功能")
        else:
            await switch_cmd.finish("⚠️ 聊天功能已是关闭状态")
    else:
        await switch_cmd.finish("用法: px chat on/off")


@personality_cmd.handle()
async def handle_personality(event: MessageEvent, args: Message = CommandArg()):
    if not await check_super_user(event):
        await personality_cmd.finish("你没有权限")
    
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text:
        personality = chat_manager.get_personality()
        await send_long_message("当前人设配置", personality, user_id=event.user_id, group_id=getattr(event, "group_id", None))
        return
    
    if arg_text.startswith("set "):
        new_personality = arg_text[4:].strip()
        if chat_manager.set_personality(new_personality):
            await personality_cmd.finish("✅ 已更新人设配置")
        else:
            await personality_cmd.finish("⚠️ 人设配置未更改")
    else:
        await personality_cmd.finish("用法: px personality set <人设内容>")


@probability_cmd.handle()
async def handle_probability(event: MessageEvent, args: Message = CommandArg()):
    if not await check_super_user(event):
        await probability_cmd.finish("你没有权限")
    
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text:
        probability = chat_manager.get_group_chat_probability()
        group_probs = chat_manager.get_all_group_probabilities()
        
        msg = f"全局群聊触发概率: {probability:.1%}"
        if group_probs:
            msg += f"\n\n独立概率配置:"
            for gid, prob in group_probs.items():
                msg += f"\n  群 {gid}: {prob:.1%}"
        else:
            msg += "\n\n暂无群聊设置独立概率"
        
        msg += "\n\n用法:\n• px prob set <0.0-1.0> - 设置全局概率\n• px group prob <群号> set <0.0-1.0> - 设置群独立概率"
        await probability_cmd.finish(msg)
    
    if arg_text.startswith("set "):
        try:
            probability = float(arg_text[4:].strip())
            if not 0 <= probability <= 1:
                await probability_cmd.finish("概率值必须在 0.0 到 1.0 之间")
            
            if chat_manager.set_group_chat_probability(probability):
                await probability_cmd.finish(f"✅ 已设置全局群聊触发概率为: {probability:.1%}")
            else:
                await probability_cmd.finish("⚠️ 概率值未更改")
        except ValueError:
            await probability_cmd.finish("概率值必须是一个数字")
    else:
        await probability_cmd.finish("用法: px prob set <概率值>")


@status_cmd.handle()
async def handle_status(event: MessageEvent):
    if not await check_super_user(event):
        await status_cmd.finish("你没有权限")
    
    status_info = []
    
    # 功能状态
    status_info.append("📊 功能状态")
    status_info.append(f"聊天功能: {'✅开启' if chat_manager.is_chat_enabled() else '❌关闭'}")
    status_info.append(f"搜索功能: {'✅开启' if chat_manager.is_search_enabled() else '❌关闭'}")
    status_info.append(f"图片识别: {'✅开启' if chat_manager.is_image_recognition_enabled() else '❌关闭'}")
    status_info.append(f"MCP功能: {'✅开启' if chat_manager.is_mcp_enabled() else '❌关闭'}")
    status_info.append("")
    
    # MCP服务器状态
    mcp_servers = chat_manager.get_mcp_servers()
    enabled_mcp_servers = chat_manager.get_enabled_mcp_servers()
    
    status_info.append("🔧 MCP服务器状态")
    status_info.append(f"总服务器: {len(mcp_servers)}个")
    status_info.append(f"启用服务器: {len(enabled_mcp_servers)}个")
    
    if mcp_servers:
        for server_name, config in mcp_servers.items():
            enabled = config.get("enabled", True)
            server_type = config.get("type", "sse")
            status_icon = "✅" if enabled else "❌"
            
            if server_type == "sse":
                url = config.get("url", "N/A")
                status_info.append(f"  {status_icon} {server_name} (SSE)")
            elif server_type == "stdio":
                status_info.append(f"  {status_icon} {server_name} (stdio)")
    else:
        status_info.append("  暂无MCP服务器配置")
    status_info.append("")
    
    # 概率设置
    probability = chat_manager.get_group_chat_probability()
    status_info.append(f"📈 全局群活跃度基础值: {probability:.1%}")
    
    group_probs = chat_manager.get_all_group_probabilities()
    if group_probs:
        status_info.append("📈 群独立活跃度:")
        for gid, prob in group_probs.items():
            status_info.append(f"  群 {gid}: {prob:.1%}")
    status_info.append("")
    
    # 群组信息
    enabled_groups = chat_manager.get_enabled_groups()
    status_info.append(f"👥 启用群组: {len(enabled_groups)}个")
    if enabled_groups:
        # 只显示前5个群组，避免消息过长
        display_groups = enabled_groups[:5]
        groups_text = ", ".join(display_groups)
        if len(enabled_groups) > 5:
            groups_text += f" ...等{len(enabled_groups)}个群组"
        status_info.append(f"  群组列表: {groups_text}")
    status_info.append("")
    
    # 管理员信息
    super_users = chat_manager.get_super_users()
    status_info.append(f"👑 管理员: {len(super_users)}人")
    if super_users:
        # 只显示前3个管理员，避免消息过长
        display_users = super_users[:3]
        users_text = ", ".join(display_users)
        if len(super_users) > 3:
            users_text += f" ...等{len(super_users)}人"
        status_info.append(f"  管理员列表: {users_text}")
    status_info.append("")
    
    # 配置信息
    current_config = chat_manager.get_current_ai_config()
    current_image_config = chat_manager.get_current_image_recognition_config()
    status_info.append(f"🔧 聊天配置: {current_config.get('name', '无')}")
    status_info.append(f"🖼️ 图片配置: {current_image_config.get('name', '无')}")
    
    # 如果有MCP工具缓存，显示工具数量
    try:
        if chat_manager.is_mcp_enabled() and enabled_mcp_servers:
            tools = await mcp_client.get_tools()
            if tools:
                status_info.append(f"🛠️ MCP工具: {len(tools)}个可用")
            else:
                status_info.append("🛠️ MCP工具: 无可用工具")
    except Exception:
        status_info.append("🛠️ MCP工具: 获取失败")

    content = "\n".join(status_info)
    await send_long_message("系统完整状态", content, user_id=event.user_id, group_id=getattr(event, "group_id", None))


@search_cmd.handle()
async def handle_search(event: MessageEvent, args: Message = CommandArg()):
    if not await check_super_user(event):
        await search_cmd.finish("你没有权限")
    
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text:
        status = "✅开启" if chat_manager.is_search_enabled() else "❌关闭"
        await search_cmd.finish(f"搜索功能状态: {status}\n\n用法: px search on/off")
    
    if arg_text == "on":
        if chat_manager.set_search_enabled(True):
            await search_cmd.finish("✅ 已开启搜索功能")
        else:
            await search_cmd.finish("⚠️ 搜索功能已是开启状态")
    elif arg_text == "off":
        if chat_manager.set_search_enabled(False):
            await search_cmd.finish("✅ 已关闭搜索功能")
        else:
            await search_cmd.finish("⚠️ 搜索功能已是关闭状态")
    else:
        await search_cmd.finish("用法: px search on/off")


@image_cmd.handle()
async def handle_image_config(event: MessageEvent, args: Message = CommandArg()):
    if not await check_super_user(event):
        await image_cmd.finish("你没有权限")
    
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text:
        status = "✅开启" if chat_manager.is_image_recognition_enabled() else "❌关闭"
        current_config = chat_manager.get_current_image_recognition_config()
        
        response = f"图片识别功能: {status}\n"
        response += f"当前配置: {current_config.get('name', '无')}\n\n"
        response += "用法:\n• px image on/off - 开关功能\n• px image switch <配置名> - 切换配置"
        
        await image_cmd.finish(response)
    
    parts = arg_text.split()
    
    if parts[0] == "on":
        if chat_manager.set_image_recognition_enabled(True):
            await image_cmd.finish("✅ 已开启图片识别功能")
        else:
            await image_cmd.finish("⚠️ 图片识别功能已是开启状态")
    elif parts[0] == "off":
        if chat_manager.set_image_recognition_enabled(False):
            await image_cmd.finish("✅ 已关闭图片识别功能")
        else:
            await image_cmd.finish("⚠️ 图片识别功能已是关闭状态")
    elif parts[0] == "switch" and len(parts) >= 2:
        name = parts[1]
        if chat_manager.switch_image_recognition_config(name):
            await image_cmd.finish(f"✅ 已切换到图片识别配置: {name}")
        else:
            await image_cmd.finish(f"⚠️ 未找到配置: {name}")
    else:
        await image_cmd.finish("用法:\n• px image on/off\n• px image switch <配置名>")

@mcp_cmd.handle()
async def handle_mcp(event: MessageEvent, args: Message = CommandArg()):
    if not await check_super_user(event):
        await mcp_cmd.finish("你没有权限")
    
    arg_text = args.extract_plain_text().strip()
    
    if not arg_text:
        # 显示MCP状态和服务器列表
        status = "✅开启" if chat_manager.is_mcp_enabled() else "❌关闭"
        servers = chat_manager.get_mcp_servers()
        
        if not servers:
            await mcp_cmd.finish(f"MCP功能: {status}\n\n当前没有配置MCP服务器")
        
        content = f"MCP功能: {status}\n\n已配置服务器:\n"
        for server_name, config in servers.items():
            enabled = "✅" if config.get("enabled", True) else "❌"
            server_type = config.get("type", "sse")
            if server_type == "sse":
                content += f"{enabled} {server_name} (SSE): {config.get('url', 'N/A')}\n"
            elif server_type == "stdio":
                command = config.get('command', 'N/A')
                args_list = config.get('args', [])
                content += f"{enabled} {server_name} (stdio): {command} {args_list}\n"
        
        content += "\n用法:\n• px mcp on/off - 开关MCP功能\n• px mcp server <服务器名> on/off - 开关单个服务器\n• px mcp refresh - 刷新工具缓存\n• px mcp tools - 查看可用工具"
        await send_long_message("MCP管理", content, user_id=event.user_id, group_id=getattr(event, "group_id", None))
        return
    
    parts = arg_text.split()
    
    if parts[0] == "on":
        if chat_manager.set_mcp_enabled(True):
            # 刷新工具缓存
            mcp_client.clear_cache()
            await mcp_cmd.finish("✅ 已开启MCP功能，工具缓存已刷新")
        else:
            await mcp_cmd.finish("⚠️ MCP功能已是开启状态")
    elif parts[0] == "off":
        if chat_manager.set_mcp_enabled(False):
            await mcp_cmd.finish("✅ 已关闭MCP功能")
        else:
            await mcp_cmd.finish("⚠️ MCP功能已是关闭状态")
    elif len(parts) >= 3 and parts[0] == "server":
        server_name = parts[1]
        action = parts[2]
        
        servers = chat_manager.get_mcp_servers()
        if server_name not in servers:
            await mcp_cmd.finish(f"⚠️ 未找到服务器: {server_name}")
        
        if action == "on":
            if chat_manager.set_mcp_server_enabled(server_name, True):
                # 刷新工具缓存
                mcp_client.clear_cache()
                await mcp_cmd.finish(f"✅ 已启用服务器: {server_name}，工具缓存已刷新")
            else:
                await mcp_cmd.finish(f"⚠️ 服务器 {server_name} 已是启用状态")
        elif action == "off":
            if chat_manager.set_mcp_server_enabled(server_name, False):
                # 刷新工具缓存
                mcp_client.clear_cache()
                await mcp_cmd.finish(f"✅ 已禁用服务器: {server_name}，工具缓存已刷新")
            else:
                await mcp_cmd.finish(f"⚠️ 服务器 {server_name} 已是禁用状态")
        else:
            await mcp_cmd.finish("用法: px mcp server <服务器名> on/off")
    elif parts[0] == "refresh":
        # 刷新工具缓存
        mcp_client.clear_cache()
        await mcp_cmd.finish("✅ 已刷新MCP工具缓存")
    elif parts[0] == "tools":
        # 显示可用工具
        try:
            tools = await mcp_client.get_tools()
            if not tools:
                await mcp_cmd.send("❌ 没有可用的MCP工具")
                return
            
            content = "🛠️ 可用MCP工具:\n\n"
            for tool in tools:
                content += f"• {tool['name']}\n"
                content += f"  描述: {tool['description']}\n"
                content += f"  服务器: {tool['server_name']}\n\n"
            
            await send_long_message("MCP工具列表", content, user_id=event.user_id, group_id=getattr(event, "group_id", None))
        except Exception as e:
            await mcp_cmd.finish(f"❌ 获取工具列表失败")
    else:
        await mcp_cmd.finish("用法:\n• px mcp on/off\n• px mcp server <服务器名> on/off\n• px mcp refresh - 刷新缓存\n• px mcp tools - 查看工具")