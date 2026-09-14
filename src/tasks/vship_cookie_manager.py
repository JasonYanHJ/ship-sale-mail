import asyncio
import re

from apscheduler.triggers.interval import IntervalTrigger
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from ..config.settings import settings
from ..utils.logger import get_logger

logger = get_logger('vship_cookie_manager')

VSHIP_APP_URL = 'https://app.shipsure.com/b2b'
VSHIP_API_URL = 'https://microservices.shipsure.com/b2b'


class VshipCookieManager:

    def __init__(self):
        self.storage_state = None
        self.company_id = None
        self._refresh_lock = asyncio.Lock()

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

    async def _login(self, browser):
        context = await browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(VSHIP_APP_URL, timeout=60000)
            await page.wait_for_url(
                re.compile(
                    r'^https://msts\.v\.group/.*/Login',
                    re.I,
                ),
                timeout=30000,
            )
            await page.locator('input#username').fill(
                settings.vship_username
            )
            await page.locator('input#password').fill(
                settings.vship_password
            )

            try:
                async with page.expect_response(
                    lambda response: (
                        '/api/v1/auth/callback' in response.url
                        and response.request.method == 'POST'
                    ),
                    timeout=60000,
                ) as response_info:
                    await page.locator('button#btnloginClk').click()
                callback_response = await response_info.value
            except PlaywrightTimeoutError as e:
                body_text = await page.locator('body').inner_text()
                if 'Invalid Login credentials' in body_text:
                    raise RuntimeError(
                        'VShips登录失败: 账号或密码无效'
                    ) from e
                raise RuntimeError(
                    f'VShips OAuth回调超时: {page.url}'
                ) from e

            if not callback_response.ok:
                raise RuntimeError(
                    f'VShips OAuth回调失败: HTTP '
                    f'{callback_response.status}'
                )

            me_response = await context.request.get(
                f'{VSHIP_API_URL}/api/v1/auth/me',
                timeout=30000,
            )
            if not me_response.ok:
                raise RuntimeError(
                    f'VShips登录验证失败: HTTP {me_response.status}'
                )

            user = await me_response.json()
            company_id = user.get('companyId')
            if not company_id:
                raise RuntimeError(
                    'VShips登录验证失败: 未返回companyId'
                )

            self.storage_state = await context.storage_state()
            self.company_id = company_id
            logger.info('成功刷新VShips登录会话')
        finally:
            await context.close()

    async def _refresh_with_browser(self, browser, force: bool):
        async with self._refresh_lock:
            if not force and self.storage_state:
                return
            await self._login(browser)

    async def refresh_vship_cookie_task(self):
        logger.info('开始刷新VShips登录会话')
        async with async_playwright() as p:
            browser = await p.chromium.connect(
                settings.playwright_browser_url
            )
            try:
                await self._refresh_with_browser(browser, force=True)
            except Exception as e:
                logger.error(f'刷新VShips登录会话失败: {e}')
                raise
            finally:
                await browser.close()

    async def new_authenticated_context(self, browser):
        await self._refresh_with_browser(browser, force=False)

        context = await browser.new_context(
            storage_state=self.storage_state,
            accept_downloads=True,
        )
        response = await context.request.get(
            f'{VSHIP_API_URL}/api/v1/auth/me',
            timeout=30000,
        )
        if response.ok:
            user = await response.json()
            company_id = user.get('companyId')
            if not company_id:
                await context.close()
                raise RuntimeError(
                    'VShips登录验证失败: 未返回companyId'
                )
            self.company_id = company_id
            return context

        await context.close()
        await self._refresh_with_browser(browser, force=True)

        context = await browser.new_context(
            storage_state=self.storage_state,
            accept_downloads=True,
        )
        response = await context.request.get(
            f'{VSHIP_API_URL}/api/v1/auth/me',
            timeout=30000,
        )
        if not response.ok:
            await context.close()
            raise RuntimeError(
                f'VShips登录验证失败: HTTP {response.status}'
            )

        user = await response.json()
        company_id = user.get('companyId')
        if not company_id:
            await context.close()
            raise RuntimeError(
                'VShips登录验证失败: 未返回companyId'
            )
        self.company_id = company_id
        return context


vship_cookie_manager = VshipCookieManager()
