from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from src.repositories.settings.json import SettingsRepository
from src.services.sessions import SessionError


# 官方文档核对日期：2026-09-05。这里只列文生图模型，编辑图片的模型不能直接使用。
IMAGE_PRESETS = [
    {"id": "openai", "label": "OpenAI GPT Image", "api_base": "https://api.openai.com/v1", "models": ["gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini"], "docs": "https://developers.openai.com/api/docs/guides/image-generation"},
    {"id": "gemini", "label": "Google Gemini", "api_base": "https://generativelanguage.googleapis.com/v1beta", "models": ["gemini-3.1-flash-image", "gemini-3-pro-image", "gemini-3.1-flash-lite-image", "gemini-2.5-flash-image"], "docs": "https://ai.google.dev/gemini-api/docs/generate-content/image-generation"},
    {"id": "siliconflow", "label": "硅基流动", "api_base": "https://api.siliconflow.cn/v1", "models": ["Qwen/Qwen-Image", "Kwai-Kolors/Kolors"], "docs": "https://api-docs.siliconflow.cn/docs/api/images-generations-post"},
    {"id": "openai_compat", "label": "自定义 OpenAI Images 兼容接口", "api_base": "", "models": [], "docs": "https://developers.openai.com/api/docs/guides/image-generation"},
]


def image_settings_payload(repo: SettingsRepository) -> dict[str, Any]:
    """网页只读取密钥是否已保存，不返回密钥本身。"""
    config = repo.load().get("image_generation") or {}
    return {"config": {key: str(config.get(key) or "") for key in ("backend", "api_base", "model", "language")}, "configured": bool(config.get("api_key") and config.get("model") and config.get("api_base")), "presets": IMAGE_PRESETS}


def save_image_settings(repo: SettingsRepository, patch: dict[str, Any]) -> dict[str, Any]:
    """生图配置独立保存；更换服务或地址时必须填写该服务的密钥。"""
    data = repo.load()
    previous = data.get("image_generation") or {}
    config = {key: str(patch.get(key) or "").strip() for key in ("backend", "api_base", "model", "language", "api_key")}
    config["api_base"] = config["api_base"].rstrip("/")
    if config["backend"] not in {item["id"] for item in IMAGE_PRESETS}:
        raise SessionError("请选择支持的生图服务。", 400)
    parsed = urlparse(config["api_base"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SessionError("请填写有效的 API 基础地址，不要在地址中放密钥或查询参数。", 400)
    same_service = all(config[key] == previous.get(key) for key in ("backend", "api_base"))
    if not config["api_key"] and same_service:
        config["api_key"] = previous.get("api_key", "")
    if not config["api_key"] or not config["model"]:
        raise SessionError("请填写生图模型名称和 API Key。", 400)
    config["language"] = config["language"] or "中文"
    data["image_generation"] = config
    repo.save(data)
    return image_settings_payload(repo)


def image_config(repo: SettingsRepository) -> dict[str, Any]:
    """在调用文字模型前检查生图配置，缺配置时不消耗模型请求。"""
    config = dict(repo.load().get("image_generation") or {})
    if not all(config.get(key) for key in ("backend", "api_base", "api_key", "model")):
        raise SessionError("请先到设置页配置“一图总结”的生图服务、模型和 API Key。", 400)
    return config


async def generate_image(config: dict[str, Any], prompt: str) -> tuple[bytes, str]:
    """按服务发送一次生图请求，并立即取回图片；不自动重试，避免重复计费。"""
    backend, model = config["backend"], config["model"]
    base = config["api_base"].rstrip("/")
    headers = {"Authorization": f"Bearer {config['api_key']}"}
    body: dict[str, Any] = {"model": model, "prompt": prompt, "n": 1}
    url = base + "/images/generations"
    if backend == "gemini":
        url = base + "/models/" + quote(model.removeprefix("models/"), safe="") + ":generateContent"
        headers = {"x-goog-api-key": config["api_key"]}
        body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
    elif backend == "siliconflow":
        body = {"model": model, "prompt": prompt, "image_size": "1024x1024" if "Kolors" in model else "1664x928"}
        if model == "Qwen/Qwen-Image":
            # 官方文档建议较高步数和 cfg，帮助海报里的中文更清楚。
            body.update(num_inference_steps=50, cfg=4.0)
    elif backend == "openai":
        body["size"] = "1536x1024"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20)) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            payload = response.json()
            if backend == "gemini":
                for candidate in payload.get("candidates", []):
                    for part in candidate.get("content", {}).get("parts", []):
                        inline = part.get("inlineData") or part.get("inline_data") or {}
                        if inline.get("data") and not part.get("thought"):
                            return _check_image(base64.b64decode(inline["data"], validate=True))
            else:
                items = payload.get("images" if backend == "siliconflow" else "data") or []
                if items:
                    item = items[0]
                    if item.get("b64_json"):
                        return _check_image(base64.b64decode(item["b64_json"], validate=True))
                    if item.get("url"):
                        image_url = str(item["url"])
                        if urlparse(image_url).scheme not in {"http", "https"}:
                            raise ValueError("图片地址不是 HTTP 地址")
                        # 图片下载不携带生图密钥，防止密钥被发送给文件存储服务。
                        image_response = await client.get(image_url, follow_redirects=True)
                        image_response.raise_for_status()
                        return _check_image(image_response.content)
    except httpx.HTTPStatusError as exc:
        raise SessionError(f"生图服务请求失败（HTTP {exc.response.status_code}），请核对服务地址、密钥、模型权限和额度。", 502) from None
    except (httpx.RequestError, ValueError, KeyError, TypeError) as exc:
        # 不把远端响应或请求地址直接返回页面，避免服务把密钥回显到错误中。
        raise SessionError("生图请求超时、连接失败或图片格式无效，请检查配置后重试。", 502) from None
    raise SessionError("生图服务没有返回图片，可能被服务拒绝，或所选模型不支持图片生成。", 502)


def _check_image(content: bytes) -> tuple[bytes, str]:
    """按文件开头识别真实图片格式，拒绝把错误网页当作图片保存。"""
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return content, "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return content, "image/jpeg"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return content, "image/webp"
    raise ValueError("服务没有返回 PNG、JPEG 或 WebP 图片")
