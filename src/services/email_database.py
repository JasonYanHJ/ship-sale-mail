from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
import aiomysql

from ..models.database import db_manager
from ..models.email_models import EmailModel, AttachmentModel, EmailSyncStats, EmailForward
from ..utils.logger import get_logger

logger = get_logger("email_database")


class EmailDatabaseService:
    """邮件数据库服务"""

    def __init__(self):
        self.db_manager = db_manager

    async def save_email(self, email: EmailModel) -> int:
        """
        保存邮件到数据库

        Args:
            email: 邮件模型

        Returns:
            保存的邮件ID
        """
        try:
            async with self.db_manager.get_transaction() as conn:
                async with conn.cursor() as cursor:
                    # 检查邮件是否已存在（基于message_id去重）
                    check_sql = "SELECT id FROM emails WHERE message_id = %s"
                    await cursor.execute(check_sql, (email.message_id,))
                    existing = await cursor.fetchone()

                    if existing:
                        logger.debug(f"邮件已存在，跳过: {email.message_id}")
                        return existing[0]

                    # 插入新邮件
                    data = email.to_db_dict()
                    columns = ', '.join(data.keys())
                    placeholders = ', '.join(['%s'] * len(data))

                    insert_sql = f"""
                        INSERT INTO emails ({columns}) 
                        VALUES ({placeholders})
                    """

                    await cursor.execute(insert_sql, list(data.values()))
                    email_id = cursor.lastrowid

                    logger.debug(
                        f"邮件保存成功: ID={email_id}, message_id={email.message_id}")
                    return email_id

        except Exception as e:
            logger.error(f"保存邮件失败: {e}")
            raise

    async def save_attachment(self, attachment: AttachmentModel) -> int:
        """
        保存附件信息到数据库

        Args:
            attachment: 附件模型

        Returns:
            保存的附件ID
        """
        try:
            async with self.db_manager.get_transaction() as conn:
                async with conn.cursor() as cursor:
                    data = attachment.to_db_dict()
                    columns = ', '.join(data.keys())
                    placeholders = ', '.join(['%s'] * len(data))

                    insert_sql = f"""
                        INSERT INTO attachments ({columns}) 
                        VALUES ({placeholders})
                    """

                    await cursor.execute(insert_sql, list(data.values()))
                    attachment_id = cursor.lastrowid

                    logger.debug(
                        f"附件信息保存成功: ID={attachment_id}, 文件={attachment.original_filename}")
                    return attachment_id

        except Exception as e:
            logger.error(f"保存附件信息失败: {e}")
            raise

    async def save_email_with_attachments(self, email: EmailModel,
                                          attachments: List[AttachmentModel]) -> Tuple[int, List[int]]:
        """
        保存邮件及其附件信息（事务性操作）

        Args:
            email: 邮件模型
            attachments: 附件模型列表

        Returns:
            (邮件ID, 附件ID列表)
        """
        try:
            async with self.db_manager.get_transaction() as conn:
                async with conn.cursor() as cursor:
                    # 1. 保存邮件
                    # 检查邮件是否已存在
                    check_sql = "SELECT id FROM emails WHERE message_id = %s"
                    await cursor.execute(check_sql, (email.message_id,))
                    existing = await cursor.fetchone()

                    if existing:
                        email_id = existing[0]
                        logger.debug(
                            f"邮件已存在: ID={email_id}, message_id={email.message_id}")

                        # 检查是否已有附件记录
                        attach_check_sql = "SELECT COUNT(*) FROM attachments WHERE email_id = %s"
                        await cursor.execute(attach_check_sql, (email_id,))
                        existing_attach_count = (await cursor.fetchone())[0]

                        if existing_attach_count > 0:
                            logger.debug(f"邮件附件已存在，跳过: email_id={email_id}")
                            return email_id, []
                    else:
                        # 插入新邮件
                        email_data = email.to_db_dict()
                        columns = ', '.join(email_data.keys())
                        placeholders = ', '.join(['%s'] * len(email_data))

                        insert_sql = f"""
                            INSERT INTO emails ({columns}) 
                            VALUES ({placeholders})
                        """

                        await cursor.execute(insert_sql, list(email_data.values()))
                        email_id = cursor.lastrowid
                        logger.debug(f"邮件保存成功: ID={email_id}")

                    # 2. 保存附件信息
                    attachment_ids = []
                    for attachment in attachments:
                        attachment.email_id = email_id

                        attach_data = attachment.to_db_dict()
                        columns = ', '.join(attach_data.keys())
                        placeholders = ', '.join(['%s'] * len(attach_data))

                        attach_sql = f"""
                            INSERT INTO attachments ({columns}) 
                            VALUES ({placeholders})
                        """

                        await cursor.execute(attach_sql, list(attach_data.values()))
                        attachment_id = cursor.lastrowid
                        attachment_ids.append(attachment_id)

                    logger.info(
                        f"邮件及附件保存完成: email_id={email_id}, 附件数={len(attachment_ids)}")
                    return email_id, attachment_ids

        except Exception as e:
            logger.error(f"保存邮件及附件失败: {e}")
            raise

    async def get_email_by_id(self, email_id: int) -> Optional[EmailModel]:
        """
        根据ID获取邮件

        Args:
            email_id: 邮件ID

        Returns:
            邮件模型，如果不存在返回None
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    sql = "SELECT * FROM emails WHERE id = %s"
                    await cursor.execute(sql, (email_id,))
                    result = await cursor.fetchone()

                    if result:
                        return EmailModel.from_db_dict(result)
                    return None

        except Exception as e:
            logger.error(f"获取邮件失败: {e}")
            raise

    async def get_email_by_message_id(self, message_id: str) -> Optional[EmailModel]:
        """
        根据message_id获取邮件

        Args:
            message_id: 邮件message_id

        Returns:
            邮件模型，如果不存在返回None
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    sql = "SELECT * FROM emails WHERE message_id = %s"
                    await cursor.execute(sql, (message_id,))
                    result = await cursor.fetchone()

                    if result:
                        return EmailModel.from_db_dict(result)
                    return None

        except Exception as e:
            logger.error(f"根据message_id获取邮件失败: {e}")
            raise

    async def get_attachments_by_email_id(self, email_id: int) -> List[AttachmentModel]:
        """
        获取邮件的所有附件

        Args:
            email_id: 邮件ID

        Returns:
            附件模型列表
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    sql = "SELECT * FROM attachments WHERE email_id = %s ORDER BY id"
                    await cursor.execute(sql, (email_id,))
                    results = await cursor.fetchall()

                    return [AttachmentModel.from_db_dict(row) for row in results]

        except Exception as e:
            logger.error(f"获取邮件附件失败: {e}")
            raise

    async def get_emails_list(self, limit: int = 50, offset: int = 0,
                              sender: Optional[str] = None) -> Tuple[List[EmailModel], int]:
        """
        获取邮件列表

        Args:
            limit: 限制数量
            offset: 偏移量
            sender: 发送者过滤（可选）

        Returns:
            (邮件列表, 总数)
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 构建查询条件
                    where_clause = ""
                    params = []

                    if sender:
                        where_clause = "WHERE sender LIKE %s"
                        params.append(f"%{sender}%")

                    # 获取总数
                    count_sql = f"SELECT COUNT(*) as total FROM emails {where_clause}"
                    await cursor.execute(count_sql, params)
                    total = (await cursor.fetchone())['total']

                    # 获取邮件列表
                    list_sql = f"""
                        SELECT * FROM emails {where_clause} 
                        ORDER BY date_received DESC 
                        LIMIT %s OFFSET %s
                    """
                    params.extend([limit, offset])
                    await cursor.execute(list_sql, params)
                    results = await cursor.fetchall()

                    emails = [EmailModel.from_db_dict(row) for row in results]
                    return emails, total

        except Exception as e:
            logger.error(f"获取邮件列表失败: {e}")
            raise

    async def check_email_exists(self, message_id: str) -> bool:
        """
        检查邮件是否已存在

        Args:
            message_id: 邮件message_id

        Returns:
            是否存在
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor() as cursor:
                    sql = "SELECT 1 FROM emails WHERE message_id = %s LIMIT 1"
                    await cursor.execute(sql, (message_id,))
                    result = await cursor.fetchone()
                    return result is not None

        except Exception as e:
            logger.error(f"检查邮件是否存在失败: {e}")
            raise

    async def get_latest_email_date(self) -> Optional[datetime]:
        """
        获取最新邮件的接收时间

        Returns:
            最新邮件的接收时间，如果没有邮件返回None
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor() as cursor:
                    sql = "SELECT MAX(date_received) FROM emails"
                    await cursor.execute(sql)
                    result = await cursor.fetchone()

                    if result and result[0]:
                        return result[0]
                    return None

        except Exception as e:
            logger.error(f"获取最新邮件时间失败: {e}")
            raise

    async def get_email_stats(self) -> Dict[str, Any]:
        """
        获取邮件统计信息

        Returns:
            统计信息字典
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 总邮件数
                    await cursor.execute("SELECT COUNT(*) as total FROM emails")
                    total_emails = (await cursor.fetchone())['total']

                    # 总附件数
                    await cursor.execute("SELECT COUNT(*) as total FROM attachments")
                    total_attachments = (await cursor.fetchone())['total']

                    # 今日新邮件数
                    await cursor.execute("""
                        SELECT COUNT(*) as today FROM emails 
                        WHERE DATE(date_received) = CURDATE()
                    """)
                    today_emails = (await cursor.fetchone())['today']

                    # 最新邮件时间
                    await cursor.execute("SELECT MAX(date_received) as latest FROM emails")
                    latest_result = await cursor.fetchone()
                    latest_email = latest_result['latest'] if latest_result else None

                    return {
                        'total_emails': total_emails,
                        'total_attachments': total_attachments,
                        'today_emails': today_emails,
                        'latest_email_time': latest_email
                    }

        except Exception as e:
            logger.error(f"获取邮件统计失败: {e}")
            raise

    async def delete_email(self, email_id: int) -> bool:
        """
        删除邮件（级联删除附件记录）

        Args:
            email_id: 邮件ID

        Returns:
            删除是否成功
        """
        try:
            async with self.db_manager.get_transaction() as conn:
                async with conn.cursor() as cursor:
                    # 由于外键约束设置了ON DELETE CASCADE，删除邮件会自动删除附件记录
                    sql = "DELETE FROM emails WHERE id = %s"
                    await cursor.execute(sql, (email_id,))
                    deleted_rows = cursor.rowcount

                    if deleted_rows > 0:
                        logger.info(f"邮件删除成功: ID={email_id}")
                        return True
                    else:
                        logger.warning(f"邮件不存在: ID={email_id}")
                        return False

        except Exception as e:
            logger.error(f"删除邮件失败: {e}")
            raise

    async def save_email_forward(self, forward: EmailForward) -> int:
        """
        保存邮件转发记录

        Args:
            forward: 转发记录模型

        Returns:
            转发记录ID
        """
        try:
            async with self.db_manager.get_transaction() as conn:
                async with conn.cursor() as cursor:
                    data = forward.to_db_dict()
                    columns = ', '.join(data.keys())
                    placeholders = ', '.join(['%s'] * len(data))

                    insert_sql = f"""
                        INSERT INTO email_forwards ({columns}) 
                        VALUES ({placeholders})
                    """

                    await cursor.execute(insert_sql, list(data.values()))
                    forward_id = cursor.lastrowid

                    logger.info(f"转发记录保存成功: ID={forward_id}")
                    return forward_id

        except Exception as e:
            logger.error(f"保存转发记录失败: {e}")
            raise

    async def update_forward_status(self, forward_id: int, status: str, error_message: Optional[str] = None) -> bool:
        """
        更新转发状态

        Args:
            forward_id: 转发记录ID
            status: 转发状态
            error_message: 错误信息（可选）

        Returns:
            更新是否成功
        """
        try:
            async with self.db_manager.get_transaction() as conn:
                async with conn.cursor() as cursor:
                    if error_message:
                        sql = """
                            UPDATE email_forwards 
                            SET forward_status = %s, error_message = %s 
                            WHERE id = %s
                        """
                        await cursor.execute(sql, (status, error_message, forward_id))
                    else:
                        sql = """
                            UPDATE email_forwards 
                            SET forward_status = %s 
                            WHERE id = %s
                        """
                        await cursor.execute(sql, (status, forward_id))

                    updated_rows = cursor.rowcount
                    if updated_rows > 0:
                        logger.info(
                            f"转发状态更新成功: ID={forward_id}, status={status}")
                        return True
                    else:
                        logger.warning(f"转发记录不存在: ID={forward_id}")
                        return False

        except Exception as e:
            logger.error(f"更新转发状态失败: {e}")
            raise

    async def get_forward_history(self, email_id: int) -> List[Dict[str, Any]]:
        """
        获取邮件转发历史

        Args:
            email_id: 邮件ID

        Returns:
            转发历史列表
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    sql = """
                        SELECT * FROM email_forwards 
                        WHERE email_id = %s 
                        ORDER BY forwarded_at DESC
                    """
                    await cursor.execute(sql, (email_id,))
                    results = await cursor.fetchall()

                    return [dict(row) for row in results]

        except Exception as e:
            logger.error(f"获取转发历史失败: {e}")
            raise

    async def get_forward_by_id(self, forward_id: int) -> Optional[Dict[str, Any]]:
        """
        根据ID获取转发记录

        Args:
            forward_id: 转发记录ID

        Returns:
            转发记录字典，如果不存在返回None
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    sql = "SELECT * FROM email_forwards WHERE id = %s"
                    await cursor.execute(sql, (forward_id,))
                    result = await cursor.fetchone()

                    if result:
                        return dict(result)
                    return None

        except Exception as e:
            logger.error(f"获取转发记录失败: {e}")
            raise

    async def update_email_field(self, email_id: int, field_name: str, field_value: Any) -> bool:
        """
        更新邮件的指定字段

        Args:
            email_id: 邮件ID
            field_name: 字段名称
            field_value: 字段值

        Returns:
            更新是否成功
        """
        try:
            # 安全检查：只允许更新特定字段
            allowed_fields = {'dispatcher_id', 'type', 'from_system'}
            if field_name not in allowed_fields:
                logger.error(f"不允许更新字段: {field_name}")
                raise ValueError(f"不允许更新字段: {field_name}")

            async with self.db_manager.get_transaction() as conn:
                async with conn.cursor() as cursor:
                    # 使用参数化查询防止SQL注入，字段名需要特殊处理
                    sql = f"UPDATE emails SET {field_name} = %s WHERE id = %s"
                    await cursor.execute(sql, (field_value, email_id))
                    updated_rows = cursor.rowcount

                    if updated_rows > 0:
                        logger.info(
                            f"邮件字段更新成功: email_id={email_id}, {field_name}={field_value}")
                        return True
                    else:
                        logger.warning(f"邮件不存在: email_id={email_id}")
                        return False

        except Exception as e:
            logger.error(f"更新邮件字段失败: {e}")
            raise


# 全局邮件数据库服务实例
email_db_service = EmailDatabaseService()
