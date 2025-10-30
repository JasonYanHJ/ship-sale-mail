from typing import Dict, Any, List
import time

from ..models.rule_models import EmailRule, ConditionGroup, RuleCondition, GroupLogic, FieldType, OperatorType
from .field_extractors import FieldExtractorFactory
from .operator_handlers import OperatorHandlerFactory
from ..utils.logger import get_logger

logger = get_logger("condition_evaluator")


class ConditionEvaluator:
    """条件评估器，负责评估规则条件的匹配逻辑"""

    def __init__(self):
        """初始化条件评估器"""
        self.field_extractor_factory = FieldExtractorFactory
        self.operator_handler_factory = OperatorHandlerFactory

    def evaluate_condition(self, condition: RuleCondition, email_data: Dict[str, Any]) -> bool:
        """
        评估单个条件

        Args:
            condition: 规则条件
            email_data: 邮件数据

        Returns:
            条件匹配结果
        """
        try:
            # 1. 提取字段值
            field_value = self._extract_field_value(
                condition.field_type, email_data)

            # 2. 执行操作符匹配
            result = self._execute_operator_match(
                condition.operator,
                field_value,
                condition.match_value,
                condition.case_sensitive
            )

            logger.debug(
                f"条件评估: {condition.field_type.value} {condition.operator.value} "
                f"'{condition.match_value}' = {result}"
            )

            return result

        except Exception as e:
            logger.error(f"条件评估失败: {e}, condition_id={condition.id}")
            # 条件评估失败时返回False，避免影响整体规则执行
            return False

    def evaluate_group(self, group: ConditionGroup, email_data: Dict[str, Any]) -> bool:
        """
        评估条件组

        Args:
            group: 条件组
            email_data: 邮件数据

        Returns:
            条件组匹配结果
        """
        try:
            if not group.conditions:
                logger.warning(f"条件组为空: group_id={group.id}")
                return True  # 空条件组认为匹配

            logger.debug(
                f"评估条件组: {group.group_logic.value}, {len(group.conditions)} 个条件")

            # 根据逻辑类型进行短路评估
            if group.group_logic == GroupLogic.AND:
                return self._evaluate_and_conditions(group.conditions, email_data)
            elif group.group_logic == GroupLogic.OR:
                return self._evaluate_or_conditions(group.conditions, email_data)
            else:
                logger.error(f"不支持的条件组逻辑: {group.group_logic}")
                return False

        except Exception as e:
            logger.error(f"条件组评估失败: {e}, group_id={group.id}")
            return False

    def evaluate_rule(self, rule: EmailRule, email_data: Dict[str, Any]) -> bool:
        """
        评估规则

        Args:
            rule: 邮件规则
            email_data: 邮件数据

        Returns:
            规则匹配结果
        """
        try:
            if not rule.condition_groups:
                logger.warning(f"规则无条件组: rule_id={rule.id}")
                return True  # 无条件组的规则认为匹配

            start_time = time.time()

            logger.debug(
                f"评估规则: {rule.name}, 全局逻辑={rule.global_group_logic.value}, "
                f"{len(rule.condition_groups)} 个条件组"
            )

            # 按条件组顺序评估
            group_results = []
            for group in rule.condition_groups:
                group_result = self.evaluate_group(group, email_data)
                group_results.append(group_result)

                # 全局短路评估优化
                if rule.global_group_logic == GroupLogic.AND and not group_result:
                    logger.debug(f"规则短路评估: AND逻辑遇到False，提前返回")
                    break
                elif rule.global_group_logic == GroupLogic.OR and group_result:
                    logger.debug(f"规则短路评估: OR逻辑遇到True，提前返回")
                    break

            # 计算最终结果
            if rule.global_group_logic == GroupLogic.AND:
                result = all(group_results)
            elif rule.global_group_logic == GroupLogic.OR:
                result = any(group_results)
            else:
                logger.error(f"不支持的全局逻辑: {rule.global_group_logic}")
                result = False

            execution_time = time.time() - start_time
            logger.debug(
                f"规则评估完成: {rule.name} = {result}, "
                f"耗时: {execution_time:.3f}秒"
            )

            return result

        except Exception as e:
            logger.error(f"规则评估失败: {e}, rule_id={rule.id}")
            return False

    def _extract_field_value(self, field_type: FieldType, email_data: Dict[str, Any]) -> str:
        """
        提取字段值

        Args:
            field_type: 字段类型
            email_data: 邮件数据

        Returns:
            字段值
        """
        try:
            field_value = self.field_extractor_factory.extract_field(
                field_type.value, email_data
            )

            if field_value is None:
                field_value = ""

            logger.debug(
                f"字段提取: {field_type.value} = '{field_value[:100]}{'...' if len(field_value) > 100 else ''}'")
            return field_value

        except Exception as e:
            logger.error(f"字段提取失败: {e}, field_type={field_type.value}")
            return ""

    def _execute_operator_match(self, operator: OperatorType, field_value: str,
                                match_value: str, case_sensitive: bool) -> bool:
        """
        执行操作符匹配

        Args:
            operator: 操作符类型
            field_value: 字段值
            match_value: 匹配值
            case_sensitive: 是否大小写敏感

        Returns:
            匹配结果
        """
        try:
            result = self.operator_handler_factory.execute_operation(
                operator.value, field_value, match_value, case_sensitive
            )

            return result

        except Exception as e:
            logger.error(
                f"操作符匹配失败: {e}, operator={operator.value}, "
                f"field_value='{field_value[:50]}', match_value='{match_value}'"
            )
            return False

    def _evaluate_and_conditions(self, conditions: List[RuleCondition],
                                 email_data: Dict[str, Any]) -> bool:
        """
        评估AND条件（短路评估）

        Args:
            conditions: 条件列表
            email_data: 邮件数据

        Returns:
            AND条件结果
        """
        for condition in conditions:
            result = self.evaluate_condition(condition, email_data)
            if not result:
                logger.debug(f"AND条件短路: 条件 {condition.id} 为False")
                return False

        logger.debug(f"AND条件全部通过: {len(conditions)} 个条件")
        return True

    def _evaluate_or_conditions(self, conditions: List[RuleCondition],
                                email_data: Dict[str, Any]) -> bool:
        """
        评估OR条件（短路评估）

        Args:
            conditions: 条件列表
            email_data: 邮件数据

        Returns:
            OR条件结果
        """
        for condition in conditions:
            result = self.evaluate_condition(condition, email_data)
            if result:
                logger.debug(f"OR条件短路: 条件 {condition.id} 为True")
                return True

        logger.debug(f"OR条件全部失败: {len(conditions)} 个条件")
        return False

    def evaluate_rules_batch(self, rules: List[EmailRule], email_data: Dict[str, Any]) -> Dict[str, bool]:
        """
        批量评估多个规则

        Args:
            rules: 规则列表
            email_data: 邮件数据

        Returns:
            规则名称到匹配结果的字典
        """
        results = {}

        try:
            logger.debug(f"开始批量评估 {len(rules)} 条规则")

            for rule in rules:
                try:
                    result = self.evaluate_rule(rule, email_data)
                    results[rule.name] = result

                    if result:
                        logger.debug(f"规则匹配成功: {rule.name}")

                        # 如果规则设置了stop_on_match，停止后续规则评估
                        if rule.stop_on_match:
                            logger.debug(
                                f"规则 {rule.name} 设置了stop_on_match，停止后续评估")
                            break

                except Exception as e:
                    logger.error(f"规则评估异常: {rule.name}, {e}")
                    results[rule.name] = False

            matched_count = sum(1 for result in results.values() if result)
            logger.debug(f"批量评估完成: {matched_count}/{len(results)} 条规则匹配")

            return results

        except Exception as e:
            logger.error(f"批量评估失败: {e}")
            return results

    def get_evaluation_statistics(self) -> Dict[str, Any]:
        """
        获取评估统计信息（简化版，用于监控）

        Returns:
            统计信息字典
        """
        # 这里可以添加更复杂的统计逻辑
        # 例如：平均评估时间、成功率、错误率等
        return {
            "evaluator_status": "active",
            "supported_field_types": self.field_extractor_factory.get_supported_fields(),
            "supported_operators": self.operator_handler_factory.get_supported_operators()
        }
