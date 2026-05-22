import bpy


TRANSLATION_DOMAIN = __package__ or "umodel_tools"
ZH_HANS = "zh_HANS"

_CONTEXTS = getattr(getattr(bpy.app, "translations", None), "contexts", None)
_DEFAULT_CONTEXT = getattr(_CONTEXTS, "default", "*")
_OPERATOR_CONTEXT = getattr(_CONTEXTS, "operator_default", "Operator")

_TRANSLATIONS_REGISTERED = False


def _with_contexts(messages: dict[str, str]) -> dict[tuple[str, str], str]:
    translated: dict[tuple[str, str], str] = {}
    for msgid, msgstr in messages.items():
        translated[(_DEFAULT_CONTEXT, msgid)] = msgstr
        translated[(_OPERATOR_CONTEXT, msgid)] = msgstr
    return translated


_ZH_HANS_MESSAGES = {
    "UModel Tools": "UModel 工具",
    "Import Unreal Engine game scenes and assets into Blender": "将 Unreal Engine 游戏场景和资产导入 Blender",
    "Game profiles": "游戏配置档",
    "Game profiles:": "游戏配置档：",
    "Profile settings": "配置档设置",
    "Profile settings:": "配置档设置：",
    "Game": "游戏",
    "UModel Export Directory": "UModel 导出目录",
    "Asset Directory": "资产缓存目录",
    "Display current profile": "显示当前配置档",
    "Verbose import": "输出详细导入日志",
    "Advanced Import Validation": "高级导入验证",
    "Show Advanced Import Validation Settings": "显示高级导入验证设置",
    "Enable Import Validation": "启用导入验证",
    "Validation Preset": "验证预设",
    "Basic Default": "基础默认",
    "Strict": "严格",
    "Custom": "自定义",
    "Min Mesh Count": "最小网格数量",
    "Min Light Count": "最小灯光数量",
    "Min Material Count": "最小材质数量",
    "Require Any Material Assigned": "要求至少分配一个材质",
    "Reject Dict-like Names": "拒绝类似字典的名称",
    "Allow Missing Placeholder Materials": "允许缺失占位材质",
    "Advanced Path Resolution": "高级路径解析",
    "Show Advanced Path Resolution Settings": "显示高级路径解析设置",
    "Enable UModel Path Inference": "启用 UModel 路径推导",
    "Path Inference Mode": "路径推导模式",
    "Strict Exact": "严格精确匹配",
    "Aggressive": "激进模式",
    "Enable Suffix Index": "启用后缀索引",
    "Report Path Resolution Stats": "报告路径解析统计",
    "Exact Resolved Count": "精确解析数量",
    "Inferred Resolved Count": "推导解析数量",
    "Suffix Resolved Count": "后缀解析数量",
    "Unresolved Count": "未解析数量",
    "Import Unreal Map": "导入 Unreal 地图",
    "Import Unreal Asset": "导入 Unreal 资产",
    "Import Unreal Assets": "导入 Unreal 资产",
    "Importing map": "正在导入地图",
    "Importing asset": "正在导入资产",
    "Importing assets": "正在导入资产",
    "Failed importing asset": "导入资产失败",
    "Missing placeholder material": "缺失占位材质",
    "Path resolution summary": "路径解析摘要",
    "Resolved truncated UModel path": "已解析截断的 UModel 路径",
    "Ambiguous asset path": "资产路径存在歧义",
    "Unresolved asset path": "无法解析资产路径",
    "Asset path": "资产路径",
    "Asset subdir": "资产子目录",
    "Enabled": "启用",
    "UModel Tools Asset": "UModel 工具资产",
    "Recover Unreal Asset": "恢复 Unreal 资产",
    "Realign Unreal Asset": "重新对齐 Unreal 资产",
    "Load PBR textures": "加载 PBR 贴图",
    "Use backface culling": "使用背面剔除",
    "Texture format": "贴图格式",
    "List Actions": "列表操作",
    "Profiles": "配置档",
    "Name": "名称",
    "Debug": "调试",
    "Fail on traceback-like CLI errors": "遇到类似 traceback 的 CLI 错误时失败",
    "UMT Active profile": "UMT 当前配置档",
    "Import validation failed. Check console for details.": "导入验证失败。请查看控制台了解详情。",
    "Import finished with validation warnings. Check console for details.": "导入已完成，但存在验证警告。请查看控制台了解详情。",
    "Map import failed. Check console for details.": "地图导入失败。请查看控制台了解详情。",
    "Asset import had warnnings. Check console for details.": "资产导入存在警告。请查看控制台了解详情。",
    "Asset path was not provided.": "未提供资产路径。",
    "You need to have an active game profile selected.": "需要先选择一个活动游戏配置档。",
    "You need to specify a UModel export dir in Scene properties.": "需要在场景属性中指定 UModel 导出目录。",
    "You need to specify an asset dir in Scene properties.": "需要在场景属性中指定资产缓存目录。",
    "Failed to import asset.": "资产导入失败。",
    "Exactly 2 objects must be selected.": "必须选中 2 个对象。",
    "One of the objects must be an Unreal asset.": "其中一个对象必须是 Unreal 资产。",
}


ADDON_TRANSLATIONS_DICT = {
    ZH_HANS: _with_contexts(_ZH_HANS_MESSAGES),
}


def _translations_api():
    return getattr(bpy.app, "translations", None)


def _api_callable(name: str) -> bool:
    api = _translations_api()
    return api is not None and callable(getattr(api, name, None))


def register_translations() -> bool:
    global _TRANSLATIONS_REGISTERED

    if _TRANSLATIONS_REGISTERED:
        return True

    if not _api_callable("register"):
        return False

    api = _translations_api()
    try:
        api.register(TRANSLATION_DOMAIN, ADDON_TRANSLATIONS_DICT)
    except ValueError:
        unregister_translations()
        api.register(TRANSLATION_DOMAIN, ADDON_TRANSLATIONS_DICT)

    _TRANSLATIONS_REGISTERED = True
    return True


def unregister_translations() -> bool:
    global _TRANSLATIONS_REGISTERED

    if not _api_callable("unregister"):
        _TRANSLATIONS_REGISTERED = False
        return False

    api = _translations_api()
    try:
        api.unregister(TRANSLATION_DOMAIN)
    except ValueError:
        _TRANSLATIONS_REGISTERED = False
        return False

    _TRANSLATIONS_REGISTERED = False
    return True


def _translate(function_name: str, msgid: str) -> str:
    api = _translations_api()
    function = getattr(api, function_name, None) if api is not None else None
    if not callable(function):
        return msgid
    return function(msgid)


def t_iface(msgid: str) -> str:
    return _translate("pgettext_iface", msgid)


def t_tip(msgid: str) -> str:
    return _translate("pgettext_tip", msgid)


def t_report(msgid: str) -> str:
    return _translate("pgettext_rpt", msgid)
