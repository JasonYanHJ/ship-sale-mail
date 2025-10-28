from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple
import asyncio

from ..services.email_reader import EmailReader
from ..services.email_database import email_db_service
from ..services.file_storage import file_storage
from ..services.rule_engine import RuleEngine
from ..models.email_models import EmailModel, AttachmentModel, EmailSyncStats
from ..utils.email_parser import EmailParser
from ..utils.logger import get_logger
from ..services.email_extra_process.shipserv import process_shipserv_pdf, process_shipserv_order_pdf
from ..models.database import db_manager
import aiomysql
from ..services.email_forwarder import forwarder

logger = get_logger("email_sync")


class EmailSyncService:
    """邮件同步服务 - 可复用的邮件处理逻辑"""

    def __init__(self):
        self.email_reader = EmailReader()
        self.email_parser = EmailParser()
        self.rule_engine = RuleEngine()
        self.is_syncing = False
        self.last_sync_time: Optional[datetime] = None
        self.sync_stats = EmailSyncStats()

    async def sync_emails(self, limit: Optional[int] = None,
                          since_date: Optional[datetime] = None) -> EmailSyncStats:
        """
        同步邮件的核心逻辑（可被定时任务和手动触发复用）

        Args:
            limit: 最大处理邮件数量限制
            since_date: 从指定日期开始同步，None表示自动检测

        Returns:
            同步统计信息
        """
        if self.is_syncing:
            logger.warning("邮件同步正在进行中，跳过本次执行")
            return self.sync_stats

        sync_start_time = datetime.now()
        self.is_syncing = True

        # 重置统计信息
        self.sync_stats = EmailSyncStats(sync_time=sync_start_time)

        try:
            logger.info("开始邮件同步...")

            # 1. 连接邮箱并获取邮件列表
            async with self.email_reader as reader:
                # 获取邮件UID列表
                mail_uids = await self._get_mail_uids(reader, since_date, limit)
                logger.info(f"找到 {len(mail_uids)} 封待处理邮件")

                if not mail_uids:
                    logger.info("没有新邮件需要同步")
                    return self.sync_stats

                # 2. 处理每封邮件
                for i, uid in enumerate(mail_uids, 1):
                    try:
                        logger.debug(f"处理邮件 {i}/{len(mail_uids)}: UID={uid}")
                        await self._process_single_email(reader, uid)

                        # 定期输出进度
                        if i % 10 == 0:
                            logger.info(f"已处理 {i}/{len(mail_uids)} 封邮件")

                    except Exception as e:
                        logger.error(f"处理邮件 UID={uid} 失败: {e}")
                        self.sync_stats.errors += 1
                        continue

                # 3. 更新同步时间
                self.last_sync_time = sync_start_time

                # 4. 输出最终统计
                duration = datetime.now() - sync_start_time
                logger.info(f"邮件同步完成 - 耗时: {duration.total_seconds():.2f}秒")
                logger.info(f"统计: 总计{self.sync_stats.total_processed}封, "
                            f"新增{self.sync_stats.new_emails}封, "
                            f"重复跳过{self.sync_stats.duplicates_skipped}封, "
                            f"规则跳过{self.sync_stats.rule_skipped}封, "
                            f"错误{self.sync_stats.errors}封")

                return self.sync_stats

        except Exception as e:
            logger.error(f"邮件同步失败: {e}")
            self.sync_stats.errors += 1
            raise
        finally:
            self.is_syncing = False

    async def _get_mail_uids(self, reader: EmailReader, since_date: datetime, limit: Optional[int]) -> List[int]:
        """获取需要处理的邮件UID列表"""
        try:
            # 确保选择了收件箱文件夹
            reader.select_folder('INBOX')

            # 构建搜索条件：未读邮件 + 指定日期之后（如果提供）
            search_criteria = ['FLAGGED']
            if since_date:
                search_criteria.extend(
                    ['SINCE', since_date.strftime("%d-%b-%Y")])

            logger.debug(f"搜索条件: {search_criteria}")

            uids = reader.search_emails(search_criteria)
            logger.info(f"找到 {len(uids)} 封匹配条件的邮件")

            if limit and len(uids) > limit:
                uids = uids[:limit]
                logger.info(f"应用数量限制，只处理前 {limit} 封邮件")

            return uids

        except Exception as e:
            logger.error(f"获取邮件UID列表失败: {e}")
            logger.error(
                f"搜索条件: {search_criteria if 'search_criteria' in locals() else 'N/A'}")
            return []

    async def _process_single_email(self, reader: EmailReader, uid: int):
        """处理单封邮件"""
        self.sync_stats.total_processed += 1

        try:
            # 1. 获取原始邮件数据
            metadata, raw_email = reader.fetch_raw_email(uid)
            if not raw_email:
                logger.warning(f"无法获取邮件原始数据: UID={uid}")
                return

            # 2. 解析邮件
            parsed_email = self.email_parser.parse_full_email(raw_email)

            # 3. 检查是否已存在（去重）
            message_id = parsed_email.get('message_id')
            if not message_id:
                logger.warning(f"邮件缺少message_id: UID={uid}")
                return

            exists = await email_db_service.check_email_exists(message_id)
            if exists:
                logger.debug(f"邮件已存在，跳过: {message_id}")
                self.sync_stats.duplicates_skipped += 1
                return

            # 4. 应用规则引擎
            rule_result = await self.rule_engine.apply_rules(parsed_email)

            # 5. 如果规则决定跳过邮件，则标记并返回
            if rule_result.should_skip:
                logger.info(
                    f"邮件被规则跳过: {message_id}, 匹配规则: {rule_result.matched_rules}")
                # 标记邮件已处理但不保存到数据库
                reader.mark_as_unflagged(uid)
                self.sync_stats.rule_skipped += 1  # 计入规则跳过统计
                return

            # 6. 创建邮件模型
            email_model = await self._create_email_model(parsed_email)

            # 7. 处理附件
            attachment_models = await self._process_attachments(
                parsed_email, str(uid)
            )

            # 8. 根据邮件类别额外处理邮件
            await self._process_email_extra(parsed_email, attachment_models)

            # 9. 保存到数据库
            email_id, attachment_ids = await email_db_service.save_email_with_attachments(
                email_model, attachment_models
            )

            self.sync_stats.new_emails += 1
            self.sync_stats.last_message_id = message_id

            # 10. 标记邮件已处理
            reader.mark_as_unflagged(uid)

            logger.debug(f"邮件处理完成: UID={uid}, DB_ID={email_id}, "
                         f"附件数={len(attachment_ids)}")

            # 11. 自动转发部分特定情形的邮件
            await self._process_auto_forward(email_id, parsed_email, attachment_models)
        except Exception as e:
            logger.error(f"处理邮件失败 UID={uid}: {e}")
            raise

    async def _process_auto_forward(self, email_id: int, parsed_email: Dict[str, Any], attachment_models: List[AttachmentModel]):
        # 订单邮件，如果有成功解析出销售代码，则系统自动转发
        if parsed_email.get('type') == 'ORDER':
            for attachment_model in attachment_models:
                if attachment_model.extra and attachment_model.extra['type'] == 'ORDER' and attachment_model.extra['code']:
                    saler = None
                    dispatcher = None

                    async with db_manager.get_read_connection() as conn:
                        async with conn.cursor(aiomysql.DictCursor) as cursor:
                            # 根据销售代码后三位（代表销售的缩写）确定对应销售以及其组长
                            sql = "SELECT s.*, l.* FROM salers s LEFT JOIN salers l ON s.leader_id = l.id WHERE s.abbr = %s"
                            await cursor.execute(sql, (attachment_model.extra['code'][-3:],))
                            saler = await cursor.fetchone()

                            # 根据dispatcher_id获取转发员的信息
                            if parsed_email.get('dispatcher_id'):
                                sql = "SELECT * FROM users WHERE id = %s"
                                await cursor.execute(sql, (parsed_email.get('dispatcher_id'),))
                                dispatcher = await cursor.fetchone()

                            logger.debug(f"销售数据：{saler}, 转发员数据：{dispatcher}")

                    if saler:
                        # 转发给销售，同时抄送order公共邮箱、转发员和销售组长，回复对象设置为转发员
                        await forwarder.forward_email(
                            email_id=email_id,
                            to_addresses=[saler['email']],
                            cc_addresses=['order@dan-marine.com']
                            + ([saler['l.email']]
                               if saler['l.email'] else [])
                            + [dispatcher['email']
                               ] if dispatcher else [],
                            reply_to=[dispatcher['email']
                                      ] if dispatcher else [],
                        )
                    break
            return
        pass

    async def _process_email_extra(self, parsed_email: Dict[str, Any], attachment_models: List[AttachmentModel]):
        try:
            if parsed_email.get('rfq') == True and parsed_email.get('rfq_type') == 'ShipServ':
                logger.debug(
                    f"开始额外处理shipserv邮件: message_id={parsed_email['message_id']}")

                # 逐个处理附件
                for attachment_model in attachment_models:
                    file_path = attachment_model.file_path

                    # 跳过非pdf附件
                    if not file_path.endswith('.pdf'):
                        continue

                    # 解析询价pdf数据
                    result = process_shipserv_pdf(file_path)
                    if not result:
                        continue

                    # 将数据保存在附件的extra字段中
                    attachment_model.extra = {
                        'type': 'ShipServ',
                        'version': 2,
                        'table_data': result['table_data'],
                        'section_data': result['section_data'],
                        'meta_data': result['meta_data'],
                    }
                return
            if parsed_email.get('type') == 'ORDER' and parsed_email.get('rfq_type') == 'ShipServ':
                logger.debug(
                    f"开始额外处理shipserv订单邮件: message_id={parsed_email['message_id']}")

                # 逐个处理附件
                for attachment_model in attachment_models:
                    file_path = attachment_model.file_path

                    # 跳过非pdf附件
                    if not file_path.endswith('.pdf'):
                        continue

                    # 解析询价pdf数据
                    result = process_shipserv_order_pdf(file_path)
                    if not result:
                        continue

                    # 将数据保存在附件的extra字段中
                    attachment_model.extra = {
                        'type': 'ORDER',
                        'from': 'ShipServ',
                        'version': 1,
                        'code': result['code'],
                    }
                return
        except Exception as e:
            logger.error(f"邮件额外处理失败: {e}")
            raise

    async def _create_email_model(self, parsed_email: Dict[str, Any]) -> EmailModel:
        """从解析结果创建邮件模型"""
        return EmailModel(
            message_id=parsed_email['message_id'],
            subject=parsed_email.get('subject'),
            sender=parsed_email.get('sender'),
            recipients=parsed_email.get('recipients', []),
            cc=parsed_email.get('cc', []),
            bcc=parsed_email.get('bcc', []),
            content_text=parsed_email.get('content_text'),
            content_html=parsed_email.get('content_html'),
            date_sent=parsed_email.get('date_sent'),
            date_received=datetime.now(),
            raw_headers=parsed_email.get('raw_headers'),
            dispatcher_id=parsed_email.get('dispatcher_id'),
            rfq=parsed_email.get('rfq'),
            rfq_type=parsed_email.get('rfq_type'),
            type=parsed_email.get('type'),
        )

    async def _process_attachments(self, parsed_email: Dict[str, Any],
                                   email_uid: str) -> List[AttachmentModel]:
        """处理邮件附件"""
        attachment_models = []
        attachments = parsed_email.get('attachments', [])

        if not attachments:
            return attachment_models

        logger.debug(f"处理 {len(attachments)} 个附件")

        for attachment in attachments:
            try:
                filename = attachment.get('filename', 'unknown_attachment')
                content = attachment.get('content', b'')
                content_type = attachment.get(
                    'content_type', 'application/octet-stream')
                content_disposition_type = attachment.get(
                    'content_disposition_type', '')
                content_id = attachment.get('content_id')

                if not content:
                    logger.warning(f"附件内容为空，跳过: {filename}")
                    continue

                # 保存附件文件
                file_info = await file_storage.save_attachment(
                    email_uid, filename, content, parsed_email.get(
                        'date_received')
                )

                # 创建附件模型
                attachment_model = AttachmentModel(
                    email_id=0,  # 将在保存邮件时设置
                    original_filename=filename,
                    stored_filename=file_info['stored_filename'],
                    file_path=file_info['file_path'],
                    file_size=file_info['file_size'],
                    content_type=content_type,
                    content_disposition_type=content_disposition_type,
                    content_id=content_id,
                    extra=None
                )

                attachment_models.append(attachment_model)
                logger.debug(
                    f"附件处理完成: {filename} -> {file_info['stored_filename']}")

            except Exception as e:
                logger.error(
                    f"处理附件失败 {attachment.get('filename', 'unknown')}: {e}")
                continue

        return attachment_models

    async def get_sync_status(self) -> Dict[str, Any]:
        """获取同步状态信息"""
        try:
            db_stats = await email_db_service.get_email_stats()

            return {
                'is_syncing': self.is_syncing,
                'last_sync_time': self.last_sync_time,
                'last_sync_stats': {
                    'total_processed': self.sync_stats.total_processed,
                    'new_emails': self.sync_stats.new_emails,
                    'duplicates_skipped': self.sync_stats.duplicates_skipped,
                    'rule_skipped': self.sync_stats.rule_skipped,
                    'errors': self.sync_stats.errors,
                    'last_message_id': self.sync_stats.last_message_id
                },
                'database_stats': db_stats
            }

        except Exception as e:
            logger.error(f"获取同步状态失败: {e}")
            return {
                'is_syncing': self.is_syncing,
                'last_sync_time': self.last_sync_time,
                'error': str(e)
            }

    async def force_sync_since(self, since_date: datetime,
                               limit: Optional[int] = None) -> EmailSyncStats:
        """强制从指定日期开始同步"""
        logger.info(f"强制同步: 从 {since_date} 开始，限制数量: {limit}")
        return await self.sync_emails(limit=limit, since_date=since_date)

    async def incremental_sync(self, limit: Optional[int] = None) -> EmailSyncStats:
        """增量同步（从上次同步点开始）"""
        logger.info(f"增量同步，限制数量: {limit}")
        return await self.sync_emails(limit=limit, since_date=None)


# 全局邮件同步服务实例
email_sync_service = EmailSyncService()
