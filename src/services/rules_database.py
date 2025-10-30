from typing import List, Optional, Dict, Any
import aiomysql

from ..models.database import db_manager
from ..models.rule_models import EmailRule, ConditionGroup, RuleCondition, RuleAction
from ..utils.logger import get_logger

logger = get_logger("rules_database")


class RulesDatabaseService:
    """规则数据库服务"""

    def __init__(self):
        self.db_manager = db_manager

    async def get_all_rules(self) -> List[EmailRule]:
        """
        获取所有规则

        Returns:
            规则列表
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 获取所有规则基本信息
                    sql = """
                        SELECT * FROM email_rules 
                        ORDER BY priority DESC, id ASC
                    """
                    await cursor.execute(sql)
                    rule_rows = await cursor.fetchall()

                    rules = []
                    for rule_row in rule_rows:
                        rule = EmailRule.from_db_dict(dict(rule_row))

                        # 加载条件组和动作
                        rule.condition_groups = await self._get_condition_groups(rule.id)
                        rule.actions = await self._get_rule_actions(rule.id)

                        rules.append(rule)

                    logger.debug(f"获取到 {len(rules)} 条规则")
                    return rules

        except Exception as e:
            logger.error(f"获取所有规则失败: {e}")
            raise

    async def get_all_active_rules(self) -> List[EmailRule]:
        """
        获取所有激活的规则，按优先级从高到低排序

        Returns:
            激活的规则列表
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 只获取激活的规则
                    sql = """
                        SELECT * FROM email_rules 
                        WHERE is_active = 1 
                        ORDER BY priority DESC, id ASC
                    """
                    await cursor.execute(sql)
                    rule_rows = await cursor.fetchall()

                    rules = []
                    for rule_row in rule_rows:
                        rule = EmailRule.from_db_dict(dict(rule_row))

                        # 加载条件组和动作
                        rule.condition_groups = await self._get_condition_groups(rule.id)
                        rule.actions = await self._get_rule_actions(rule.id)

                        rules.append(rule)

                    logger.info(f"获取到 {len(rules)} 条激活规则")
                    return rules

        except Exception as e:
            logger.error(f"获取激活规则失败: {e}")
            raise

    async def get_rule_by_id(self, rule_id: int) -> Optional[EmailRule]:
        """
        根据ID获取规则

        Args:
            rule_id: 规则ID

        Returns:
            规则实例，如果不存在返回None
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    sql = "SELECT * FROM email_rules WHERE id = %s"
                    await cursor.execute(sql, (rule_id,))
                    rule_row = await cursor.fetchone()

                    if not rule_row:
                        return None

                    rule = EmailRule.from_db_dict(dict(rule_row))

                    # 加载条件组和动作
                    rule.condition_groups = await self._get_condition_groups(rule.id)
                    rule.actions = await self._get_rule_actions(rule.id)

                    return rule

        except Exception as e:
            logger.error(f"根据ID获取规则失败: {e}")
            raise

    async def _get_condition_groups(self, rule_id: int) -> List[ConditionGroup]:
        """
        获取规则的条件组

        Args:
            rule_id: 规则ID

        Returns:
            条件组列表
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    sql = """
                        SELECT * FROM rule_condition_groups 
                        WHERE rule_id = %s 
                        ORDER BY group_order ASC, id ASC
                    """
                    await cursor.execute(sql, (rule_id,))
                    group_rows = await cursor.fetchall()

                    groups = []
                    for group_row in group_rows:
                        group = ConditionGroup.from_db_dict(dict(group_row))

                        # 加载条件组中的具体条件
                        group.conditions = await self._get_group_conditions(group.id)

                        groups.append(group)

                    return groups

        except Exception as e:
            logger.error(f"获取条件组失败: rule_id={rule_id}, {e}")
            raise

    async def _get_group_conditions(self, group_id: int) -> List[RuleCondition]:
        """
        获取条件组中的具体条件

        Args:
            group_id: 条件组ID

        Returns:
            条件列表
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    sql = """
                        SELECT * FROM rule_conditions 
                        WHERE group_id = %s 
                        ORDER BY condition_order ASC, id ASC
                    """
                    await cursor.execute(sql, (group_id,))
                    condition_rows = await cursor.fetchall()

                    conditions = []
                    for condition_row in condition_rows:
                        condition = RuleCondition.from_db_dict(
                            dict(condition_row))
                        conditions.append(condition)

                    return conditions

        except Exception as e:
            logger.error(f"获取组条件失败: group_id={group_id}, {e}")
            raise

    async def _get_rule_actions(self, rule_id: int) -> List[RuleAction]:
        """
        获取规则的动作

        Args:
            rule_id: 规则ID

        Returns:
            动作列表
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    sql = """
                        SELECT * FROM rule_actions 
                        WHERE rule_id = %s 
                        ORDER BY action_order ASC, id ASC
                    """
                    await cursor.execute(sql, (rule_id,))
                    action_rows = await cursor.fetchall()

                    actions = []
                    for action_row in action_rows:
                        action = RuleAction.from_db_dict(dict(action_row))
                        actions.append(action)

                    return actions

        except Exception as e:
            logger.error(f"获取规则动作失败: rule_id={rule_id}, {e}")
            raise

    async def check_rules_tables(self) -> bool:
        """
        检查规则相关表是否存在

        Returns:
            是否所有表都存在
        """
        required_tables = [
            'email_rules',
            'rule_condition_groups',
            'rule_conditions',
            'rule_actions'
        ]

        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor() as cursor:
                    missing_tables = []

                    for table_name in required_tables:
                        sql = "SHOW TABLES LIKE %s"
                        await cursor.execute(sql, (table_name,))
                        result = await cursor.fetchone()
                        if not result:
                            missing_tables.append(table_name)

                    if missing_tables:
                        logger.error(f"规则表不存在: {', '.join(missing_tables)}")
                        return False

                    logger.info("规则表检查通过")
                    return True

        except Exception as e:
            logger.error(f"检查规则表失败: {e}")
            return False

    async def get_rules_stats(self) -> Dict[str, Any]:
        """
        获取规则统计信息

        Returns:
            统计信息字典
        """
        try:
            async with self.db_manager.get_read_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    stats = {}

                    # 总规则数
                    await cursor.execute("SELECT COUNT(*) as total FROM email_rules")
                    result = await cursor.fetchone()
                    stats['total_rules'] = result['total']

                    # 激活规则数
                    await cursor.execute("SELECT COUNT(*) as active FROM email_rules WHERE is_active = 1")
                    result = await cursor.fetchone()
                    stats['active_rules'] = result['active']

                    # 总条件组数
                    await cursor.execute("SELECT COUNT(*) as total FROM rule_condition_groups")
                    result = await cursor.fetchone()
                    stats['total_condition_groups'] = result['total']

                    # 总条件数
                    await cursor.execute("SELECT COUNT(*) as total FROM rule_conditions")
                    result = await cursor.fetchone()
                    stats['total_conditions'] = result['total']

                    # 总动作数
                    await cursor.execute("SELECT COUNT(*) as total FROM rule_actions")
                    result = await cursor.fetchone()
                    stats['total_actions'] = result['total']

                    return stats

        except Exception as e:
            logger.error(f"获取规则统计失败: {e}")
            raise


# 全局规则数据库服务实例
rules_db_service = RulesDatabaseService()
