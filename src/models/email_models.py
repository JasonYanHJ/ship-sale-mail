from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import json


class EmailModel(BaseModel):
    """邮件数据模型"""
    id: Optional[int] = None
    message_id: str
    subject: Optional[str] = None
    sender: Optional[str] = None
    recipients: Optional[List[str]] = None
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None
    content_text: Optional[str] = None
    content_html: Optional[str] = None
    date_sent: Optional[datetime] = None
    date_received: Optional[datetime] = None
    raw_headers: Optional[str] = None
    dispatcher_id: Optional[int] = None  # 处理人ID，NULLABLE bigint unsigned
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    type: Optional[str] = None
    from_system: Optional[str] = None

    def to_db_dict(self) -> Dict[str, Any]:
        """转换为数据库存储格式"""
        data = {
            'message_id': self.message_id,
            'subject': self.subject,
            'sender': self.sender,
            'recipients': json.dumps(self.recipients, ensure_ascii=False) if self.recipients else None,
            'cc': json.dumps(self.cc, ensure_ascii=False) if self.cc else None,
            'bcc': json.dumps(self.bcc, ensure_ascii=False) if self.bcc else None,
            'content_text': self.content_text,
            'content_html': self.content_html,
            'date_sent': self.date_sent,
            'date_received': self.date_received,
            'raw_headers': self.raw_headers,
            'dispatcher_id': self.dispatcher_id,
            'type': self.type,
            'from_system': self.from_system,
        }
        if self.id:
            data['id'] = self.id
        return data

    @classmethod
    def from_db_dict(cls, data: Dict[str, Any]) -> 'EmailModel':
        """从数据库记录创建模型"""
        email_data = data.copy()

        # 解析JSON字段
        if email_data.get('recipients'):
            email_data['recipients'] = json.loads(email_data['recipients'])
        if email_data.get('cc'):
            email_data['cc'] = json.loads(email_data['cc'])
        if email_data.get('bcc'):
            email_data['bcc'] = json.loads(email_data['bcc'])

        return cls(**email_data)


class AttachmentModel(BaseModel):
    """附件数据模型"""
    id: Optional[int] = None
    email_id: int
    original_filename: Optional[str] = None
    stored_filename: Optional[str] = None
    file_path: Optional[str] = None
    file_size: Optional[int] = None
    content_type: Optional[str] = None
    content_disposition_type: Optional[str] = None
    content_id: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None

    def to_db_dict(self) -> Dict[str, Any]:
        """转换为数据库存储格式"""
        data = {
            'email_id': self.email_id,
            'original_filename': self.original_filename,
            'stored_filename': self.stored_filename,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'content_type': self.content_type,
            'content_disposition_type': self.content_disposition_type,
            'content_id': self.content_id,
            'extra': json.dumps(self.extra, ensure_ascii=False) if self.extra else None
        }
        if self.id:
            data['id'] = self.id
        return data

    @classmethod
    def from_db_dict(cls, data: Dict[str, Any]) -> 'AttachmentModel':
        """从数据库记录创建模型"""
        attachment_data = data.copy()

        # 解析JSON字段
        if attachment_data.get('extra'):
            attachment_data['extra'] = json.loads(attachment_data['extra'])

        return cls(**attachment_data)


class EmailForwardRequest(BaseModel):
    """邮件转发请求模型"""
    to_addresses: List[str]
    cc_addresses: Optional[List[str]] = None
    bcc_addresses: Optional[List[str]] = None
    additional_message: Optional[str] = None
    reply_to: Optional[List[str]] = None,


class EmailListResponse(BaseModel):
    """邮件列表响应模型"""
    emails: List[EmailModel]
    total: int
    page: int
    page_size: int
    total_pages: int


class EmailForwardModel(BaseModel):
    """邮件转发记录模型"""
    id: Optional[int] = None
    email_id: int
    to_addresses: List[str]
    cc_addresses: Optional[List[str]] = None
    bcc_addresses: Optional[List[str]] = None
    additional_message: Optional[str] = None
    forward_status: str = "pending"  # pending, sent, failed
    error_message: Optional[str] = None
    forwarded_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    def to_db_dict(self) -> Dict[str, Any]:
        """转换为数据库存储格式"""
        data = {
            'email_id': self.email_id,
            'to_addresses': json.dumps(self.to_addresses, ensure_ascii=False),
            'cc_addresses': json.dumps(self.cc_addresses, ensure_ascii=False) if self.cc_addresses else None,
            'bcc_addresses': json.dumps(self.bcc_addresses, ensure_ascii=False) if self.bcc_addresses else None,
            'additional_message': self.additional_message,
            'forward_status': self.forward_status,
            'error_message': self.error_message,
            'forwarded_at': self.forwarded_at
        }
        if self.id:
            data['id'] = self.id
        return data

    @classmethod
    def from_db_dict(cls, data: Dict[str, Any]) -> 'EmailForwardModel':
        """从数据库记录创建模型"""
        forward_data = data.copy()

        # 解析JSON字段
        if forward_data.get('to_addresses'):
            forward_data['to_addresses'] = json.loads(
                forward_data['to_addresses'])
        if forward_data.get('cc_addresses'):
            forward_data['cc_addresses'] = json.loads(
                forward_data['cc_addresses'])
        if forward_data.get('bcc_addresses'):
            forward_data['bcc_addresses'] = json.loads(
                forward_data['bcc_addresses'])

        return cls(**forward_data)


class EmailDetailResponse(BaseModel):
    """邮件详情响应模型"""
    email: EmailModel
    attachments: List[AttachmentModel]
    forwards: List[EmailForwardModel]


# 为了兼容性创建别名
EmailForward = EmailForwardModel


class EmailSyncStats(BaseModel):
    """邮件同步统计模型"""
    total_processed: int = 0
    new_emails: int = 0
    duplicates_skipped: int = 0
    rule_skipped: int = 0
    errors: int = 0
    sync_time: Optional[datetime] = None
    last_message_id: Optional[str] = None
