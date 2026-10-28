# astrbot_plugin_self_media

给 AstrBot 里的拟人角色一套「自我管理」能力：换自己的 QQ 头像、把网图收进表情包库、发 QQ 空间说说，以及几个让对话更像真人的输出层修正。

写给 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 用的，依赖 OneBot v11 平台（推荐 NapCat）。不是通用工具箱，是为「一个住在 QQ 里的人物」准备的手脚。

---

## 功能

### LLM 工具（角色自己决定要不要用）

| 工具 | 作用 | 依赖 |
|---|---|---|
| `set_my_avatar(image_url)` | 换自己的 QQ 头像 | NapCat `set_qq_avatar` |
| `add_sticker(image_url)` | 把网图收进表情包库，之后能直接发 | `astrbot_plugin_self_evolution` |
| `post_qzone(content, image_urls, visibility)` | 发一条 QQ 空间说说 | NapCat `send_qzone_msg` |
| `delete_qzone(tid)` | 删掉刚发的说说 | NapCat `delete_qzone_msg` |
| `note_person(note)` | 记一句关于眼前这个人的摘要 | 无 |
| `trust_friend(qq)` | 把 QQ 号加进「可以加我」白名单 | 无 |

### 钩子（不依赖模型自觉）

| 钩子 | 作用 |
|---|---|
| `normalize_layout` | 发送前按换行把消息拆成多条，避免「一个气泡里好几行」 |
| `inject_cross_session` | 跨会话摘要注入：饲养员能看到「谁来过、聊了什么」，其他人只看到「有 N 个人来过」 |
| `on_friend_request` | 白名单内的好友申请自动通过并打招呼（兜底，主逻辑建议放协议层） |

---

## 安装

### 1. 放进去

把 `astrbot_plugin_self_media` 整个目录放到 AstrBot 的数据目录下：

```
AstrBot/
└── data/
    └── plugins/
        └── astrbot_plugin_self_media/
            ├── main.py
            └── metadata.yaml
```

目录里必须能直接看到 `main.py`，不要多套一层文件夹。

### 2. 重启 AstrBot

插件第一次加载时会自动生成：

```
data/plugin_data/astrbot_plugin_self_media/config.json
```

内容是 `{"owner_qq": ""}`。

### 3. 填饲养员 QQ（必须做）

```json
{
  "owner_qq": "123456789"
}
```

**不填的话，所有需要权限的工具都会拒绝执行**——这是故意的，防止装完之后谁都能让她换头像。

改完再重启一次（或在面板里重载插件）。

### 4. 可选：表情包支持

`add_sticker` 直接写 `astrbot_plugin_self_evolution` 的表情包目录。想用这个能力，先装它：

- 仓库：https://github.com/Renyus/astrbot_plugin_self_evolution
- 插件的表情包存在 `data/plugin_data/astrbot_plugin_self_evolution/stickers/`

没装也不影响其他功能，`add_sticker` 会自己把目录和 `index.json` 建出来。

---

## 配置

只有一个配置项，在 `data/plugin_data/astrbot_plugin_self_media/config.json`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `owner_qq` | string | 饲养员 QQ。只有这个号能调用需要权限的工具 |

### 数据文件

```
data/plugin_data/astrbot_plugin_self_media/
├── config.json          # owner_qq
├── trusted.json         # 好友白名单（trust_friend 写入）
└── global_digest.json   # 跨会话摘要（note_person 写入，最多 50 条）
```

备份或迁移时，这三个文件一起带走。

---

## 用起来是什么样

装好之后，你在 QQ 里跟她说：

> 「换个头像吧，用这张 https://example.com/a.jpg」

她会先跟你说一句要换成什么，再调 `set_my_avatar`。

> 「把这张存成表情包 https://example.com/b.jpg」

回「存好了，现在库里有 3 张」。之后聊天里她自己会发表情包。

> 「发条说说，就说今天白饭很好吃」

她调 `post_qzone`，说说默认**好友可见**。发错了让她「删掉刚才那条」，她用 `delete_qzone`。

> 「12345678 是我朋友，他加你的时候通过一下」

她记进 `trusted.json`，对方申请时自动通过并回一句「进来了。有事说事，别问东问西。」

### 跨会话记忆

- 跟**饲养员**说话：注入「最近谁来找过你、聊了什么」，附带隐私规则（只许概括，不许复述原话）
- 跟**其他人**说话：只注入一句「最近有 N 个别人来找过你」，具体内容**根本不下发**

不是靠提示词劝住，是数据层就不给。想让她泄密也没有原料。

---

## 兼容性

| 项 | 要求 |
|---|---|
| AstrBot | ≥ 4.18.2（用到 `StarTools.get_data_dir`、`on_decorating_result`、`on_llm_request`） |
| 平台 | OneBot v11，推荐 NapCat |
| Python | 3.10+（用了 `str \| None` 之类的新语法） |
| 依赖 | `aiohttp`（AstrBot 自带） |

### 关于 NapCat 的版本

`post_qzone` / `delete_qzone` 调用的是 NapCat 的扩展 action：

```
send_qzone_msg    { content, images[], ugc_right, target_uins[] }
delete_qzone_msg  { tid }
```

这组接口不是所有 NapCat 版本都开放。如果调用报 `unknown action`，升级 NapCat 再试；实在没有就删掉这两个工具，其余功能不受影响。

`ugc_right` 映射：`public` → 1，`friends` → 2，`private` → 3。

---

## 设计上的几个取舍

**1. 权限在代码里，不在提示词里**

`_is_owner()` 是 `if` 判断，不是「请模型不要」。提示词能被绕，`if` 不能。所有敏感工具的**第一行**都是身份校验。

**2. 换行拆分放在发送层**

模型写不写换行它自己控制不了，所以在 `on_decorating_result` 里按换行拆消息段。配合 AstrBot 的 `segmented_reply`，每段独立发送、中间有间隔，观感就是「一句一句打出来」。

⚠️ 这个钩子在**流式输出**下不生效（AstrBot 的流式路径不走 `result.chain`）。要用请把 `provider_settings.streaming_response` 设为 `false`。

**3. 跨会话摘要只给饲养员看细节**

拟人角色一旦「知道所有人聊了什么」，就有泄密风险。所以注入是按身份分级的：完整清单只进饲养员的会话，其他人只拿到一个计数。

---

## 常见问题

**Q：工具调用了但没反应？**

先看日志里有没有 `[self_media]`。最常见原因是 `owner_qq` 没填，工具直接返回「这个得问我家饲养员」。

**Q：表情包存进去了但发不出来？**

`astrbot_plugin_self_evolution` 对索引有内存缓存。本插件写入后它可能读不到，需要在它的 `engine/sticker_store.py` 里给 `load_index` 加 mtime 校验（本仓库不包含这个改动，属于上游插件的补丁）。

**Q：她还在一条消息里换行？**

确认 `streaming_response = false`，并且 `platform_settings.segmented_reply.enable = true`。

**Q：别人也能让她换头像吗？**

不能。所有工具第一行都校验 `owner_qq`。

---

## License

MIT
