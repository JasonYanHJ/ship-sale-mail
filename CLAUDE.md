# 邮箱微服务技术文档

## 项目概述

基于 FastAPI 框架实现的邮箱微服务，提供以下核心功能：

1. 定期读取网易企业邮箱新邮件，保存到 MariaDB 并下载附件
2. 邮件转发功能，保持原始邮件格式
3. RESTful API 接口，支持邮件查询、转发等操作
4. 异步任务调度，支持定时同步和手动触发

## 技术架构

### 技术栈

- **应用框架**: FastAPI (异步 Web 框架)
- **邮箱协议**: IMAP (读取) + SMTP (发送)
- **邮箱服务**: 网易企业邮箱 (imap.qiye.163.com / smtp.qiye.163.com)
- **数据库**: MariaDB (支持完整 Unicode 字符集 utf8mb4)
- **任务调度**: APScheduler (AsyncIOScheduler)
- **核心依赖**:
  - fastapi[standard]==0.115.0 + uvicorn[standard]==0.32.0 (Web 服务)
  - aiomysql==0.2.0 + PyMySQL\==1.1.0 (异步/同步数据库操作)
  - imapclient==3.0.1 (IMAP 客户端)
  - smtplib + email (SMTP 发送和邮件处理，Python 标准库)
  - pydantic-settings==2.1.0 + python-dotenv\==1.0.0 (配置管理)
  - APScheduler==3.10.4 (定时任务调度)
  - pydantic==2.5.0 (数据验证和序列化)

## 环境变量配置 (.env)

```
# 邮箱配置
EMAIL_USERNAME=your_email@company.com
EMAIL_PASSWORD=your_password
IMAP_SERVER=imap.qiye.163.com
IMAP_PORT=993
SMTP_SERVER=smtp.qiye.163.com
SMTP_PORT=465

# 数据库配置
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=password
DB_NAME=mail_service

# 文件存储
ATTACHMENT_PATH=/path/to/attachments

# 系统配置
MAIL_CHECK_INTERVAL=300  # 秒，检查邮件频率

# 日志配置
LOG_LEVEL=INFO           # 日志级别
LOG_FILE=               # 日志文件路径（可选）

# API配置
API_HOST=0.0.0.0        # API服务绑定主机
API_PORT=8000           # API服务端口
DEBUG=false             # 调试模式

# CORS配置
CORS_ORIGINS=http://localhost:5173,http://example.com  # 允许的跨域来源，逗号分隔
```

## 数据库设计

注意：数据表由 Laravel 主服务创建和管理，本微服务仅进行数据读写操作

### emails 表

```php
Schema::create('emails', function (Blueprint $table) {
    $table->id();

    // 邮件唯一标识，用于去重
    $table->string('message_id', 255)->unique()->comment('邮件唯一标识，用于去重');

    $table->text('subject')->nullable();
    $table->string('sender', 255)->nullable();

    // JSON格式存储多个收件人、抄送人、密送人
    $table->text('recipients')->nullable()->comment('JSON格式存储多个收件人');
    $table->text('cc')->nullable()->comment('JSON格式存储抄送人');
    $table->text('bcc')->nullable()->comment('JSON格式存储密送人');

    $table->longText('content_text')->nullable();
    $table->longText('content_html')->nullable();

    $table->dateTime('date_sent')->nullable();
    $table->dateTime('date_received')->useCurrent(); // DEFAULT CURRENT_TIMESTAMP

    // 原始邮件头
    $table->longText('raw_headers')->nullable()->comment('原始邮件头');

    $table->timestamps();

    // 索引
    $table->index('message_id', 'idx_message_id');
    $table->index('date_received', 'idx_date_received');
    $table->index('sender', 'idx_sender');
});
Schema::table('emails', function (Blueprint $table) {
    $table->foreignId('dispatcher_id')
        ->nullable()
        ->constrained('users')
        ->onDelete('no action');
});
Schema::table('emails', function (Blueprint $table) {
    $table->string('from')->nullable()->comment('询价邮件来源系统');
    $table->string('type')->nullable()->comment('询价邮件类型');
});
```

### attachments 表

```php
Schema::create('attachments', function (Blueprint $table) {
    $table->id();

    // 外键关联到 emails 表
    $table->foreignId('email_id')
        ->constrained('emails')
        ->onDelete('cascade');

    $table->string('original_filename', 255)->nullable();
    $table->string('stored_filename', 255)->nullable();
    $table->string('file_path', 500)->nullable();
    $table->bigInteger('file_size')->nullable();
    $table->string('content_type', 100)->nullable();

    // Content-Disposition类型(如attachment/inline/form-data等)
    $table->string('content_disposition_type', 50)->nullable();

    $table->timestamps();

    // 索引
    $table->index('email_id', 'idx_email_id');
});

// 后续补充字段
Schema::table('attachments', function (Blueprint $table) {
    $table->string('content_id', 255)->nullable();
    $table->index('content_id', 'idx_content_id');
});
Schema::table('attachments', function (Blueprint $table) {
    $table->json('extra')->nullable();
});
```

