"""PyHomeworks - Async client for Lutron Homeworks Series 4/8.

This package provides a clean, typed interface for communicating with
Lutron Homeworks lighting control systems via RS-232 (typically through
an Ethernet-to-serial adapter).

Main components:
- HomeworksClient: High-level async client with auto-reconnect
- Message types: Typed dataclasses for all protocol messages
- Command builders: Functions to construct protocol commands

Example:
    from .hwi_protocol import HomeworksClient, KLSMessage

    async def on_message(msg):
        if isinstance(msg, KLSMessage):
            print(f"LED states at {msg.address}: {msg.led_states}")

    client = HomeworksClient("192.168.1.100", 23, callback=on_message)
    await client.start()
    await client.fade_dim("[01:02:03:04:05]", 75.0, 2.0)
"""

from .client import HomeworksClient
from .exceptions import (
    HomeworksAuthenticationException,
    HomeworksConnectionFailed,
    HomeworksConnectionLost,
    HomeworksException,
    HomeworksInvalidCredentialsProvided,
    HomeworksNoCredentialsProvided,
)
from .messages import (
    AnyMessage,
    ButtonEventMessage,
    ButtonEventType,
    DimmerLevelMessage,
    GrafikEyeSceneMessage,
    HomeworksMessage,
    KeypadEnableMessage,
    KLSMessage,
    MessageType,
    SivoiaSceneMessage,
    UnknownMessage,
)
from .protocol import (
    MessageParser,
    normalize_address,
    parse_address,
)

__all__ = [
    # Client
    "HomeworksClient",
    # Messages
    "AnyMessage",
    "ButtonEventMessage",
    "ButtonEventType",
    "DimmerLevelMessage",
    "GrafikEyeSceneMessage",
    "HomeworksMessage",
    "KeypadEnableMessage",
    "KLSMessage",
    "MessageType",
    "SivoiaSceneMessage",
    "UnknownMessage",
    # Protocol utilities
    "MessageParser",
    "normalize_address",
    "parse_address",
    # Exceptions
    "HomeworksAuthenticationException",
    "HomeworksConnectionFailed",
    "HomeworksConnectionLost",
    "HomeworksException",
    "HomeworksInvalidCredentialsProvided",
    "HomeworksNoCredentialsProvided",
]
