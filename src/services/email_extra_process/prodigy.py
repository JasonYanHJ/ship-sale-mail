from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import requests
import json
from playwright.async_api import async_playwright
import os
from ...models.email_models import AttachmentModel
from ...utils.logger import get_logger
from ...config.settings import settings
from ...services.file_storage import file_storage
from ...tasks.prodigy_token_manager import prodigy_token_manager

logger = get_logger("extra_prodigy")

DOWNLOAD_DIR = Path(settings.attachment_path)


def getRfqUrl(rfq_number: str):
    try:
        url = "https://prodigyp2p-api.prodigymarinesolutions.com/api/RequestForQuote/GetRFQForVP"

        payload = {
            "pageNumber": 1,
            "pageSize": 25,
            "rfqNumber": rfq_number,
            "SourceTypeName": "SPMV3",
            "vendorId": "0b915a4b-f580-4220-b7a7-e201922c4758",
            "vendorLocationId": "f48244e1-ad67-4463-af96-68ea8666a1e2"
        }
        headers = {
            'accept': 'application/json',
            'authorization': f'Bearer {prodigy_token_manager.token}',
            'content-type': 'application/json',
            'locale': 'en',
            'tenant_id': '476d671c-fb81-4797-a8cd-31efb70cba60',
            'time_zone': 'IND'
        }

        rfq_list_response = requests.request(
            "POST",
            "https://prodigyp2p-api.prodigymarinesolutions.com/api/RequestForQuote/GetRFQ",
            headers=headers,
            data=json.dumps({
                "searchOptions": {"rfqNumber": rfq_number},
                "sortByColumn": "RfqDate",
                "sortByOrder": "DESC",
                "pageNumber": 1,
                "pageSize": 25
            })
        )
        rfq_list = rfq_list_response.json(
        )['dataResponse']['data']['rfq']
        rfq = next((item for item in rfq_list
                    if item.get('rfqNumber') == rfq_number), None)
        if not rfq or not rfq.get('supplyPortId'):
            raise ValueError(f"未找到Prodigy询价单的supplyPortId: {rfq_number}")

        payload['supplyPortId'] = rfq['supplyPortId']

        response = requests.request(
            "POST", url, headers=headers, data=json.dumps(payload))

        rfq_url = response.json(
        )['dataResponse']['data']['rfqVendors'][0]['pdfUrl']
        return rfq_url
    except Exception as e:
        logger.debug(f"获取prodigy rfq url失败: {e}")
        raise e


async def downloadRfqAsAttachments(rfq_number: str, rfq_url, email_uid: str, date_sent: datetime):
    async with async_playwright() as p:
        browser = await p.chromium.connect(settings.playwright_browser_url)
        context = await browser.new_context()
        context.set_default_timeout(15000)
        page = await context.new_page()
        await page.goto(rfq_url)

        attachment_models = []

        try:
            await page.locator('input[type="password"]').fill("DANMARINE-CN")
            await page.locator('button').click()

            _rfq = await page.evaluate("_rfq")
            key_of_intersts = [
                'rfqLineNo',
                'itemDescription',
                'makerRef',
                'partNo',
                'drawingNo',
                'positionNo',
                'componentName',
                'maker',
                'model',
                'componentSerialNo',
                'requestedQty',
                'requestedUOM',
                'offeredQty',
                'offeredUOM',
            ]
            extra = {
                'type': 'Prodigy',
                'version': 1,
                'meta_data': {
                    'Description': _rfq['buyerRemarks'],
                    'Buyer Remarks': _rfq['commentsToVendor']
                },
                'table_data': [
                    {k: v for k, v in d.items() if k in key_of_intersts}
                    for d in _rfq['items']
                ],
            }

            # 下载pdf并且将询价数据作为extra数据
            download_task = page.wait_for_event("download")
            await page.locator('i[title="Click to export pdf"]').click()
            download = await download_task

            filename = f"{rfq_number}.pdf"
            stored_filename = file_storage.generate_filename(
                email_uid, filename)
            sub_dir = date_sent.strftime('%Y/%m/%d')
            file_path = DOWNLOAD_DIR / sub_dir / stored_filename
            await download.save_as(file_path)

            # 创建附件模型
            attachment_models.append(AttachmentModel(
                email_id=0,  # 将在保存邮件时设置
                original_filename=filename,
                stored_filename=stored_filename,
                file_path=str(file_path),
                file_size=os.stat(file_path).st_size,
                content_type="application/pdf",
                content_disposition_type="attachment",
                extra=extra
            ))

            # 下载excel
            download_task = page.wait_for_event("download")
            await page.locator('i[title="Click to export excel"]').click()
            download = await download_task

            filename = f"{rfq_number}.xls"
            stored_filename = file_storage.generate_filename(
                email_uid, filename)
            sub_dir = date_sent.strftime('%Y/%m/%d')
            file_path = DOWNLOAD_DIR / sub_dir / stored_filename
            await download.save_as(file_path)

            # 创建附件模型
            attachment_models.append(AttachmentModel(
                email_id=0,  # 将在保存邮件时设置
                original_filename=filename,
                stored_filename=stored_filename,
                file_path=str(file_path),
                file_size=os.stat(file_path).st_size,
                content_type="application/vnd.ms-excel",
                content_disposition_type="attachment",
                extra=None
            ))

            return attachment_models

        except Exception as e:
            if await page.locator('h4', has_text="no longer available").count() > 0:
                logger.info(
                    f"{rfq_number} is no longer available. 跳过询价单下载，仅同步邮件。")
                return []
            else:
                logger.error(f"下载prodigy询价单附件出错: {e}")
                raise e

        finally:
            logger.debug("关闭浏览器")
            await context.close()
            await browser.close()


async def process_prodigy_rfq(rfq_number: str, email_uid: str, parsed_email: Dict[str, Any]):
    rfq_url = getRfqUrl(rfq_number)
    logger.debug(f"rfq url: {rfq_url}")
    return await downloadRfqAsAttachments(
        rfq_number,
        rfq_url,
        email_uid,
        parsed_email.get('date_sent')
    )
