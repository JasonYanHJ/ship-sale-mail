import time
from typing import List, Dict, Any, Optional
import asyncio

from ..models.rule_models import EmailRule, RuleResult
from ..services.rules_database import RulesDatabaseService
from ..services.condition_evaluator import ConditionEvaluator
from ..services.action_executor import ActionExecutor
from ..services.error_handler import ErrorHandler
from ..utils.logger import get_logger

logger = get_logger("rule_engine")


class RuleEngine:
    """
    邮件规则引擎主类

    整合规则数据库服务、条件评估器、动作执行器和错误处理器，
    提供完整的规则执行功能。
    """

    def __init__(self):
        """
        初始化规则引擎
        """
        self.rules_database = RulesDatabaseService()
        self.condition_evaluator = ConditionEvaluator()
        self.action_executor = ActionExecutor()
        self.error_handler = ErrorHandler()

        # 执行统计
        self.execution_statistics = {
            'total_emails_processed': 0,
            'total_rules_executed': 0,
            'total_rules_matched': 0,
            'total_emails_skipped': 0,
            'total_fields_modified': 0,
            'total_execution_time': 0.0,
            'average_execution_time': 0.0,
            'slowest_rule_time': 0.0,
            'slowest_rule_name': '',
            'errors_count': 0
        }

        logger.info("规则引擎初始化完成")

    async def apply_rules(self, email_data: Dict[str, Any],
                          rules: Optional[List[EmailRule]] = None) -> RuleResult:
        """
        对邮件应用规则

        Args:
            email_data: 邮件数据字典
            rules: 规则列表，如果为None则从数据库加载所有激活规则

        Returns:
            规则执行结果
        """
        start_time = time.time()

        try:
            # 清空错误处理器
            self.error_handler.clear_errors()

            message_id = email_data.get('message_id', 'unknown')
            logger.debug(f"开始对邮件应用规则: message_id={message_id}")

            # 如果没有提供规则，从数据库加载
            if rules is None:
                try:
                    rules = await self.rules_database.get_all_active_rules()
                    logger.debug(f"从数据库加载了 {len(rules)} 条激活规则")
                except Exception as e:
                    self.error_handler.handle_database_error("加载激活规则", e)
                    return self._create_error_result("规则加载失败", start_time)

            if not rules:
                logger.debug("没有找到激活的规则，跳过规则处理")
                return self._create_empty_result(start_time)

            # 按优先级排序规则（从高到低）
            sorted_rules = sorted(rules, key=lambda x: (
                x.priority, x.id), reverse=True)

            # 初始化结果
            final_result = RuleResult()
            rules_executed = 0
            rules_matched = 0

            # 逐个执行规则
            for rule in sorted_rules:
                try:
                    rule_start_time = time.time()

                    logger.debug(
                        f"评估规则: {rule.name} (ID: {rule.id}, 优先级: {rule.priority})")

                    # 评估规则条件
                    rule_matches = await self._evaluate_rule_conditions(rule, email_data)
                    rules_executed += 1

                    if rule_matches:
                        rules_matched += 1
                        final_result.add_matched_rule(rule.name)

                        logger.debug(f"规则匹配: {rule.name}, 开始执行动作")

                        # 执行规则动作
                        action_result = await self._execute_rule_actions(rule, email_data)

                        # 合并动作结果
                        self._merge_action_result(final_result, action_result)

                        # 记录规则执行时间
                        rule_execution_time = time.time() - rule_start_time
                        self._update_rule_performance(
                            rule.name, rule_execution_time)

                        # 检查是否需要停止后续规则执行
                        if rule.stop_on_match:
                            logger.debug(
                                f"规则 {rule.name} 设置了 stop_on_match，停止后续规则执行")
                            break

                        # 如果动作设置了跳过标志，也停止后续规则执行
                        if final_result.should_skip:
                            logger.debug(f"规则 {rule.name} 的动作设置了跳过标志，停止后续规则执行")
                            break

                    else:
                        logger.debug(f"规则不匹配: {rule.name}")

                except Exception as e:
                    # 处理单个规则执行错误
                    should_continue = self.error_handler.handle_rule_error(
                        rule.name, rule.id, e)
                    if not should_continue:
                        logger.error(f"规则 {rule.name} 执行失败，停止后续规则处理")
                        break

            # 完善执行结果
            total_time = time.time() - start_time
            final_result.total_time = total_time
            final_result.success = True  # 只要没有严重错误就算成功

            # 将错误处理器中的错误添加到结果中
            final_result.error_messages.extend(self.error_handler.get_errors())

            # 检查是否有严重错误
            if self.error_handler.has_critical_errors():
                final_result.success = False

            # 更新统计信息
            self._update_execution_statistics(
                total_time, rules_executed, rules_matched, final_result)

            logger.debug(
                f"规则引擎执行完成: message_id={message_id}, "
                f"执行规则数={rules_executed}, 匹配规则数={rules_matched}, "
                f"跳过邮件={final_result.should_skip}, 耗时={total_time:.3f}s"
            )

            return final_result

        except Exception as e:
            # 处理顶层异常
            self.error_handler.handle_system_error("规则引擎执行", e)
            return self._create_error_result(f"规则引擎执行失败: {str(e)}", start_time)

    async def _evaluate_rule_conditions(self, rule: EmailRule, email_data: Dict[str, Any]) -> bool:
        """
        评估规则条件

        Args:
            rule: 邮件规则
            email_data: 邮件数据

        Returns:
            规则是否匹配
        """
        try:
            return self.condition_evaluator.evaluate_rule(rule, email_data)
        except Exception as e:
            self.error_handler.handle_condition_error(f"规则 {rule.name}", e)
            return False

    async def _execute_rule_actions(self, rule: EmailRule, email_data: Dict[str, Any]) -> RuleResult:
        """
        执行规则动作

        Args:
            rule: 邮件规则
            email_data: 邮件数据

        Returns:
            动作执行结果
        """
        try:
            if not rule.actions:
                logger.debug(f"规则 {rule.name} 没有配置动作")
                return RuleResult(success=True)

            return await self.action_executor.execute_actions_batch(rule.actions, email_data)

        except Exception as e:
            self.error_handler.handle_action_error(f"规则 {rule.name} 的动作", e)
            # 返回失败的结果
            result = RuleResult(success=False)
            result.add_error(f"动作执行失败: {str(e)}")
            return result

    def _merge_action_result(self, final_result: RuleResult, action_result: RuleResult):
        """
        合并动作执行结果到最终结果

        Args:
            final_result: 最终结果
            action_result: 动作执行结果
        """
        # 合并跳过标志（任何一个动作设置跳过就跳过）
        if action_result.should_skip:
            final_result.should_skip = True

        # 合并错误信息
        final_result.error_messages.extend(action_result.error_messages)

        # 如果动作执行失败，标记最终结果失败
        if not action_result.success:
            final_result.success = False

    def _update_rule_performance(self, rule_name: str, execution_time: float):
        """
        更新规则性能统计

        Args:
            rule_name: 规则名称
            execution_time: 执行时间
        """
        if execution_time > self.execution_statistics['slowest_rule_time']:
            self.execution_statistics['slowest_rule_time'] = execution_time
            self.execution_statistics['slowest_rule_name'] = rule_name

        # 记录慢规则警告
        if execution_time > 1.0:  # 超过1秒
            self.error_handler.add_warning(
                f"慢规则检测: {rule_name} 执行时间 {execution_time:.3f}s"
            )

    def _update_execution_statistics(self, total_time: float, rules_executed: int,
                                     rules_matched: int, result: RuleResult):
        """
        更新执行统计信息

        Args:
            total_time: 总执行时间
            rules_executed: 执行的规则数
            rules_matched: 匹配的规则数
            result: 执行结果
        """
        stats = self.execution_statistics

        stats['total_emails_processed'] += 1
        stats['total_rules_executed'] += rules_executed
        stats['total_rules_matched'] += rules_matched
        stats['total_execution_time'] += total_time

        if result.should_skip:
            stats['total_emails_skipped'] += 1

        if not result.success or result.error_messages:
            stats['errors_count'] += 1

        # 计算平均执行时间
        if stats['total_emails_processed'] > 0:
            stats['average_execution_time'] = (
                stats['total_execution_time'] / stats['total_emails_processed']
            )

    def _create_empty_result(self, start_time: float) -> RuleResult:
        """
        创建空的执行结果

        Args:
            start_time: 开始时间

        Returns:
            空的执行结果
        """
        return RuleResult(
            success=True,
            total_time=time.time() - start_time
        )

    def _create_error_result(self, error_message: str, start_time: float) -> RuleResult:
        """
        创建错误执行结果

        Args:
            error_message: 错误消息
            start_time: 开始时间

        Returns:
            错误执行结果
        """
        result = RuleResult(
            success=False,
            total_time=time.time() - start_time
        )
        result.add_error(error_message)
        return result

    async def get_execution_health(self) -> Dict[str, Any]:
        """
        获取规则引擎健康状态

        Returns:
            健康状态字典
        """
        try:
            # 检查各组件状态
            rules_count = len(await self.rules_database.get_all_active_rules())
            error_summary = self.error_handler.get_error_summary()

            health_status = {
                'status': 'healthy' if not error_summary['has_critical_errors'] else 'degraded',
                'active_rules_count': rules_count,
                'execution_statistics': self.execution_statistics.copy(),
                'error_summary': error_summary,
                'performance_metrics': {
                    'average_execution_time_ms': self.execution_statistics['average_execution_time'] * 1000,
                    'slowest_rule': {
                        'name': self.execution_statistics['slowest_rule_name'],
                        'time_ms': self.execution_statistics['slowest_rule_time'] * 1000
                    }
                }
            }

            return health_status

        except Exception as e:
            logger.error(f"获取健康状态失败: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }

    def get_execution_statistics(self) -> Dict[str, Any]:
        """
        获取执行统计信息

        Returns:
            统计信息字典
        """
        return self.execution_statistics.copy()

    def reset_statistics(self):
        """重置执行统计信息"""
        for key in self.execution_statistics:
            if isinstance(self.execution_statistics[key], (int, float)):
                self.execution_statistics[key] = 0
            elif isinstance(self.execution_statistics[key], str):
                self.execution_statistics[key] = ''

        self.error_handler.clear_errors()
        logger.info("规则引擎统计信息已重置")
