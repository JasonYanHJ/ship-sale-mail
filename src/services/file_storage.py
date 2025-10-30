import os
import asyncio
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from ..config.settings import settings
from ..utils.logger import get_logger

logger = get_logger("file_storage")


class FileStorageService:
    """文件存储服务"""

    def __init__(self):
        self.attachment_path = Path(settings.attachment_path)
        self._ensure_base_dir()

    def _ensure_base_dir(self):
        """确保基础目录存在"""
        try:
            self.attachment_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"附件存储目录已准备: {self.attachment_path}")
        except Exception as e:
            logger.error(f"创建附件存储目录失败: {e}")
            raise

    def generate_filename(self, email_id: str, original_filename: str,
                          date_received: Optional[datetime] = None) -> str:
        """
        生成存储文件名: YYYYMMDDHHMM_邮件ID_UUID.扩展名
        使用UUID避免中文文件名兼容性问题

        Args:
            email_id: 邮件ID
            original_filename: 原始文件名
            date_received: 邮件接收时间，默认使用当前时间

        Returns:
            生成的存储文件名
        """
        if date_received is None:
            date_received = datetime.now()

        # 格式化时间: YYYYMMDDHHMM
        time_prefix = date_received.strftime("%Y%m%d%H%M")

        # 生成UUID确保文件名唯一性
        file_uuid = str(uuid.uuid4())

        # 提取原始文件扩展名
        _, ext = os.path.splitext(original_filename)

        # 生成最终文件名: 时间_邮件ID_UUID.扩展名
        filename = f"{time_prefix}_{email_id}_{file_uuid}{ext}"

        logger.debug(f"生成存储文件名: {filename} (原始文件名: {original_filename})")
        return filename

    async def save_attachment(self, email_id: str, filename: str, content: bytes,
                              date_received: Optional[datetime] = None) -> Dict[str, Any]:
        """
        保存附件到文件系统

        Args:
            email_id: 邮件ID
            filename: 原始文件名
            content: 文件内容
            date_received: 邮件接收时间

        Returns:
            文件信息字典，包含存储路径、文件大小等信息
        """
        try:
            # 生成存储文件名
            stored_filename = self.generate_filename(
                email_id, filename, date_received)
            file_path = self.attachment_path / stored_filename

            # 异步写入文件
            await self._write_file_async(file_path, content)

            # 构建返回信息
            file_info = {
                'original_filename': filename,
                'stored_filename': stored_filename,
                'file_path': str(file_path),
                'file_size': len(content),
                'created_at': datetime.now()
            }

            logger.debug(f"附件保存成功: {stored_filename} ({len(content)} bytes)")
            return file_info

        except Exception as e:
            logger.error(f"保存附件失败 {filename}: {e}")
            raise

    async def _write_file_async(self, file_path: Path, content: bytes):
        """异步写入文件"""
        def write_file():
            with open(file_path, 'wb') as f:
                f.write(content)

        # 在线程池中执行文件写入
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, write_file)

    async def delete_attachment(self, file_path: str) -> bool:
        """
        删除附件文件

        Args:
            file_path: 文件路径

        Returns:
            删除是否成功
        """
        try:
            path = Path(file_path)
            if path.exists():
                def delete_file():
                    path.unlink()

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, delete_file)
                logger.info(f"附件删除成功: {file_path}")
                return True
            else:
                logger.warning(f"附件文件不存在: {file_path}")
                return False

        except Exception as e:
            logger.error(f"删除附件失败 {file_path}: {e}")
            return False

    def get_file_info(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        获取文件信息

        Args:
            file_path: 文件路径

        Returns:
            文件信息字典，如果文件不存在返回None
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return None

            stat = path.stat()
            return {
                'file_path': str(path),
                'file_size': stat.st_size,
                'created_at': datetime.fromtimestamp(stat.st_ctime),
                'modified_at': datetime.fromtimestamp(stat.st_mtime),
                'exists': True
            }

        except Exception as e:
            logger.error(f"获取文件信息失败 {file_path}: {e}")
            return None

    async def read_attachment(self, file_path: str) -> Optional[bytes]:
        """
        读取附件内容

        Args:
            file_path: 文件路径

        Returns:
            文件内容，如果文件不存在返回None
        """
        try:
            path = Path(file_path)
            if not path.exists():
                logger.warning(f"附件文件不存在: {file_path}")
                return None

            def read_file():
                with open(path, 'rb') as f:
                    return f.read()

            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(None, read_file)

            logger.debug(f"附件读取成功: {file_path} ({len(content)} bytes)")
            return content

        except Exception as e:
            logger.error(f"读取附件失败 {file_path}: {e}")
            return None

    def cleanup_old_files(self, days: int = 30) -> int:
        """
        清理旧文件

        Args:
            days: 保留天数，超过此天数的文件将被删除

        Returns:
            删除的文件数量
        """
        try:
            deleted_count = 0
            cutoff_time = datetime.now().timestamp() - (days * 24 * 3600)

            for file_path in self.attachment_path.iterdir():
                if file_path.is_file():
                    if file_path.stat().st_mtime < cutoff_time:
                        try:
                            file_path.unlink()
                            deleted_count += 1
                            logger.debug(f"删除旧文件: {file_path}")
                        except Exception as e:
                            logger.error(f"删除文件失败 {file_path}: {e}")

            logger.info(f"清理完成，删除了 {deleted_count} 个旧文件")
            return deleted_count

        except Exception as e:
            logger.error(f"清理旧文件时出错: {e}")
            return 0


# 全局文件存储服务实例
file_storage = FileStorageService()
