import json
import regex as re
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
    if not auto_forward_saler:
        return None

    # 根据物料组的特殊规则再次转换销售对象
    auto_forward_saler = reassign_saler(
        auto_forward_saler, salers, parsed_email)

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
    # 如果六位IMPA码的个数有6个及以上，认定是物料组负责的邮件，组长是Duke Wang
    if len(re.findall(r'[^a-zA-Z0-9\-\.](?<!dra?w.{0,8}|\d )\d{6}[^a-zA-Z0-9\-\.](?!\d)', text, re.IGNORECASE)) >= 6:
        return next((saler for saler in salers if saler.get("name") == "Duke Wang"), None)

    for saler in salers:
        for tag in saler['tags']:
            if not tag['pivot']['auto_forward']:
                continue
            if tag['name'].lower() in text:
                logger.debug(f"找到匹配的销售：{saler['name']}，自动转发标签：{tag['name']}")
                return saler
    return None


def reassign_saler(s, salers, email):
    # 只特殊处理 Duke Wang 的情况，其余情况原样返回
    if s["name"] != "Duke Wang":
        return s

    # 负责名单配置：姓名 -> [(字段, 关键词)]
    responsibilities = {
        "Colin Zhu": [
            ("subject", "Columbia"),
            ("subject", "OSM Maritime"),
            ("subject", "OSM Ship"),
            ("subject", "OSM tankers"),
            ("subject", "OSM bergen"),
            ("subject", "OSM THOME"),
            ("subject", "OSM offshore"),
            ("subject", "Wallem"),
            ("subject", "Thome Ship"),
            ("subject", "Berge Bulk"),
            ("subject", " Chellaram Shipping"),
        ],
        "Lorna Wang": [
            ("subject", "Anglo-eastern"),
            ("subject", "Seaspan"),
            ("subject", "Optimum"),
            ("subject", "Norbulk Shipping"),
            ("subject", "NYK Shipmanagement"),
            ("subject", "Scorpio"),
            ("subject", "Teekay"),
            ("subject", "WSM global service"),
            ("from_system", "Procure"),
        ],
    }

    # 遍历配置项进行匹配
    for name, rules in responsibilities.items():
        # 检查是否满足任一规则
        for field, keyword in rules:
            # 获取邮件对应字段的值，并进行不区分大小写的包含匹配
            email_field_value = email.get(field, "")
            if email_field_value and keyword.lower() in email_field_value.lower():
                # 从销售列表中找到匹配的名字并返回
                target_saler = next(
                    (saler for saler in salers if saler.get("name") == name), None)
                if target_saler:
                    return target_saler
                else:
                    logger.error(f"根据物料组的特殊规则进行转换，但是未找到被转换销售{name}")

    # 如果没有匹配到任何规则，返回原始销售
    return s
