from typing import List, Dict, Optional, Tuple
import ssl
from imapclient import IMAPClient
from email.message import Message
from ..config.settings import settings
from ..utils.logger import logger


class EmailReader:
    """邮件读取服务 - 专注于IMAP操作"""

    def __init__(self):
        self.client: Optional[IMAPClient] = None
        self.connected = False

    def connect(self) -> bool:
        """连接到IMAP服务器"""
        try:
            # 创建SSL上下文
            ssl_context = ssl.create_default_context()

            # 连接到IMAP服务器
            self.client = IMAPClient(
                host=settings.imap_server,
                port=settings.imap_port,
                ssl=True,
                ssl_context=ssl_context
            )

            # 登录
            self.client.login(settings.email_username, settings.email_password)
            self.connected = True

            # 对于163邮箱，发送ID命令以通过安全验证
            if "163.com" in settings.imap_server:
                try:
                    self.client.id_({"name": "IMAPClient", "version": "2.1.0"})
                except Exception as e:
                    logger.warning(f"IMAP ID命令失败，将重新连接并跳过ID命令: {e}")
                    try:
                        self.client.shutdown()
                    except Exception:
                        pass

                    self.client = IMAPClient(
                        host=settings.imap_server,
                        port=settings.imap_port,
                        ssl=True,
                        ssl_context=ssl_context
                    )
                    self.client.login(
                        settings.email_username, settings.email_password)

            logger.info(f"成功连接到IMAP服务器: {settings.imap_server}")
            return True

        except Exception as e:
            logger.error(f"IMAP连接失败: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """断开IMAP连接"""
        if self.client and self.connected:
            try:
                self.client.logout()
                logger.info("IMAP连接已断开")
            except Exception as e:
                logger.error(f"断开IMAP连接时出错: {e}")
            finally:
                self.client = None
                self.connected = False

    def get_folders(self) -> List[str]:
        """获取所有邮箱文件夹"""
        if not self.connected or not self.client:
            raise Exception("未连接到IMAP服务器")

        try:
            folders = self.client.list_folders()
            folder_names = [folder[2] for folder in folders]
            logger.info(f"获取到邮箱文件夹: {folder_names}")
            return folder_names
        except Exception as e:
            logger.error(f"获取邮箱文件夹失败: {e}")
            raise

    def select_folder(self, folder_name: str = "INBOX") -> Dict:
        """选择邮箱文件夹"""
        if not self.connected or not self.client:
            raise Exception("未连接到IMAP服务器")

        try:
            folder_info = self.client.select_folder(folder_name)
            logger.info(
                f"选择文件夹 '{folder_name}' 成功，邮件数量: {folder_info[b'EXISTS']}")
            return folder_info
        except Exception as e:
            logger.error(f"选择文件夹 '{folder_name}' 失败: {e}")
            raise

    def search_emails(self, criteria: List[str] = None, limit: int = None) -> List[int]:
        """搜索邮件"""
        if not self.connected or not self.client:
            raise Exception("未连接到IMAP服务器")

        try:
            # 默认搜索所有邮件
            if criteria is None:
                criteria = ['ALL']

            message_ids = self.client.search(criteria)

            # 限制返回数量，获取最新的邮件
            if limit and len(message_ids) > limit:
                message_ids = message_ids[-limit:]

            logger.info(f"搜索到 {len(message_ids)} 封邮件")
            return message_ids

        except Exception as e:
            logger.error(f"搜索邮件失败: {e}")
            raise

    def fetch_raw_email(self, message_id: int) -> Tuple[Dict, bytes]:
        """获取邮件原始数据"""
        if not self.connected or not self.client:
            raise Exception("未连接到IMAP服务器")

        try:
            # 获取邮件数据
            response = self.client.fetch([message_id], ['RFC822', 'FLAGS'])

            if message_id not in response:
                raise Exception(f"无法获取邮件 ID: {message_id}")

            email_data = response[message_id]
            raw_email = email_data[b'RFC822']
            flags = email_data[b'FLAGS']

            logger.debug(f"获取邮件 {message_id} 原始数据成功")
            return {
                'flags': flags,
                'imap_id': message_id
            }, raw_email

        except Exception as e:
            logger.error(f"获取邮件 {message_id} 失败: {e}")
            raise

    def get_email_flags(self, message_id: int) -> List:
        """获取邮件标志"""
        if not self.connected or not self.client:
            raise Exception("未连接到IMAP服务器")

        try:
            response = self.client.fetch([message_id], ['FLAGS'])
            if message_id in response:
                return response[message_id][b'FLAGS']
            return []
        except Exception as e:
            logger.error(f"获取邮件 {message_id} 标志失败: {e}")
            return []

    def mark_as_unflagged(self, message_id: int) -> bool:
        """标记邮件为已读"""
        if not self.connected or not self.client:
            raise Exception("未连接到IMAP服务器")

        try:
            self.client.remove_flags([message_id], ['\\FLAGGED'])
            logger.debug(f"邮件 {message_id} 已标记为已读")
            return True
        except Exception as e:
            logger.error(f"标记邮件 {message_id} 为已读失败: {e}")
            return False

    def __enter__(self):
        """上下文管理器入口"""
        if not self.connect():
            raise Exception("无法连接到IMAP服务器")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.disconnect()

    async def __aenter__(self):
        """异步上下文管理器入口"""
        if not self.connect():
            raise Exception("无法连接到IMAP服务器")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        self.disconnect()


# 全局邮件读取器实例
email_reader = EmailReader()
