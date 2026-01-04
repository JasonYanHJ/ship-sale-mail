import asyncio
from apscheduler.triggers.interval import IntervalTrigger
from playwright.async_api import async_playwright
from ..config.settings import settings

from ..utils.logger import get_logger

logger = get_logger('vship_cookie_manager')


class VshipCookieManager:

    def __init__(self):
        self.cookies = {
            'b2b': '',
            'session_id': '',
            'sticky': '',
        }

    def start_refresh_vship_cookie_job(self, scheduler):
        asyncio.create_task(self.refresh_vship_cookie_task())

        scheduler.add_job(
            self.refresh_vship_cookie_task,
            trigger=IntervalTrigger(seconds=3600),
            id='refresh_vship_cookie',
            name='定时刷新Vship cookie',
            replace_existing=True,
            max_instances=1,  # 确保同一时间只有一个实例运行
            misfire_grace_time=600,  # 错过触发时间的宽限期
            coalesce=True  # 合并错过的任务
        )

    async def refresh_vship_cookie_task(self):
        logger.info("开始刷新Vship cookie")
        async with async_playwright() as p:
            browser = await p.chromium.connect(settings.playwright_browser_url)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()
            await page.goto('https://b2b.shipsure.com/', timeout=60000)

            try:
                await page.locator('input#username').fill(settings.vship_username)
                await page.locator('input#password').fill(settings.vship_password)
                async with page.expect_navigation():
                    await page.locator('button#btnloginClk').click()
                all_cookies = await page.context.cookies(urls='https://b2b.shipsure.com')
                for cookie in all_cookies:
                    if cookie['name'] == 'b2b':
                        self.cookies['b2b'] = cookie
                        logger.info(f"成功刷新Vship b2b cookie {cookie['value']}")
                    if cookie['name'] == 'ASP.NET_SessionId':
                        self.cookies['session_id'] = cookie
                        logger.info(
                            f"成功刷新Vship session_id cookie {cookie['value']}")
                    if cookie['name'] == 'stickysession_b2b':
                        self.cookies['sticky'] = cookie
                        logger.info(
                            f"成功刷新Vship sticky cookie {cookie['value']}")

            except Exception as e:
                print(f"发生错误: {e}")

            finally:
                await context.close()
                await browser.close()


vship_cookie_manager = VshipCookieManager()
