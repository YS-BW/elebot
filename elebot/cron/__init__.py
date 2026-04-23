"""中文模块说明：冻结模块，保留实现且不接入默认主链路。"""


from elebot.cron.service import CronService
from elebot.cron.types import CronJob, CronSchedule

__all__ = ["CronService", "CronJob", "CronSchedule"]
