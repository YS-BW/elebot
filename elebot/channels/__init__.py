"""中文模块说明：冻结模块，保留实现且不接入默认主链路。"""


from elebot.channels.base import BaseChannel
from elebot.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