### email_forwards 表

```php
Schema::create('email_forwards', function (Blueprint $table) {
    $table->id();

    // 外键关联到 emails 表
    $table->foreignId('email_id')
        ->constrained('emails')
        ->onDelete('cascade');

    $table->text('to_addresses');
    $table->text('cc_addresses')->nullable();
    $table->text('bcc_addresses')->nullable();
    $table->text('additional_message')->nullable();
    $table->enum('forward_status', ['pending', 'sent', 'failed'])->default('pending');
    $table->text('error_message')->nullable();
    $table->timestamp('forwarded_at')->useCurrent();
    $table->timestamps();

    // 索引
    $table->index('email_id', 'idx_email_id');
    $table->index('forwarded_at', 'idx_forwarded_at');
    $table->index('forward_status', 'idx_forward_status');
});
```

### 系统架构

- **配置层**: 基于 pydantic-settings 的环境变量配置管理
- **数据库层**: aiomysql 异步连接池 + pymysql 同步操作，支持事务管理
- **服务层**: 邮件读取、转发、文件存储等核心业务服务
- **API 层**: FastAPI RESTful 接口 + CORS 中间件支持跨域访问
- **任务层**: APScheduler 异步任务调度
- **工具层**: 邮件解析、日志管理等公共组件

## 项目结构

```
src/
├── main.py                 # FastAPI应用入口，生命周期管理
├── config/
│   └── settings.py         # pydantic-settings配置管理
├── models/
│   ├── __init__.py
│   ├── database.py         # 异步连接池 + 同步表创建
│   └── email_models.py     # Pydantic数据模型
├── services/
│   ├── __init__.py
│   ├── email_reader.py     # IMAP邮件读取服务
│   ├── email_forwarder.py  # SMTP邮件转发服务
│   ├── file_storage.py     # 异步文件存储服务
│   ├── email_database.py   # 邮件数据库操作服务
│   └── email_sync.py       # 邮件同步服务
├── api/
│   ├── __init__.py
│   └── email_routes.py     # API路由定义
├── tasks/
│   ├── __init__.py
│   └── scheduler.py        # 异步任务调度器
└── utils/
    ├── __init__.py
    ├── email_parser.py     # MIME邮件解析工具
    └── logger.py           # 统一日志配置
```

## 核心技术实现

### 1. 配置管理 (config/settings.py)

- **技术选型**: pydantic-settings + python-dotenv
- **特性**: 类型安全的环境变量读取，支持默认值和验证
- **配置分类**: 邮箱配置、数据库配置、文件存储配置、系统配置

### 2. 数据库层 (models/)

- **连接池**: aiomysql 异步连接池 (minsize=1, maxsize=10)
- **字符集**: utf8mb4，支持完整 Unicode 字符
- **事务支持**: 自动回滚机制，确保数据完整性
- **数据模型**: Pydantic BaseModel，支持 JSON 序列化和验证
- **表检查**: 启动时检查必需表（emails、attachments、email_forwards）是否存在

### 3. 邮件读取服务 (services/email_reader.py)

- **IMAP 连接**: 基于 imapclient 的 SSL 连接管理
- **网易兼容**: 支持网易企业邮箱的特殊 ID 命令
- **上下文管理**: 自动连接管理和资源清理
- **错误处理**: 完整的异常处理和日志记录

### 4. 邮件解析工具 (utils/email_parser.py)

- **MIME 解码**: RFC2047 标准，支持中文主题和附件名
- **多部分邮件**: 文本/HTML/附件的完整解析
- **字符编码**: UTF-8、GB2312 等多种编码支持
- **错误容错**: 编码失败时的降级处理机制

### 5. 文件存储服务 (services/file_storage.py)

- **同步文件操作**: 基于 Python 标准库的文件操作 (注意：实际未使用 aiofiles)
- **智能命名**: YYYYMMDDHHMM\_邮件 ID_UUID.扩展名格式
- **UUID 策略**: 解决中文文件名在容器环境中的兼容性问题
- **原始信息**: 数据库中保留完整的原始文件名信息

### 6. 数据库服务 (services/email_database.py)

- **异步操作**: 基于 aiomysql 连接池的高性能数据访问
- **事务管理**: 邮件和附件的原子性保存
- **智能去重**: 基于 message_id 的自动去重机制
- **JSON 处理**: 自动处理 recipients、cc、bcc 等 JSON 字段

### 7. 邮件转发服务 (services/email_forwarder.py)

- **SMTP 连接**: 基于 smtplib 的 SSL 安全连接
- **格式保持**: 转发时保持原始邮件头和附件类型
- **多收件人**: 支持 to、cc、bcc 多种收件人模式
- **状态追踪**: pending/sent/failed 状态管理

### 8. 任务调度器 (tasks/scheduler.py)

