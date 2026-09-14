from datetime import datetime
import os
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote

from playwright.async_api import async_playwright

from ...config.settings import settings
from ...models.email_models import AttachmentModel
from ...services.file_storage import file_storage
from ...tasks.vship_cookie_manager import (
    VSHIP_API_URL,
    VSHIP_APP_URL,
    vship_cookie_manager,
)
from ...utils.logger import get_logger

logger = get_logger("extra_vship")

DOWNLOAD_DIR = Path(settings.attachment_path)


async def _get_json(response, action: str):
    if not response.ok:
        raise RuntimeError(f'{action}失败: HTTP {response.status}')
    return await response.json()


async def getRfq(context, rfq_number: str):
    response = await context.request.post(
        f'{VSHIP_API_URL}/api/v1/quotes/list',
        data={
            'supplierId': vship_cookie_manager.company_id,
            'sortField': 'RSP_DateEnqSent',
            'sortDir': 'desc',
        },
        timeout=60000,
    )
    data = await _get_json(response, '获取VShips询价单列表')
    quotes = data.get('quotes')
    if not isinstance(quotes, list):
        raise RuntimeError(
            '获取VShips询价单列表失败: quotes格式错误'
        )

    rfq = next(
        (item for item in quotes if item.get('orderNo') == rfq_number),
        None,
    )
    if not rfq or not rfq.get('rspId'):
        raise RuntimeError(f'未找到VShips询价单: {rfq_number}')

    return rfq


async def getRfqExtraData(page, rfq: Dict[str, Any]):
    rfq_rsp_id = rfq['rspId']
    rfq_url = (
        f'{VSHIP_APP_URL}/quotes/{rfq_rsp_id}'
        f'?sId={vship_cookie_manager.company_id}'
        f'&stage={quote(rfq.get("stage") or "")}'
    )
    async with page.expect_response(
        lambda response: (
            response.url.partition('?')[0].endswith(
                f'/api/v1/quotes/{rfq_rsp_id}'
            )
            and response.request.method == 'GET'
        ),
        timeout=60000,
    ) as response_info:
        await page.goto(rfq_url, timeout=60000)
    response = await response_info.value
    detail = await _get_json(response, '获取VShips询价单详情')
    lines = detail.get('lines')
    if not isinstance(lines, list):
        raise RuntimeError(
            '获取VShips询价单详情失败: lines格式错误'
        )

    first_line = lines[0] if lines else {}
    key_mapping = {
        'RodLineNo': 'rodLineNo',
        'Enquired': 'enquired',
        'UnitType': 'unitType',
        'PartName': 'partName',
        'MakersRef': 'makersRef',
        'DrawingPos': 'drawingPos',
        'SparePartNotes': 'sparePartNotes',
    }
    extra_data = {
        'meta_data': {
            'Title': detail.get('orderName'),
            'For Component': first_line.get('compName'),
            'Maker': first_line.get('compManuf'),
            'Serial No.': first_line.get('compSerial'),
            'Component Notes': first_line.get('compNotes'),
            'Notes': detail.get('orderNotes'),
        },
        'table_data': [
            {
                old_key: line.get(new_key)
                for old_key, new_key in key_mapping.items()
            }
            for line in lines
        ],
    }
    return extra_data


async def downloadRfqAsAttachments(
    rfq_number: str,
    email_uid: str,
    date_sent: datetime,
):
    async with async_playwright() as p:
        browser = await p.chromium.connect(
            settings.playwright_browser_url
        )
        context = None

        try:
            context = (
                await vship_cookie_manager.new_authenticated_context(
                    browser
                )
            )
            rfq = await getRfq(context, rfq_number)
            logger.debug(f'rfq rsp_id: {rfq["rspId"]}')

            page = await context.new_page()
            extra_data = await getRfqExtraData(page, rfq)
            await page.locator(
                '[data-testid="quote-print-button"]'
            ).wait_for(state='visible', timeout=60000)

            filename = f'{rfq_number}.pdf'
            stored_filename = file_storage.generate_filename(
                email_uid,
                filename,
                date_sent,
            )
            sub_dir = date_sent.strftime('%Y/%m/%d')
            file_path = DOWNLOAD_DIR / sub_dir / stored_filename
            file_path.parent.mkdir(parents=True, exist_ok=True)

            async with page.expect_download(timeout=60000) as download_info:
                await page.locator(
                    '[data-testid="quote-print-button"]'
                ).click()
            download = await download_info.value
            await download.save_as(file_path)

            return [AttachmentModel(
                email_id=0,  # 将在保存邮件时设置
                original_filename=filename,
                stored_filename=stored_filename,
                file_path=str(file_path),
                file_size=os.stat(file_path).st_size,
                content_type='application/pdf',
                content_disposition_type='attachment',
                extra={
                    'type': 'Vship',
                    'version': 1,
                    **extra_data,
                },
            )]
        except Exception as e:
            logger.error(f'下载VShips询价单附件出错: {e}')
            raise
        finally:
            if context:
                await context.close()
            await browser.close()


async def process_vship_rfq(
    rfq_number: str,
    email_uid: str,
    parsed_email: Dict[str, Any],
):
    return await downloadRfqAsAttachments(
        rfq_number,
        email_uid,
        parsed_email.get('date_sent'),
    )
