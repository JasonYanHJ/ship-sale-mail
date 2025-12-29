import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
import requests
from playwright.async_api import async_playwright
import os
from ...models.email_models import AttachmentModel
from ...utils.logger import get_logger
from ...config.settings import settings
from ...services.file_storage import file_storage
from ...tasks.vship_cookie_manager import vship_cookie_manager

logger = get_logger("extra_vship")

DOWNLOAD_DIR = Path(settings.attachment_path)


def getRfq(rfq_number: str):
    try:
        url = "https://b2b.shipsure.com/QuoteList/LoadQuotes"

        payload = f"take=1000&skip=0&page=1&pageSize=1000&filter%5Blogic%5D=and&filter%5Bfilters%5D%5B0%5D%5Bfield%5D=ORD_OrderNo&filter%5Bfilters%5D%5B0%5D%5Boperator%5D=eq&filter%5Bfilters%5D%5B0%5D%5Bvalue%5D={rfq_number}"
        headers = {
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Cookie': f'stickysession_b2b={vship_cookie_manager.cookie_sticky}; b2b={vship_cookie_manager.cookie_b2b}; ASP.NET_SessionId={vship_cookie_manager.cookie_session_id}'
        }

        response = requests.request("POST", url, headers=headers, data=payload)

        rfq_rsp_id = response.json(
        )['quotes'][0]['RSP_ID']
        return rfq_rsp_id
    except Exception as e:
        logger.debug(f"vship rfq 获取失败: {e}")
        raise e


async def getRfqExtraData(page, rfq_url: str):
    extra_data = {
        'meta_data': None,
        'table_data': None,
    }

    async def wait_for_meta_data():
        async with page.expect_response(lambda r: "/QuoteList/LoadCompLines?rsp_id" in r.url) as resp_info:
            response = await resp_info.value
            meta_data = (await response.json())['Data'][0]
            extra_data['meta_data'] = {
                'Title': (await page.locator('.quoteHeaderTopRow b').inner_text())[13:],
                'For Component': meta_data['CompName'],
                'Maker': meta_data['CompManuf'],
                'Serial No.': meta_data['CompSerial'],
                'Component Notes': meta_data['CompNotes'],
                'Notes': (await page.locator('.quoteOrdNotes').inner_text()).replace('\xa0', ' '),
            }
            return

    async def wait_for_table_data():
        async with page.expect_response(lambda r: "/QuoteList/LoadQuoteLines?PRTID" in r.url) as resp_info:
            response = await resp_info.value
            table_data = (await response.json())['Data']
            target_keys = ["RodLineNo", "Enquired", "UnitType", "PartName",
                           "MakersRef", "DrawingPos", "SparePartNotes"]
            extra_data['table_data'] = [
                {k: d[k] for k in target_keys if k in d} for d in table_data]
            return

    task1 = asyncio.create_task(wait_for_meta_data())
    task2 = asyncio.create_task(wait_for_table_data())

    await page.goto(rfq_url)

    await asyncio.gather(task1, task2)

    return extra_data


async def downloadRfqAsAttachments(rfq_number: str, rfq_url, email_uid: str, date_sent: datetime):
    async with async_playwright() as p:
        browser = await p.chromium.connect(settings.playwright_browser_url)
        context = await browser.new_context()
        context.set_default_timeout(15000)
        await context.add_cookies(vship_cookie_manager.cookies)
        page = await context.new_page()

        # 前往询价单页面，并通过监听请求的响应获取rfq数据
        extra_data = await getRfqExtraData(page, rfq_url)

        attachment_models = []

        try:
            # 下载pdf询价单
            download_task = page.wait_for_event("download")
            await page.locator('a#printout').click(no_wait_after=True)
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
                extra={
                    'type': 'Vship',
                    'version': 1,
                    **extra_data
                }
            ))

            return attachment_models

        except Exception as e:
            logger.error(f"下载vship询价单附件出错: {e}")
            raise e

        finally:
            logger.debug("关闭浏览器")
            await context.close()
            await browser.close()


async def process_vship_rfq(rfq_number: str, email_uid: str, parsed_email: Dict[str, Any]):
    rfq_rsp_id = getRfq(rfq_number)
    logger.debug(f"rfq rsp_id: {rfq_rsp_id}")
    return await downloadRfqAsAttachments(
        rfq_number,
        f'https://b2b.shipsure.com/QuoteList/GetDetailsPage?id={rfq_rsp_id}&sId=GLAS00058396',
        email_uid,
        parsed_email.get('date_sent')
    )
