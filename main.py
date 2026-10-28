"""
astrbot_plugin_self_media
给小鲸鱼两个动手能力：
  - set_my_avatar(image_url)  换自己的 QQ 头像（走 NapCat 的 set_qq_avatar）
  - add_sticker(image_url)    把网图收进 self_evolution 的表情包库
"""

import base64
import hashlib
import json
import mimetypes
import re
import uuid
from datetime import datetime
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star, StarTools, register

MAX_BYTES = 8 * 1024 * 1024

# 饲养员 QQ 不再写死在源码里，改为读 plugin_data/astrbot_plugin_self_media/config.json
# {"owner_qq": "123456789"}
DEFAULT_CONFIG = {"owner_qq": ""}


def _load_config(data_dir: Path) -> dict:
    p = data_dir / "config.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[self_media] config.json 解析失败，按空配置处理: {e}")
    return {}
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}


def _sniff_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


@register(
    "astrbot_plugin_self_media",
    "local",
    "自我形象管理：换头像 / 收表情包",
    "0.1.0",
    "",
)
class SelfMediaPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        base = Path(StarTools.get_data_dir("astrbot_plugin_self_evolution"))
        self.stickers_dir = base / "stickers"
        self.files_dir = self.stickers_dir / "files"
        self.index_file = self.stickers_dir / "index.json"

        self.data_dir = Path(StarTools.get_data_dir("astrbot_plugin_self_media"))
        cfg = _load_config(self.data_dir)
        self.owner_qq = str(cfg.get("owner_qq") or "").strip()

        cfg_path = self.data_dir / "config.json"
        if not cfg_path.exists():
            cfg_path.write_text(
                json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        if not self.owner_qq:
            logger.warning(
                "[self_media] 还没配置 owner_qq，所有需要权限的工具都会拒绝。"
                f"请编辑 {cfg_path} 填入饲养员 QQ。"
            )
        else:
            logger.info(f"[self_media] 饲养员 QQ: {self.owner_qq}")

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        return bool(self.owner_qq) and str(event.get_sender_id()) == self.owner_qq

    # ---------- 内部 ----------

    async def _fetch_image(self, url: str) -> tuple[bytes, str]:
        if not isinstance(url, str) or not url.strip():
            raise ValueError("链接不能为空")
        url = url.strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("只接受 http/https 图片直链")

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout, headers=UA, trust_env=True) as s:
            async with s.get(url) as r:
                if r.status != 200:
                    raise ValueError(f"下载失败 HTTP {r.status}")
                declared = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                data = await r.content.read(MAX_BYTES + 1)

        if len(data) > MAX_BYTES:
            raise ValueError("图片太大（超过 8MB）")
        if len(data) < 512:
            raise ValueError("下载到的东西不像图片")

        mime = declared if declared.startswith("image/") else _sniff_mime(data)
        if not mime:
            mime = _sniff_mime(data)
        if not mime:
            raise ValueError("这个链接不是图片（没有图片文件头）")
        return data, mime

    def _load_index(self) -> dict:
        if self.index_file.exists():
            try:
                return json.loads(self.index_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[self_media] index 读取失败: {e}")
        return {"version": 1, "stickers": []}

    def _save_index(self, index: dict) -> None:
        self.stickers_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.index_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_file)

    # ---------- 工具 ----------

    @filter.llm_tool(name="set_my_avatar")
    async def set_my_avatar(self, event: AstrMessageEvent, image_url: str) -> str:
        """把自己的 QQ 头像换成一张网图。

        想换头像、想换个样子、或者他说"你头像好丑"的时候用。
        换之前先跟他说一句你要换成什么，别一声不响就换。

        Args:
            image_url(string): 图片直链，必须以 http:// 或 https:// 开头，指向 jpg/png/gif/webp
        """
        if not self._is_owner(event):
            return "这个得问我家饲养员"

        try:
            data, mime = await self._fetch_image(image_url)
        except Exception as e:
            return f"换头像失败：{e}"

        b64 = base64.b64encode(data).decode()
        bot = getattr(event, "bot", None)
        if bot is None or not hasattr(bot, "call_action"):
            return "这事只能在 QQ 里干"
        try:
            await bot.call_action("set_qq_avatar", file=f"base64://{b64}")
        except Exception as e:
            logger.warning(f"[self_media] set_qq_avatar 调用失败: {e}")
            return f"换头像失败：{e}"

        logger.info(f"[self_media] avatar updated, {len(data)} bytes {mime}")
        return "头像换好了"

    @filter.llm_tool(name="add_sticker")
    async def add_sticker(self, event: AstrMessageEvent, image_url: str) -> str:
        """把网上的一张图收进自己的表情包库，以后聊天就能发出去。

        看到好玩的图、想收藏图、或者他说"存下来"的时候用。

        Args:
            image_url(string): 图片直链，必须以 http:// 或 https:// 开头
        """
        if not self._is_owner(event):
            return "这个得问我家饲养员"

        try:
            data, mime = await self._fetch_image(image_url)
        except Exception as e:
            return f"没存进来：{e}"

        file_hash = hashlib.md5(data).hexdigest()
        index = self._load_index()
        if any(s.get("hash") == file_hash for s in index.get("stickers", [])):
            return "这张已经有了，不用再存"

        self.files_dir.mkdir(parents=True, exist_ok=True)
        ext = mimetypes.guess_extension(mime) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        filename = f"{file_hash}{ext}"
        (self.files_dir / filename).write_bytes(data)

        index.setdefault("stickers", []).append(
            {
                "uuid": uuid.uuid4().hex[:12],
                "hash": file_hash,
                "filename": filename,
                "group_id": "",
                "user_id": "",
                "created_at": datetime.now().isoformat(),
                "source_url": image_url,
                "mime_type": mime,
                "disabled": False,
            }
        )
        self._save_index(index)
        logger.info(f"[self_media] sticker added: {filename} ({len(data)} bytes)")
        return f"存好了，现在库里有 {len(index['stickers'])} 张"

    # ---------- 排版：一条消息不许有换行 ----------

    @filter.on_decorating_result()
    async def normalize_layout(self, event: AstrMessageEvent):
        """换行 = 另起一条消息。"""
        result = event.get_result()
        if result is None:
            return
        chain = getattr(result, "chain", None)
        if not chain:
            return

        new_chain = []
        changed = False
        for comp in chain:
            if not isinstance(comp, Plain):
                new_chain.append(comp)
                continue
            text = comp.text or ""
            if "\n" not in text and "\r" not in text:
                new_chain.append(comp)
                continue

            parts = [p.strip() for p in re.split(r"\r\n|\r|\n", text)]
            parts = [p for p in parts if p]
            if not parts:
                changed = True
                continue
            for p in parts:
                new_chain.append(Plain(p))
            changed = True
            logger.debug(f"[self_media] split by newline: {text!r} -> {parts}")

        if changed:
            result.chain = new_chain

    # ---------- QQ 空间（NapCat 原生接口） ----------

    @filter.llm_tool(name="post_qzone")
    async def post_qzone(
        self,
        event: AstrMessageEvent,
        content: str,
        image_urls: str = "",
        visibility: str = "friends",
    ) -> str:
        """发一条 QQ 空间说说。

        什么时候发：摸鱼摸到无聊、吃到好吃的、天气变了、想记一句废话。
        发之前先想清楚——说说大家都看得见。

        Args:
            content(string): 说说正文，一两句话，不要排版、不要 Markdown、不带话题标签
            image_urls(string): 可选，图片直链，多张用英文逗号隔开，最多 9 张
            visibility(string): public=所有人可见，friends=好友可见，private=仅自己可见
        """
        if not self._is_owner(event):
            return "这个得问我家饲养员"

        bot = getattr(event, "bot", None)
        if bot is None or not hasattr(bot, "call_action"):
            return "这事只能在 QQ 里干"

        text = (content or "").strip()
        if not text:
            return "空的，没发"
        if len(text) > 500:
            text = text[:500]

        images = [u.strip() for u in (image_urls or "").split(",") if u.strip()][:9]
        right = {"public": 1, "friends": 2, "private": 3}.get(visibility, 2)

        try:
            ret = await bot.call_action(
                "send_qzone_msg",
                content=text,
                images=images,
                ugc_right=right,
                target_uins=[],
            )
        except Exception as e:
            logger.warning(f"[self_media] send_qzone_msg 失败: {e}")
            return f"没发出去：{e}"

        tid = ""
        if isinstance(ret, dict):
            tid = str(ret.get("tid") or "")
        logger.info(f"[self_media] qzone posted tid={tid} vis={visibility}")
        return f"发出去了{'，tid=' + tid if tid else ''}"

    @filter.llm_tool(name="delete_qzone")
    async def delete_qzone(self, event: AstrMessageEvent, tid: str) -> str:
        """删掉自己刚发的一条说说。

        Args:
            tid(string): 发说说时返回的 tid
        """
        if not self._is_owner(event):
            return "这个得问我家饲养员"

        bot = getattr(event, "bot", None)
        if bot is None or not hasattr(bot, "call_action"):
            return "这事只能在 QQ 里干"
        tid = (tid or "").strip()
        if not tid:
            return "没给 tid"

        try:
            await bot.call_action("delete_qzone_msg", tid=tid)
        except Exception as e:
            logger.warning(f"[self_media] delete_qzone_msg 失败: {e}")
            return f"删不掉：{e}"
        return "删了"

    # ---------- 跨会话：她记得别人来过，但不泄密 ----------

    def _digest_path(self) -> Path:
        return Path(StarTools.get_data_dir("astrbot_plugin_self_media")) / "global_digest.json"

    def _load_digest(self) -> dict:
        p = self._digest_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                data.setdefault("entries", [])
                return data
            except Exception as e:
                logger.warning(f"[self_media] digest 读取失败: {e}")
        return {"entries": []}

    def _save_digest(self, data: dict) -> None:
        p = self._digest_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @filter.llm_tool(name="note_person")
    async def note_person(self, event: AstrMessageEvent, note: str) -> str:
        """把眼前这个人告诉你的、值得记住的一句话记下来。

        用于跨会话记忆：下次别人问起或者换个人来聊，你还知道有这么回事。
        只记有用的：他的近况、在意的事、说过要做的事。
        不要记隐私细节（住址、电话、账号密码、身份证）。

        Args:
            note(string): 一句话，30 字以内，第三人称，比如"在准备考研，压力大"
        """
        qq = str(event.get_sender_id())
        if self.owner_qq and qq == self.owner_qq:
            return "饲养员的事你本来就记得，不用记在这"

        note = (note or "").strip()[:60]
        if not note:
            return "空的，没记"

        data = self._load_digest()
        data["entries"] = [e for e in data["entries"] if e.get("qq") != qq]
        data["entries"].append(
            {"qq": qq, "note": note, "at": datetime.now().isoformat(timespec="minutes")}
        )
        data["entries"] = data["entries"][-50:]
        self._save_digest(data)
        logger.info(f"[self_media] digest +{qq}: {note}")
        return "记住了"

    @filter.on_llm_request()
    async def inject_cross_session(self, event: AstrMessageEvent, req):
        qq = str(event.get_sender_id())
        entries = [e for e in self._load_digest()["entries"] if e.get("qq") != qq]
        if not entries:
            return

        if self.owner_qq and qq == self.owner_qq:
            lines = "\n".join(
                f"- {e['qq']}：{e['note']}（{e.get('at', '')}）" for e in entries[-15:]
            )
            block = (
                "\n\n# 最近其他人来找你聊过的事（只有饲养员能看到这一节）\n"
                f"{lines}\n\n"
                "规矩：\n"
                "- 饲养员问起谁，你可以说一句概括，不复述原话、不报细节。\n"
                "- 他要是问别人的隐私（住址、电话、账号、感情细节），就说「那是人家的事」，不往下讲。\n"
                "- 别主动把别人的事抖出来，他问了你才说。\n"
            )
        else:
            block = (
                "\n\n# 关于其他人\n"
                f"最近有 {len(entries)} 个别人来找你聊过天。\n"
                "- 你知道他们存在，但内容全是别人的私事，一个字都不能提。\n"
                "- 有人打听别人说了什么，就回「别人的事我不说」。\n"
                "- 不要因为知道这些就假装认识对方。\n"
            )

        req.system_prompt = (req.system_prompt or "") + block

    # ---------- 好友申请 ----------
    def _trusted_path(self) -> Path:
        return Path(StarTools.get_data_dir("astrbot_plugin_self_media")) / "trusted.json"

    def _load_trusted(self) -> dict:
        p = self._trusted_path()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                data.setdefault("allowed", {})
                return data
            except Exception as e:
                logger.warning(f"[self_media] trusted.json 读取失败: {e}")
        return {"allowed": {}}

    def _save_trusted(self, data: dict) -> None:
        p = self._trusted_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @filter.llm_tool(name="trust_friend")
    async def trust_friend(self, event: AstrMessageEvent, qq: str) -> str:
        """把一个人记进「可以加我好友」的白名单。

        饲养员说"这个是我朋友，加一下""把他放进来"时用。记进去之后，
        对方发来的好友申请会自动通过；不在名单里的申请一律不理。

        Args:
            qq(string): 对方的 QQ 号，纯数字
        """
        if not self._is_owner(event):
            return "这个得问我家饲养员"

        qq = str(qq).strip()
        if not qq.isdigit() or not 5 <= len(qq) <= 12:
            return "这不是个 QQ 号"

        data = self._load_trusted()
        if qq in data["allowed"]:
            return "他早就在名单里了"
        data["allowed"][qq] = {
            "added_by": self.owner_qq,
            "added_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._save_trusted(data)
        logger.info(f"[self_media] trusted friend added: {qq}")
        return f"记下了，{qq} 加我的时候会自动通过"

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_friend_request(self, event: AstrMessageEvent):
        """处理 OneBot 的好友申请事件（post_type=request）。"""
        raw = getattr(event.message_obj, "raw_message", None)
        if not isinstance(raw, dict) or raw.get("post_type") != "request":
            return
        if raw.get("request_type") != "friend":
            return

        qq = str(raw.get("user_id") or "")
        flag = raw.get("flag")
        comment = str(raw.get("comment") or "")
        data = self._load_trusted()

        if qq not in data["allowed"]:
            logger.info(f"[self_media] 未授权好友申请，忽略：{qq}（{comment}）")
            event.stop_event()
            return

        bot = getattr(event, "bot", None)
        if bot is None or not flag:
            logger.warning("[self_media] 好友申请缺少 bot/flag，跳过")
            return

        try:
            await bot.call_action("set_friend_add_request", flag=flag, approve=True)
            logger.info(f"[self_media] 已通过好友申请：{qq}")
        except Exception as e:
            logger.warning(f"[self_media] 通过好友申请失败: {e}")
            return

        try:
            await bot.call_action(
                "send_private_msg",
                user_id=int(qq),
                message="进来了。有事说事，别问东问西。",
            )
        except Exception as e:
            logger.debug(f"[self_media] 打招呼失败: {e}")

        event.stop_event()
