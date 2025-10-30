from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import time

from ..models.rule_models import RuleAction, ActionType, RuleResult
from ..utils.logger import get_logger

logger = get_logger("action_executor")


class ActionHandler(ABC):
    """动作处理器抽象基类"""

    @abstractmethod
    async def execute(self, action: RuleAction, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行动作

        Args:
            action: 规则动作
            email_data: 邮件数据

        Returns:
            执行结果字典
        """
        pass

    def _create_result(self, success: bool, message: str, **kwargs) -> Dict[str, Any]:
        """
        创建标准化的执行结果

        Args:
            success: 执行是否成功
            message: 结果消息
            **kwargs: 其他结果数据

        Returns:
            标准化结果字典
        """
        result = {
            'success': success,
            'message': message,
            'timestamp': time.time()
        }
        result.update(kwargs)
        return result


class SkipActionHandler(ActionHandler):
    """跳过邮件处理动作处理器"""

    async def execute(self, action: RuleAction, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行跳过邮件处理动作

        Args:
            action: 规则动作
            email_data: 邮件数据

        Returns:
            执行结果
        """
        try:
            message_id = email_data.get('message_id', 'unknown')

            logger.debug(f"执行跳过动作: message_id={message_id}")

            # 跳过动作的执行逻辑
            # 在规则引擎的上下文中，这个动作会告诉系统跳过对这封邮件的后续处理
            skip_reason = "规则匹配，跳过邮件处理"

            # 如果action_config包含跳过原因，使用自定义原因
            if action.action_config and isinstance(action.action_config, dict):
                skip_reason = action.action_config.get('reason', skip_reason)

            logger.debug(f"邮件跳过处理: {skip_reason}")

            return self._create_result(
                success=True,
                message=f"邮件跳过处理: {skip_reason}",
                action_type="skip",
                skip_reason=skip_reason,
                should_skip=True  # 关键标志：告诉调用者应该跳过后续处理
            )

        except Exception as e:
            logger.error(f"跳过动作执行失败: {e}")
            return self._create_result(
                success=False,
                message=f"跳过动作执行失败: {str(e)}",
                action_type="skip",
                error=str(e)
            )


class SetFieldActionHandler(ActionHandler):
    """设置邮件字段动作处理器"""

    async def execute(self, action: RuleAction, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行设置邮件字段动作

        Args:
            action: 规则动作
            email_data: 邮件数据（会被直接修改）

        Returns:
            执行结果
        """
        try:
            message_id = email_data.get('message_id', 'unknown')

            # 解析动作参数
            field_name, field_value = self._parse_set_field_action(action)

            # 记录原始值
            old_value = email_data.get(field_name)

            logger.debug(
                f"执行设置字段动作: message_id={message_id}, {field_name}: {old_value} -> {field_value}")

            # 直接修改email_data字典
            email_data[field_name] = field_value

            logger.debug(
                f"字段设置成功: message_id={message_id}, {field_name}={field_value}")

            return self._create_result(
                success=True,
                message=f"字段设置成功: {field_name}={field_value}",
                action_type="set_field",
                field_name=field_name,
                field_value=field_value,
                old_value=old_value,
                field_modified=True
            )

        except ValueError as e:
            logger.error(f"字段设置参数错误: {e}")
            return self._create_result(
                success=False,
                message=f"字段设置参数错误: {str(e)}",
                action_type="set_field",
                error=str(e)
            )
        except Exception as e:
            logger.error(f"设置字段动作执行失败: {e}")
            return self._create_result(
                success=False,
                message=f"设置字段动作执行失败: {str(e)}",
                action_type="set_field",
                error=str(e)
            )

    def _parse_set_field_action(self, action: RuleAction) -> tuple[str, Any]:
        """
        解析设置字段动作的参数

        Args:
            action: 规则动作

        Returns:
            (字段名, 字段值)元组

        Raises:
            ValueError: 参数格式错误
        """
        action_config = action.action_config

        if not action_config:
            raise ValueError("设置字段动作缺少action_config参数")

        if not isinstance(action_config, dict):
            raise ValueError(
                f"action_config应为字典类型，实际类型: {type(action_config)}")

        # 提取字段名和字段值
        field_name = action_config.get('field_name')
        field_value = action_config.get('field_value')

        if not field_name:
            raise ValueError("action_config中缺少field_name")

        return field_name, field_value


class ActionExecutor:
    """动作执行器，管理所有动作处理器"""

    def __init__(self):
        """初始化动作执行器"""
        self._handlers = {
            ActionType.SKIP: SkipActionHandler(),
            ActionType.SET_FIELD: SetFieldActionHandler(),
        }
        self._execution_stats = {
            'total_executions': 0,
            'successful_executions': 0,
            'failed_executions': 0,
            'skip_actions': 0,
            'set_field_actions': 0
        }

    async def execute_action(self, action: RuleAction, email_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单个动作

        Args:
            action: 规则动作
            email_data: 邮件数据

        Returns:
            执行结果
        """
        try:
            start_time = time.time()

            # 获取对应的处理器
            handler = self._handlers.get(action.action_type)
            if not handler:
                logger.error(f"不支持的动作类型: {action.action_type}")
                return self._create_error_result(
                    f"不支持的动作类型: {action.action_type}",
                    action.action_type
                )

            logger.debug(
                f"执行动作: {action.action_type.value}, action_id={action.id}")

            # 执行动作
            result = await handler.execute(action, email_data)

            # 更新统计信息
            execution_time = time.time() - start_time
            self._update_stats(action.action_type,
                               result.get('success', False))

            # 添加执行时间
            result['execution_time'] = execution_time
            result['action_id'] = action.id

            logger.debug(
                f"动作执行完成: {action.action_type.value}, "
                f"success={result.get('success')}, time={execution_time:.3f}s"
            )

            return result

        except Exception as e:
            logger.error(f"动作执行异常: {e}, action_id={action.id}")
            self._update_stats(action.action_type, False)
            return self._create_error_result(f"动作执行异常: {str(e)}", action.action_type)

    async def execute_actions_batch(self, actions: List[RuleAction],
                                    email_data: Dict[str, Any]) -> RuleResult:
        """
        批量执行动作

        Args:
            actions: 动作列表
            email_data: 邮件数据

        Returns:
            规则执行结果
        """
        try:
            start_time = time.time()
            action_results = []
            should_skip = False

            logger.debug(f"开始批量执行动作: {len(actions)} 个动作")

            for action in actions:
                try:
                    result = await self.execute_action(action, email_data)
                    action_results.append(result)

                    # 检查是否需要跳过后续处理
                    if result.get('should_skip', False):
                        should_skip = True
                        logger.debug(f"动作 {action.id} 设置了跳过标志，停止后续动作执行")
                        break

                except Exception as e:
                    logger.error(f"单个动作执行失败: {e}, action_id={action.id}")
                    error_result = self._create_error_result(
                        f"动作执行失败: {str(e)}",
                        action.action_type,
                        action.id
                    )
                    action_results.append(error_result)

            # 计算总体结果
            total_time = time.time() - start_time
            successful_actions = sum(
                1 for r in action_results if r.get('success', False))
            failed_actions = len(action_results) - successful_actions

            # 创建规则执行结果
            rule_result = RuleResult(
                should_skip=should_skip,
                total_time=total_time,
                success=failed_actions == 0  # 所有动作成功才算成功
            )

            # 将动作执行中的错误添加到错误列表
            for action_result in action_results:
                if not action_result.get('success', True) and action_result.get('message'):
                    rule_result.add_error(action_result['message'])

            logger.debug(
                f"批量动作执行完成: {successful_actions}/{len(action_results)} 成功, "
                f"跳过邮件={should_skip}, 耗时={total_time:.3f}s"
            )

            return rule_result

        except Exception as e:
            logger.error(f"批量动作执行失败: {e}")

            # 创建错误结果
            rule_result = RuleResult(
                should_skip=False,
                total_time=0,
                success=False
            )
            rule_result.add_error(f"批量动作执行失败: {str(e)}")
            return rule_result

    def _create_error_result(self, message: str, action_type: ActionType,
                             action_id: Optional[int] = None) -> Dict[str, Any]:
        """
        创建错误结果

        Args:
            message: 错误消息
            action_type: 动作类型
            action_id: 动作ID

        Returns:
            错误结果字典
        """
        return {
            'success': False,
            'message': message,
            'action_type': action_type.value if action_type else 'unknown',
            'action_id': action_id,
            'timestamp': time.time()
        }

    def _update_stats(self, action_type: ActionType, success: bool):
        """
        更新执行统计信息

        Args:
            action_type: 动作类型
            success: 是否成功
        """
        self._execution_stats['total_executions'] += 1

        if success:
            self._execution_stats['successful_executions'] += 1
        else:
            self._execution_stats['failed_executions'] += 1

        # 更新具体动作类型统计
        if action_type == ActionType.SKIP:
            self._execution_stats['skip_actions'] += 1
        elif action_type == ActionType.SET_FIELD:
            self._execution_stats['set_field_actions'] += 1

    def get_supported_actions(self) -> List[str]:
        """
        获取支持的动作类型列表

        Returns:
            支持的动作类型列表
        """
        return [action_type.value for action_type in self._handlers.keys()]

    def get_execution_statistics(self) -> Dict[str, Any]:
        """
        获取执行统计信息

        Returns:
            统计信息字典
        """
        return self._execution_stats.copy()

    def reset_statistics(self):
        """重置执行统计信息"""
        for key in self._execution_stats:
            self._execution_stats[key] = 0

        logger.debug("动作执行器统计信息已重置")


# 全局动作执行器实例
action_executor = ActionExecutor()
