import json
from typing import Any, Dict, List

from ..models.email_models import AttachmentModel
from ..utils.logger import get_logger
from ..config.settings import settings
import httpx
from httpx import HTTPStatusError, RequestError

logger = get_logger("rfq_auto_forward")


async def process_rfq_auto_forward(email_id: int, parsed_email: Dict[str, Any], attachment_models: List[AttachmentModel]):
    # 只处理询价邮件
    if parsed_email.get('type') != 'RFQ':
        return
    # 目前只处理解析过的系统的询价邮件
    if not parsed_email.get('from_system') in ['ShipServ', 'Procure', 'Prodigy', 'Vship', 'BSM']:
        return

    extra_text = get_extra_text(attachment_models)
    if not extra_text:
        return None

    salers = (await fetch_salers_data())['data']

    auto_forward_saler = get_auto_forward_saler(salers, extra_text)
    return auto_forward_saler


def get_extra_text(attachment_models: List[AttachmentModel]):
    # 1. 过滤出有 extra 字段的附件
    attachments_with_extra = [
        att for att in attachment_models if att.extra]

    parts = []
    for attr in attachments_with_extra:
        extra = attr.extra
        meta_data = extra.get('meta_data', {})
        table_data = extra.get('table_data', [])
        extra_type = extra.get('type')

        # 2. 处理特定的 table_data 逻辑 (Prodigy/Vship/BSM 仅取 values)
        if extra_type in ["Prodigy", "Vship", "BSM"]:
            processed_table = [list(d.values()) for d in table_data]
        else:
            processed_table = table_data

        # 3. 序列化并拼接
        combined_json_str = json.dumps(meta_data, separators=(',', ':')) + \
            json.dumps(processed_table, separators=(',', ':'))

        # 4. 替换换行符
        cleaned_text = combined_json_str.replace('\\n', ' ')
        parts.append(cleaned_text)

    # 5. 合并并转为小写
    return ",".join(parts).lower()


async def fetch_salers_data():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{settings.laravel_url}/api/internal/salers",
                headers={'accept': 'text/json'},
                timeout=5.0  # 建议设置超时，防止被 Laravel 拖死
            )

            # 如果状态码不是 2xx，将抛出 httpx.HTTPStatusError
            response.raise_for_status()

            return response.json()

        except HTTPStatusError as exc:
            # 响应错误（例如 404, 500 等）
            logger.error(
                f"请求失败，状态码: {exc.response.status_code}，原因: {exc.response.text}")
            raise
        except RequestError as exc:
            # 网络错误（例如 DNS 解析失败、连接拒绝等）
            logger.error(f"网络连接异常: {exc}")
            raise


def get_auto_forward_saler(salers: List[Dict[str, Any]], text: str):
    for saler in salers:
        for tag in saler['tags']:
            if not tag['pivot']['auto_forward']:
                continue
            if tag['name'] in text:
                logger.debug(f"找到匹配的销售：{saler['name']}，自动转发标签：{tag['name']}")
                return saler
    return None
