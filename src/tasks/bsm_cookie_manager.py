import asyncio
from apscheduler.triggers.interval import IntervalTrigger
from playwright.async_api import async_playwright
from ..config.settings import settings

from ..utils.logger import get_logger

logger = get_logger('bsm_cookie_manager')


class BsmCookieManager:

    def __init__(self):
        self.auth_cookie = ''
        self.cflb = ''

    def start_refresh_bsm_cookie_job(self, scheduler):
        asyncio.create_task(self.refresh_bsm_cookie_task())

        scheduler.add_job(
            self.refresh_bsm_cookie_task,
            trigger=IntervalTrigger(seconds=3600),
            id='refresh_bsm_cookie',
            name='定时刷新bsm cookie',
            replace_existing=True,
            max_instances=1,  # 确保同一时间只有一个实例运行
            misfire_grace_time=600,  # 错过触发时间的宽限期
            coalesce=True  # 合并错过的任务
        )

    async def refresh_bsm_cookie_task(self):
        logger.info("开始刷新bsm cookie")
        async with async_playwright() as p:
            browser = await p.chromium.connect(settings.playwright_browser_url)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()
            await page.goto('https://econnect.mariapps.com/', timeout=60000)

            try:
                await page.locator('input#Username:visible').fill(settings.bsm_username)
                await page.locator('input#Password').fill(settings.bsm_password)
                async with page.expect_navigation():
                    await page.locator('button', has_text='LOG IN').click()

                # 捕获跳转BSM后的新页面
                async with context.expect_page() as new_page_info:
                    await page.locator('a', has_text='BSM BSM').click()
                new_page = await new_page_info.value
                await new_page.wait_for_url("**/Dashboard")

                all_cookies = await new_page.context.cookies(urls='https://paleconnect.bs-shipmanagement.com')
                for cookie in all_cookies:
                    if cookie['name'] == '.ASPXAUTH':
                        self.auth_cookie = cookie['value']
                        logger.info(f"成功刷新bsm auth cookie {cookie['value']}")
                    if cookie['name'] == '__cflb':
                        self.cflb = cookie['value']
                        logger.info(f"成功刷新bsm cflb cookie {cookie['value']}")

            except Exception as e:
                print(f"发生错误: {e}")

            finally:
                await context.close()
                await browser.close()


bsm_cookie_manager = BsmCookieManager()
