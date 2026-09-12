"""Local protocol bridge used by the AutoFTBQ game front-end."""

from .protocol import PROTOCOL_VERSION
from .server import StudioBridgeServer

__all__ = ["PROTOCOL_VERSION", "StudioBridgeServer"]
