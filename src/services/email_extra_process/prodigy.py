from pathlib import Path
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


def getPdfUrl(rfq_number: str):
    try:
        url = "https://prodigyp2p-api.prodigymarinesolutions.com/api/RequestForQuote/GetRFQForVP"

        payload = json.dumps({
            "pageNumber": 1,
            "pageSize": 25,
            "rfqNumber": rfq_number,
            "SourceTypeName": "SPMV3",
            "vendorId": "0b915a4b-f580-4220-b7a7-e201922c4758",
            "vendorLocationId": "f48244e1-ad67-4463-af96-68ea8666a1e2"
        })
        headers = {
            'accept': 'application/json',
            'authorization': f'Bearer {prodigy_token_manager.token}',
            'content-type': 'application/json',
            'locale': 'en',
            'tenant_id': '476d671c-fb81-4797-a8cd-31efb70cba60',
            'time_zone': 'IND'
        }

        response = requests.request("POST", url, headers=headers, data=payload)

        pdf_url = response.json(
        )['dataResponse']['data']['rfqVendors'][0]['pdfUrl']
        return pdf_url
    except Exception as e:
        logger.debug(f"获取prodigy pdf url失败: {e}")
        raise e


async def downloadPdfAsAttachment(rfq_number: str, pdf_url, email_uid: str):
    async with async_playwright() as p:
        browser = await p.chromium.connect(settings.playwright_browser_url)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(pdf_url)

        try:
            await page.locator('input[type="password"]').fill("DANMARINE-CN")
            await page.locator('button').click()
            download_task = page.wait_for_event("download", timeout=10000)
            await page.locator('i[title="Click to export pdf"]').click()
            download = await download_task

            filename = f"{rfq_number}.pdf"
            stored_filename = file_storage.generate_filename(
                email_uid, filename)
            file_path = DOWNLOAD_DIR / stored_filename
            await download.save_as(file_path)

            # 创建附件模型
            attachment_model = AttachmentModel(
                email_id=0,  # 将在保存邮件时设置
                original_filename=filename,
                stored_filename=stored_filename,
                file_path=str(file_path),
                file_size=os.stat(file_path).st_size,
                content_type="application/pdf",
                content_disposition_type="attachment",
                extra=None
            )

            if file_path.exists():
                logger.debug(f"文件已成功保存为: {file_path.resolve()}")
            else:
                logger.debug("文件保存失败或路径不存在。")

            return attachment_model

        except Exception as e:
            logger.error(f"下载pdf出错: {e}")
            raise e

        finally:
            logger.debug("关闭浏览器")
            await context.close()
            await browser.close()


async def process_prodigy_pdf(rfq_number: str, email_uid: str):
    pdf_url = getPdfUrl(rfq_number)
    logger.debug(f"pdf url: {pdf_url}")
    return await downloadPdfAsAttachment(rfq_number, pdf_url, email_uid)
