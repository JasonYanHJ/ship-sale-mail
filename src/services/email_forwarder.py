import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.header import Header
from email.utils import formataddr
import json
import re
import urllib.parse
from typing import List, Optional, Dict, Any
from datetime import datetime
import os

from ..config.settings import settings
from ..utils.logger import get_logger
from ..models.email_models import EmailForward
from .email_database import EmailDatabaseService
from .file_storage import FileStorageService

logger = get_logger(__name__)


class EmailForwarder:
    """邮件转发服务"""

    def __init__(self):
        self.smtp_server = settings.smtp_server
        self.smtp_port = settings.smtp_port
        self.email_username = settings.email_username
        self.email_password = settings.email_password
        self.db_service = EmailDatabaseService()
        self.file_service = FileStorageService()

    async def forward_email(
        self,
        email_id: int,
        to_addresses: List[str],
        cc_addresses: Optional[List[str]] = None,
        bcc_addresses: Optional[List[str]] = None,
        additional_message: Optional[str] = None,
        reply_to: List[str] = [],
    ) -> bool:
        """
        转发邮件

        Args:
            email_id: 邮件ID
            to_addresses: 收件人列表
            cc_addresses: 抄送人列表
            bcc_addresses: 密送人列表
            additional_message: 附加消息
            reply_to: 回复人列表

        Returns:
            bool: 转发是否成功
        """
        try:
            # 获取原始邮件
            original_email = await self.db_service.get_email_by_id(email_id)
            if not original_email:
                logger.error(f"Email with ID {email_id} not found")
                return False

            # 获取附件信息
            attachments = await self.db_service.get_attachments_by_email_id(email_id)

            # 创建转发记录
            forward_record = EmailForward(
                email_id=email_id,
                to_addresses=to_addresses,
                cc_addresses=cc_addresses,
                bcc_addresses=bcc_addresses,
                additional_message=additional_message,
                forward_status="pending"
            )

            forward_id = await self.db_service.save_email_forward(forward_record)

            try:
                # 发送邮件
                success = await self._send_forward_email(
                    original_email,
                    attachments,
                    to_addresses,
                    cc_addresses,
                    bcc_addresses,
                    additional_message,
                    reply_to,
                )

                # 更新转发状态
                if success:
                    await self.db_service.update_forward_status(forward_id, "sent")
                    logger.info(
                        f"Email {email_id} forwarded successfully to {to_addresses}")
                    return True
                else:
                    await self.db_service.update_forward_status(forward_id, "failed", "Failed to send email")
                    return False

            except Exception as e:
                error_msg = str(e)
                await self.db_service.update_forward_status(forward_id, "failed", error_msg)
                logger.error(
                    f"Failed to forward email {email_id}: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"Error forwarding email {email_id}: {str(e)}")
            return False

    async def _send_forward_email(
        self,
        original_email,
        attachments,
        to_addresses: List[str],
        cc_addresses: Optional[List[str]] = None,
        bcc_addresses: Optional[List[str]] = None,
        additional_message: Optional[str] = None,
        reply_to: List[str] = [],
    ) -> bool:
        """发送转发邮件"""
        try:
            # 创建邮件对象
            msg = MIMEMultipart()

            # 设置邮件头
            msg['From'] = formataddr(
                (self.email_username, self.email_username))
            msg['To'] = ', '.join(to_addresses)
            if cc_addresses:
                msg['Cc'] = ', '.join(cc_addresses)
            if reply_to:
                msg['Reply-To'] = ', '.join(reply_to)

            # 转发邮件主题
            original_subject = original_email.subject or ''
            if not original_subject.startswith('Fwd:') and not original_subject.startswith('FW:'):
                forward_subject = f"Fwd: {original_subject}"
            else:
                forward_subject = original_subject
            msg['Subject'] = Header(forward_subject, 'utf-8')

            # 构建邮件内容
            email_body = self._build_forward_body(
                original_email, additional_message, reply_to)

            # 添加HTML内容
            if original_email.content_html:
                msg.attach(MIMEText(email_body, 'html', 'utf-8'))
            else:
                msg.attach(MIMEText(email_body, 'plain', 'utf-8'))

            # 添加附件
            for attachment in attachments:
                if await self._add_attachment_to_message(msg, attachment):
                    logger.info(
                        f"Added attachment: {attachment.original_filename}")
                else:
                    logger.warning(
                        f"Failed to add attachment: {attachment.original_filename}")

            # 发送邮件
            all_recipients = to_addresses[:]
            if cc_addresses:
                all_recipients.extend(cc_addresses)
            if bcc_addresses:
                all_recipients.extend(bcc_addresses)

            return await self._smtp_send(msg, all_recipients)

        except Exception as e:
            logger.error(f"Error building forward email: {str(e)}")
            return False

    def _build_forward_body(self, original_email, additional_message: Optional[str] = None, reply_to: Optional[List[str]] = None) -> str:
        """构建转发邮件正文"""
        try:
            # 获取原始邮件信息
            original_from = original_email.sender or ''
            original_to = original_email.recipients or []
            original_cc = original_email.cc or []
            original_date = original_email.date_sent or ''
            original_subject = original_email.subject or ''

            # 处理收件人列表
            if isinstance(original_to, list):
                original_to = ', '.join(original_to)
            elif isinstance(original_to, str) and original_to.startswith('['):
                try:
                    original_to = ', '.join(json.loads(original_to))
                except:
                    pass

            # 处理抄送列表
            if isinstance(original_cc, list):
                original_cc = ', '.join(original_cc)
            elif isinstance(original_cc, str) and original_cc.startswith('['):
                try:
                    original_cc = ', '.join(json.loads(original_cc))
                except:
                    pass

            # 构建转发头部
            forward_header = f"""---------- Forwarded message ----------
From: {original_from}
Date: {original_date}
Subject: {original_subject}
To: {original_to}
Reply-To: {', '.join(reply_to)}
"""

            if original_cc:
                forward_header += f"Cc: {original_cc}\n"

            # 添加附加消息
            body_parts = []
            if additional_message:
                body_parts.append(additional_message)
                body_parts.append("")  # 空行分隔

            body_parts.append(forward_header)
            body_parts.append("")  # 空行分隔

            # 添加原始邮件内容
            if original_email.content_html:
                # HTML内容处理
                return self._insert_html_forward_content(
                    original_email.content_html,
                    forward_header,
                    additional_message
                )
            else:
                # 纯文本内容
                if original_email.content_text:
                    body_parts.append(original_email.content_text)

                return '\n'.join(body_parts)

        except Exception as e:
            logger.error(f"Error building forward body: {str(e)}")
            return f"Error building email content: {str(e)}"

    def _insert_html_forward_content(self, html_content: str, forward_header: str, additional_message: Optional[str] = None) -> str:
        """
        在HTML内容中插入转发头部和附加消息

        Args:
            html_content: 原始HTML内容
            forward_header: 转发头部信息
            additional_message: 附加消息

        Returns:
            处理后的HTML内容
        """
        try:
            # 使用正则表达式匹配body标签（支持属性）
            body_pattern = re.compile(r'(<body[^>]*>)', re.IGNORECASE)
            body_match = body_pattern.search(html_content)

            if body_match:
                # 找到body标签，准备插入内容
                html_header = forward_header.replace('\n', '<br>')
                forward_content = f'<pre style="font-family: monospace; margin: 10px 0; padding: 10px; background-color: #f5f5f5; border-left: 3px solid #ccc;">{html_header}</pre>'

                insert_content = ""
                if additional_message:
                    insert_content += f'<div style="margin-bottom: 15px; padding: 10px; background-color: #e8f4f8; border-radius: 5px;"><p style="margin: 0; color: #2c5aa0;"><strong>转发说明:</strong> {additional_message}</p></div>'

                insert_content += forward_content

                # 在body标签后插入内容
                insert_position = body_match.end()
                modified_html = (
                    html_content[:insert_position] +
                    insert_content +
                    html_content[insert_position:]
                )
                return modified_html
            else:
                # 没有找到body标签，直接返回原内容，不插入转发头信息
                logger.warning(
                    "No body tag found in HTML content, skipping forward header insertion")
                return html_content

        except Exception as e:
            logger.error(f"Error inserting HTML forward content: {str(e)}")
            # 出错时返回原内容
            return html_content

    async def _add_attachment_to_message(self, msg: MIMEMultipart, attachment) -> bool:
        """向邮件添加附件"""
        try:
            file_path = attachment.file_path
            original_filename = attachment.original_filename
            content_type = attachment.content_type or 'application/octet-stream'

            # 检查文件是否存在
            if not os.path.exists(file_path):
                logger.warning(f"Attachment file not found: {file_path}")
                return False

            # 读取文件内容
            file_content = await self.file_service.read_attachment(file_path)
            if not file_content:
                logger.warning(f"Failed to read attachment: {file_path}")
                return False

            # 创建附件对象
            attachment_part = MIMEBase('application', 'octet-stream')
            attachment_part.set_payload(file_content)
            encoders.encode_base64(attachment_part)

            # 设置附件头，保持原有的content-disposition-type
            disposition_type = attachment.content_disposition_type or 'inline'

            # 对文件名进行RFC2231编码以支持中文文件名
            encoded_filename = self._encode_filename_rfc2231(original_filename)
            attachment_part.add_header(
                'Content-Disposition',
                f'{disposition_type}; {encoded_filename}'
            )

            # 设置Content-ID（如果原附件有的话）
            if hasattr(attachment, 'content_id') and attachment.content_id:
                attachment_part.add_header(
                    'Content-Id', f'<{attachment.content_id}>')

            msg.attach(attachment_part)
            return True

        except Exception as e:
            logger.error(
                f"Error adding attachment {getattr(attachment, 'original_filename', 'unknown')}: {str(e)}")
            return False

    def _encode_filename_rfc2231(self, filename: str) -> str:
        """
        使用RFC2231标准编码文件名以支持中文字符

        Args:
            filename: 原始文件名

        Returns:
            编码后的filename参数字符串
        """
        try:
            # 检查文件名是否包含非ASCII字符
            filename.encode('ascii')
            # 如果是纯ASCII，直接使用普通格式
            return f'filename="{filename}"'
        except UnicodeEncodeError:
            # 包含非ASCII字符，使用RFC2231编码
            try:
                # 使用UTF-8编码并URL编码
                encoded = urllib.parse.quote(filename.encode('utf-8'))
                # RFC2231格式: filename*=charset'language'encoded-value
                return f"filename*=utf-8''{encoded}"
            except Exception as e:
                logger.warning(f"RFC2231编码文件名失败: {e}, 使用原文件名")
                # 降级处理：直接使用原文件名（可能出现乱码）
                return f'filename="{filename}"'

    async def _smtp_send(self, msg: MIMEMultipart, recipients: List[str]) -> bool:
        """通过SMTP发送邮件"""
        try:
            # 创建SSL上下文
            context = ssl.create_default_context()

            # 连接SMTP服务器
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context) as server:
                # 登录
                server.login(self.email_username, self.email_password)

                # 发送邮件
                text = msg.as_string()
                server.sendmail(self.email_username, recipients, text)

                logger.info(f"Email sent successfully to {recipients}")
                return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {str(e)}")
            return False
        except smtplib.SMTPRecipientsRefused as e:
            logger.error(f"SMTP recipients refused: {str(e)}")
            return False
        except smtplib.SMTPServerDisconnected as e:
            logger.error(f"SMTP server disconnected: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"SMTP send error: {str(e)}")
            return False

    async def get_forward_history(self, email_id: int) -> List[Dict[str, Any]]:
        """获取邮件转发历史"""
        try:
            return await self.db_service.get_forward_history(email_id)
        except Exception as e:
            logger.error(
                f"Error getting forward history for email {email_id}: {str(e)}")
            return []

    async def get_forward_status(self, forward_id: int) -> Optional[Dict[str, Any]]:
        """获取转发状态"""
        try:
            return await self.db_service.get_forward_by_id(forward_id)
        except Exception as e:
            logger.error(
                f"Error getting forward status {forward_id}: {str(e)}")
            return None


forwarder = EmailForwarder()
