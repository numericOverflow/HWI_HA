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
    CCO_BUTTON_WINDOW_LENGTH,
    CCO_BUTTON_WINDOW_OFFSET,
    CCO_RELAY_CLOSED_DIGIT,
    CCO_RELAY_OPEN_DIGIT,
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
    cco_relay_digit_to_state,
)
from .protocol import (
    MessageParser,
    normalize_address,
    parse_address,
)

__all__ = [
    # CCO_* and cco_relay_digit_to_state apply to CCO modules only, not keypad LEDs
    "CCO_BUTTON_WINDOW_LENGTH",
    "CCO_BUTTON_WINDOW_OFFSET",
    "CCO_RELAY_CLOSED_DIGIT",
    "CCO_RELAY_OPEN_DIGIT",
    "AnyMessage",
    "ButtonEventMessage",
    "ButtonEventType",
    "DimmerLevelMessage",
    "GrafikEyeSceneMessage",
    "HomeworksAuthenticationException",
    "HomeworksClient",
    "HomeworksConnectionFailed",
    "HomeworksConnectionLost",
    "HomeworksException",
    "HomeworksInvalidCredentialsProvided",
    "HomeworksMessage",
    "HomeworksNoCredentialsProvided",
    "KLSMessage",
    "KeypadEnableMessage",
    "MessageParser",
    "MessageType",
    "SivoiaSceneMessage",
    "UnknownMessage",
    "cco_relay_digit_to_state",
    "normalize_address",
    "parse_address",
]
