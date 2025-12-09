import asyncio
from apscheduler.triggers.interval import IntervalTrigger
from playwright.async_api import async_playwright
from ..config.settings import settings

from ..utils.logger import get_logger

logger = get_logger('prodigy_token_manager')


class ProdigyTokenManager:

    def __init__(self):
        self.token = ''

    def start_refresh_prodigy_token_job(self, scheduler):
        asyncio.create_task(self.refresh_prodigy_token_task())

        scheduler.add_job(
            self.refresh_prodigy_token_task,
            trigger=IntervalTrigger(seconds=3600),
            id='refresh_prodigy_token',
            name='定时刷新Prodigy token',
            replace_existing=True,
            max_instances=1,  # 确保同一时间只有一个实例运行
            misfire_grace_time=600,  # 错过触发时间的宽限期
            coalesce=True  # 合并错过的任务
        )

    async def refresh_prodigy_token_task(self):
        async with async_playwright() as p:
            browser = await p.chromium.connect(settings.playwright_browser_url)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()
            await page.goto('https://vendor-portal.prodigymarinesolutions.com/en/login')

            try:
                await page.locator('input#username').fill(settings.prodigy_username)
                await page.locator('input#password').fill(settings.prodigy_password)
                async with page.expect_navigation():
                    await page.locator('button', has_text='Log in').click()
                all_cookies = await page.context.cookies()
                for cookie in all_cookies:
                    if cookie['name'] == 'user':
                        self.token = cookie['value']
                        logger.info("成功刷新Prodigy token")

            except Exception as e:
                print(f"发生错误: {e}")

            finally:
                await context.close()
                await browser.close()


prodigy_token_manager = ProdigyTokenManager()
