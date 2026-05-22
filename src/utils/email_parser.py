from typing import Dict, List, Optional
from datetime import datetime
from email.message import Message
from email import message_from_bytes
import email.utils
import email.header
import re
import urllib.parse
from .logger import logger


class EmailParser:
    """邮件解析工具类"""

    @staticmethod
    def parse_message_from_bytes(raw_email: bytes) -> Message:
        """从字节数据解析邮件消息对象"""
        try:
            return message_from_bytes(raw_email)
        except Exception as e:
            logger.error(f"解析邮件字节数据失败: {e}")
            raise

    @staticmethod
    def parse_headers(msg: Message) -> Dict:
        """解析邮件头信息"""
        try:
            # 解析发件人
            sender_raw = EmailParser._decode_header(msg.get('From', ''))
            sender = email.utils.parseaddr(sender_raw)[1] if sender_raw else ''

            # 解析收件人
            recipients = []
            to_header = EmailParser._decode_header(msg.get('To', ''))
            if to_header:
                recipients.extend(
                    [addr[1] for addr in email.utils.getaddresses([to_header])])

            # 解析抄送
            cc = []
            cc_header = EmailParser._decode_header(msg.get('Cc', ''))
            if cc_header:
                cc.extend([addr[1]
                          for addr in email.utils.getaddresses([cc_header])])

            # 解析密送
            bcc = []
            bcc_header = EmailParser._decode_header(msg.get('Bcc', ''))
            if bcc_header:
                bcc.extend([addr[1]
                           for addr in email.utils.getaddresses([bcc_header])])

            # 解析日期
            date_sent = None
            date_header = EmailParser._decode_header(msg.get('Date', ''))
            if date_header:
                try:
                    date_tuple = email.utils.parsedate_tz(date_header)
                    if date_tuple:
                        timestamp = email.utils.mktime_tz(date_tuple)
                        date_sent = datetime.fromtimestamp(timestamp)
                except Exception as e:
                    logger.warning(f"解析邮件日期失败: {e}")

            # 解析主题 - 处理MIME编码并清理格式
            subject = EmailParser._decode_header(msg.get('Subject', ''))
            subject = EmailParser._clean_header_text(subject)
            
            # 解析Message-ID并清理格式
            message_id = EmailParser._clean_header_text(
                EmailParser._decode_header(msg.get('Message-ID', ''))
            )

            return {
                'message_id': message_id,
                'subject': subject,
                'sender': sender,
                'recipients': recipients,
                'cc': cc,
                'bcc': bcc,
                'date_sent': date_sent,
                'raw_headers': EmailParser._extract_raw_headers(msg)
            }

        except Exception as e:
            logger.error(f"解析邮件头失败: {e}")
            raise

    @staticmethod
    def parse_content(msg: Message) -> Dict:
        """解析邮件内容"""
        try:
            content_text = ""
            content_html = ""
            attachments = []

            if msg.is_multipart():
                # 多部分邮件
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = EmailParser._decode_header(
                        part.get('Content-Disposition', '')
                    )
                    disposition_type = EmailParser._extract_disposition_type(
                        content_disposition
                    )

                    if content_type == 'text/plain' and disposition_type != 'attachment':
                        # 文本内容
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or 'utf-8'
                            try:
                                content_text += payload.decode(
                                    charset, errors='ignore')
                            except:
                                content_text += payload.decode(
                                    'utf-8', errors='ignore')

                    elif content_type == 'text/html' and disposition_type != 'attachment':
                        # HTML内容
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or 'utf-8'
                            try:
                                content_html += payload.decode(
                                    charset, errors='ignore')
                            except:
                                content_html += payload.decode(
                                    'utf-8', errors='ignore')

                    elif disposition_type == 'attachment' or part.get_filename():
                        # 附件
                        filename = part.get_filename()
                        if filename:
                            # 解码文件名
                            decoded_filename = EmailParser._decode_filename(
                                filename)

                            # 提取Content-ID（如果有）
                            content_id = part.get('Content-Id')
                            if content_id:
                                # 移除尖括号（如果存在）
                                content_id = content_id.strip('<>')

                            attachment_info = {
                                'filename': decoded_filename,
                                'content_type': content_type,
                                'size': len(part.get_payload(decode=True) or b''),
                                'content': part.get_payload(decode=True),
                                'content_disposition_type': disposition_type,
                                'content_id': content_id
                            }
                            attachments.append(attachment_info)
            else:
                # 单部分邮件
                content_type = msg.get_content_type()
                payload = msg.get_payload(decode=True)

                if payload:
                    charset = msg.get_content_charset() or 'utf-8'
                    try:
                        content = payload.decode(charset, errors='ignore')
                    except:
                        content = payload.decode('utf-8', errors='ignore')

                    if content_type == 'text/plain':
                        content_text = content
                    elif content_type == 'text/html':
                        content_html = content

            return {
                'content_text': content_text,
                'content_html': content_html,
                'attachments': attachments
            }

        except Exception as e:
            logger.error(f"解析邮件内容失败: {e}")
            raise

    @staticmethod
    def parse_full_email(raw_email: bytes) -> Dict:
        """完整解析邮件（头信息+内容）"""
        try:
            # 解析邮件消息对象
            msg = EmailParser.parse_message_from_bytes(raw_email)

            # 解析邮件头
            headers = EmailParser.parse_headers(msg)

            # 解析邮件内容
            content = EmailParser.parse_content(msg)

            # 合并结果
            return {
                **headers,
                **content
            }

        except Exception as e:
            logger.error(f"完整解析邮件失败: {e}")
            raise

    @staticmethod
    def _decode_header(header_value) -> str:
        """解码MIME编码的邮件头，并兼容Header对象和unknown-8bit头。"""
        if not header_value:
            return ''

        original_value = header_value

        try:
            # Python email在遇到未按RFC编码的8-bit头时会返回Header对象；
            # 直接对Header做 in/startswith/split 会抛 TypeError，先转成可解码文本。
            if isinstance(header_value, email.header.Header):
                header_value = header_value.encode()
            elif isinstance(header_value, bytes):
                header_value = header_value.decode('utf-8', errors='replace')
            else:
                header_value = str(header_value)

            decoded_parts = email.header.decode_header(header_value)
            decoded_string = ''

            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    decoded_string += EmailParser._decode_header_bytes(
                        part, encoding
                    )
                else:
                    decoded_string += str(part)

            return decoded_string.strip()

        except Exception as e:
            logger.warning(f"解码邮件头失败: {e}, 原始值: {original_value}")
            return str(original_value)

    @staticmethod
    def _decode_header_bytes(part: bytes, encoding: Optional[str]) -> str:
        """按邮件头声明编码解码字节，unknown-8bit优先尝试UTF-8。"""
        candidate_encodings = []

        if encoding and encoding.lower() != 'unknown-8bit':
            candidate_encodings.append(encoding)

        candidate_encodings.extend(['utf-8', 'gb18030', 'latin1'])

        for candidate_encoding in candidate_encodings:
            try:
                return part.decode(candidate_encoding)
            except (UnicodeDecodeError, LookupError):
                continue

        return part.decode('utf-8', errors='replace')

    @staticmethod
    def _extract_raw_headers(msg: Message) -> str:
        """提取邮件的原始头信息（不包含正文）"""
        try:
            # 构建包含所有头信息的字符串
            headers = []
            for key, value in msg.items():
                headers.append(f"{key}: {EmailParser._decode_header(value)}")
            return "\n".join(headers)
        except Exception as e:
            logger.warning(f"提取原始邮件头失败: {e}")
            return ""

    @staticmethod
    def _decode_filename(filename: str) -> str:
        """
        解码文件名，支持多种编码格式
        
        Args:
            filename: 原始文件名
            
        Returns:
            解码后的文件名
        """
        if not filename:
            return ''
            
        original_filename = filename
        filename = EmailParser._decode_header(filename)
        
        try:
            # 1. 首先检查是否是MIME编码格式 (=?charset?encoding?encoded-text?=)
            if filename.startswith('=?') and filename.endswith('?='):
                logger.debug(f"检测到MIME编码文件名: {filename}")
                decoded = EmailParser._decode_header(filename)
                if decoded and decoded != filename:
                    logger.debug(f"MIME解码成功: {filename} -> {decoded}")
                    return decoded
            
            # 2. 尝试RFC2231编码解码 (用于处理非ASCII文件名)
            try:
                decoded = email.utils.collapse_rfc2231_value(filename)
                if decoded and decoded != filename:
                    logger.debug(f"RFC2231解码成功: {filename} -> {decoded}")
                    return decoded
            except (ValueError, LookupError) as e:
                logger.debug(f"RFC2231解码失败: {e}")
            
            # 3. 检查是否是URL编码格式 (包含%字符)
            if '%' in filename:
                try:
                    decoded = urllib.parse.unquote(filename)
                    if decoded and decoded != filename:
                        logger.debug(f"URL解码成功: {filename} -> {decoded}")
                        return decoded
                except Exception as e:
                    logger.debug(f"URL解码失败: {e}")
            
            # 4. 如果都不是，直接返回原文件名
            logger.debug(f"文件名无需解码: {filename}")
            return filename
            
        except Exception as e:
            logger.warning(f"文件名解码出错: {e}, 原始文件名: {original_filename}")
            return original_filename

    @staticmethod
    def extract_attachment_info(msg: Message) -> List[Dict]:
        """仅提取附件信息（不包含内容）"""
        try:
            attachments = []

            if msg.is_multipart():
                for part in msg.walk():
                    content_disposition = EmailParser._decode_header(
                        part.get('Content-Disposition', '')
                    )
                    disposition_type = EmailParser._extract_disposition_type(
                        content_disposition
                    )

                    if disposition_type == 'attachment' or part.get_filename():
                        filename = part.get_filename()
                        if filename:
                            decoded_filename = EmailParser._decode_filename(
                                filename)

                            attachment_info = {
                                'filename': decoded_filename,
                                'content_type': part.get_content_type(),
                                'size': len(part.get_payload(decode=True) or b''),
                                'content_disposition_type': disposition_type
                            }
                            attachments.append(attachment_info)

            return attachments

        except Exception as e:
            logger.error(f"提取附件信息失败: {e}")
            return []

    @staticmethod
    def extract_attachment_content(msg: Message, filename: str) -> Optional[bytes]:
        """提取指定附件的内容"""
        try:
            if msg.is_multipart():
                for part in msg.walk():
                    content_disposition = EmailParser._decode_header(
                        part.get('Content-Disposition', '')
                    )
                    disposition_type = EmailParser._extract_disposition_type(
                        content_disposition
                    )

                    if disposition_type == 'attachment' or part.get_filename():
                        part_filename = part.get_filename()
                        if part_filename:
                            decoded_filename = EmailParser._decode_filename(
                                part_filename)
                            if decoded_filename == filename:
                                return part.get_payload(decode=True)

            return None

        except Exception as e:
            logger.error(f"提取附件内容失败: {e}")
            return None

    @staticmethod
    def _extract_disposition_type(content_disposition: str) -> str:
        """
        从Content-Disposition头中提取disposition类型

        Args:
            content_disposition: Content-Disposition头的完整值

        Returns:
            disposition类型（去除参数部分），如果解析失败返回空字符串
        """
        content_disposition = EmailParser._decode_header(content_disposition)

        if not content_disposition:
            return ''

        try:
            # Content-Disposition格式为:
            # "attachment; filename=example.txt"
            # "inline; filename=image.jpg"
            # "form-data; name=file"
            # 我们只需要第一部分的disposition类型，去除后续的参数
            disposition_type = content_disposition.split(';')[
                0].strip().lower()

            # 返回disposition类型（保留所有可能的类型值）
            return disposition_type

        except Exception as e:
            logger.warning(
                f"解析Content-Disposition类型失败: {e}, 原始值: {content_disposition}")
            return ''

    @staticmethod
    def _clean_header_text(text: str) -> str:
        """
        清理邮件头文本，去掉多余的空格和回车符
        
        Args:
            text: 原始文本
            
        Returns:
            清理后的文本
        """
        if not text:
            return ''

        text = str(text)
        
        try:
            # 去掉首尾空格和回车符
            cleaned_text = text.strip()
            
            # 去掉文本中间的回车符和换行符（email库会自动插入这些字符来格式化长行）
            cleaned_text = cleaned_text.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
            
            # 将多个连续空格替换为单个空格
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
            
            # 再次去掉首尾空格
            cleaned_text = cleaned_text.strip()
            
            return cleaned_text
            
        except Exception as e:
            logger.warning(f"清理邮件头文本失败: {e}, 原始文本: {text}")
            return text.strip() if text else ''


# 全局邮件解析器实例
email_parser = EmailParser()