- **异步调度**: 基于 APScheduler 的 AsyncIOScheduler
- **并发控制**: max_instances=1 确保单任务执行
- **错过处理**: misfire_grace_time=60 秒宽限期
- **事件监听**: 任务执行成功/失败事件处理

### 9. 邮件同步服务 (services/email_sync.py)

- **增量同步**: 只处理新邮件，避免重复处理
- **状态监控**: 实时同步状态和统计信息
- **错误恢复**: IMAP 连接断开重连机制

### 10. 应用生命周期管理 (main.py)

- **启动序列**: 目录检查 -> 数据库表检查 -> 连接池初始化 -> 调度器启动
- **优雅关闭**: 停止调度器 -> 关闭数据库连接池 -> 清理资源
- **错误处理**: 关键服务启动失败时的降级处理
- **健康检查**: 提供/health 端点用于服务监控

## API 接口设计

### 邮件相关

- `POST /emails/{email_id}/forward` - 转发邮件 (本微服务实现)

### 系统管理

- `GET /health` - 健康检查
- `POST /sync/manual` - 手动触发邮件同步
- `GET /sync/status` - 获取邮件同步状态
- `GET /scheduler/status` - 获取调度器状态

### 转发 API 请求格式

```json
POST /emails/{email_id}/forward
{
  "to_addresses": ["recipient@example.com"],
  "cc_addresses": ["cc@example.com"],     // 可选
  "bcc_addresses": ["bcc@example.com"],   // 可选
  "additional_message": "转发说明"         // 可选
}
```

## 中间件配置

### CORS 跨域配置

通过环境变量 `CORS_ORIGINS` 配置允许的跨域来源，多个来源用逗号分隔：

```python
# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,  # 从环境变量读取
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

环境变量配置示例：

```
CORS_ORIGINS=http://localhost:5173,http://example.com
```

## 关键技术点

1. **邮件去重**: 使用 Message-ID 作为唯一标识
2. **附件命名**: `YYYYMMDDHHMM_邮件ID_UUID.扩展名` (使用 UUID 避免中文文件名兼容性问题)
3. **原始邮件头保留**: 转发时保持完整的邮件头信息
4. **异步处理**: 使用 FastAPI 的异步特性处理 IO 密集操作
5. **错误恢复**: IMAP 连接断开重连，邮件处理失败重试
6. **安全性**: 邮箱密码加密存储，API 访问控制

## 注意事项

1. **IMAP 连接管理**: 合理控制连接数，避免服务器限制
2. **大附件处理**: 设置文件大小限制，流式下载
3. **邮件编码**: 正确处理各种字符编码
4. **时区处理**: 邮件时间的时区转换
5. **内存管理**: 大邮件处理时的内存控制

## 已知技术限制

1. **文件存储**: 当前使用同步文件操作，未使用 aiofiles 异步库
2. **微服务职责**: 邮件查询、详情、下载等 API 端点由主服务负责实现
3. **配置验证**: 环境变量缺失时的错误提示需要改进

## 系统特性

### 性能特性

- **异步架构**: 全栈异步处理，支持高并发请求
- **连接池管理**: 数据库连接池优化，避免连接泄漏
- **增量同步**: 智能增量同步，减少重复处理
- **流式处理**: 大附件的流式下载和存储

### 可靠性特性

- **事务保证**: 邮件和附件的原子性操作
- **自动去重**: 基于 message_id 的智能去重机制
- **错误恢复**: 连接断开自动重连，任务失败重试
- **状态监控**: 实时同步状态和系统健康检查

### 安全特性

- **SSL 连接**: IMAP 和 SMTP 均使用 SSL 加密连接
- **参数验证**: 完整的输入参数验证和错误处理
- **文件安全**: 安全的文件命名和路径管理
- **日志审计**: 详细的操作日志和错误追踪

### 扩展性特性

- **模块化设计**: 清晰的分层架构，便于功能扩展
- **配置驱动**: 环境变量配置，支持不同部署环境
- **API 标准**: RESTful API 设计，便于集成和扩展
- **数据模型**: 标准化的数据模型，支持功能演进

## 运维要点

### 监控指标

- 数据库连接池状态
- 邮件同步成功率和延迟
- 附件存储空间使用
- API 响应时间和错误率

### 日志管理

- 统一的日志格式和级别
- 邮件操作的详细日志
- 错误追踪和性能分析
- 定时任务执行记录

### 部署要求

- Python 3.9+ 环境
- MariaDB 10.3+ 数据库
- 足够的磁盘空间存储附件
- 网易企业邮箱访问权限

### 容器化部署

- **Docker 支持**: 项目包含完整的 Dockerfile 配置
- **基础镜像**: python:3.9
- **时区设置**: Asia/Shanghai (东八区)
- **端口映射**: 容器内 80 端口，可映射到主机端口
- **启动命令**: uvicorn 服务器，绑定所有网络接口
