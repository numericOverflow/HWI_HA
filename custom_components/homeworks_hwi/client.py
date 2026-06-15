"""Home Assistant client wrapper for Lutron Homeworks.

This module provides a thin wrapper around pyhomeworks.HomeworksClient
that integrates with Home Assistant's callback pattern and adds
HA-specific functionality like KLS caching for the CCO state engine.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable

from .hwi_protocol import (
    HomeworksClient as PyHomeworksClient,
    KLSMessage,
    DimmerLevelMessage,
    ButtonEventMessage,
    ButtonEventType,
    KeypadEnableMessage,
    GrafikEyeSceneMessage,
    SivoiaSceneMessage,
    AnyMessage,
    normalize_address,
)

from .models import ControllerHealth, KLSState

_LOGGER = logging.getLogger(__name__)

# Message types for callbacks (HA-layer uses string types)
HW_BUTTON_PRESSED = "button_pressed"
HW_BUTTON_RELEASED = "button_released"
HW_BUTTON_HOLD = "button_hold"
HW_BUTTON_DOUBLE_TAP = "button_double_tap"
HW_KEYPAD_LED_CHANGED = "keypad_led_changed"
HW_LIGHT_CHANGED = "light_changed"
HW_KEYPAD_ENABLE_CHANGED = "keypad_enable_changed"
HW_GRAFIK_EYE_SCENE_CHANGED = "grafik_eye_scene_changed"
HW_SIVOIA_SCENE_CHANGED = "sivoia_scene_changed"
HW_LOGIN_INCORRECT = "login_incorrect"
HW_CONNECTION_LOST = "connection_lost"
HW_CONNECTION_RESTORED = "connection_restored"


@dataclass
class HomeworksClientConfig:
    """Configuration for the Homeworks client."""

    host: str
    port: int
    username: str | None = None
    password: str | None = None
    reconnect_delay: float = 5.0
    command_delay: float = 0.05  # Delay between commands to avoid flooding


class HomeworksClient:
    """Home Assistant wrapper for Homeworks communication.

    This class:
    - Wraps pyhomeworks.HomeworksClient for async communication
    - Converts typed messages to HA callback format
    - Maintains KLS cache for CCO state derivation
    - Tracks connection health metrics
    """

    def __init__(
        self,
        config: HomeworksClientConfig,
        message_callback: Callable[[str, list[Any]], None] | None = None,
    ) -> None:
        """Initialize the client."""
        self._config = config
        self._message_callback = message_callback
        self._command_lock = asyncio.Lock()
        self._health = ControllerHealth()

        # Build credentials string
        credentials = None
        if config.username:
            if config.password:
                credentials = f"{config.username}, {config.password}"
            else:
                credentials = config.username

        # Create the underlying client
        self._client = PyHomeworksClient(
            host=config.host,
            port=config.port,
            callback=self._handle_message,
            credentials=credentials,
        )

        # KLS state cache: normalized address -> KLSState
        self._kls_cache: dict[str, KLSState] = {}

        # Addresses to poll for KLS
        self._kls_poll_addresses: set[str] = set()

        # Track connection state for callbacks
        self._was_connected = False

    @property
    def connected(self) -> bool:
        """Return True if connected to the controller."""
        return self._client.connected

    @property
    def health(self) -> ControllerHealth:
        """Return health metrics."""
        return self._health

    def get_kls_state(self, address: str) -> KLSState | None:
        """Get cached KLS state for an address."""
        normalized = normalize_address(address)
        return self._kls_cache.get(normalized)

    def register_kls_address(self, address: str) -> None:
        """Register an address for KLS polling."""
        normalized = normalize_address(address)
        self._kls_poll_addresses.add(normalized)
        _LOGGER.debug("Registered KLS poll address: %s", normalized)

    def unregister_kls_address(self, address: str) -> None:
        """Unregister an address from KLS polling."""
        normalized = normalize_address(address)
        self._kls_poll_addresses.discard(normalized)

    async def connect(self) -> bool:
        """Connect to the controller."""
        try:
            success = await self._client.connect()
            if success:
                self._health.connected = True
                self._health.record_message()
                self._was_connected = True
                _LOGGER.info(
                    "Connected to Homeworks controller at %s:%s",
                    self._config.host,
                    self._config.port,
                )
            return success
        except Exception as err:
            _LOGGER.error("Failed to connect: %s", err)
            self._health.connected = False
            self._health.record_poll_failure(str(err))
            return False

    async def start(self) -> None:
        """Start the client read loop."""
        await self._client.start()

    async def stop(self) -> None:
        """Stop the client and close connection."""
        await self._client.stop()
        self._health.connected = False

    def _handle_message(self, msg: AnyMessage) -> None:
        """Handle a typed message from pyhomeworks.

        Converts to HA callback format and updates internal state.
        """
        # Update health metrics
        self._health.record_message()

        # Check for connection state changes
        if self._client.connected and not self._was_connected:
            self._was_connected = True
            self._health.record_reconnect()
            if self._message_callback:
                self._message_callback(HW_CONNECTION_RESTORED, [])
        elif not self._client.connected and self._was_connected:
            self._was_connected = False
            self._health.connected = False
            if self._message_callback:
                self._message_callback(HW_CONNECTION_LOST, [])

        # Route by message type
        if isinstance(msg, KLSMessage):
            self._handle_kls_message(msg)
        elif isinstance(msg, DimmerLevelMessage):
            self._handle_dimmer_message(msg)
        elif isinstance(msg, ButtonEventMessage):
            self._handle_button_message(msg)
        elif isinstance(msg, KeypadEnableMessage):
            self._handle_keypad_enable_message(msg)
        elif isinstance(msg, GrafikEyeSceneMessage):
            self._handle_grafik_eye_message(msg)
        elif isinstance(msg, SivoiaSceneMessage):
            self._handle_sivoia_message(msg)

    def _handle_kls_message(self, msg: KLSMessage) -> None:
        """Handle KLS (Keypad LED State) message."""
        # Store in cache
        kls_state = KLSState(
            address=msg.address,
            led_states=list(msg.led_states),
            timestamp=msg.timestamp,
        )
        self._kls_cache[msg.address] = kls_state
        self._health.record_kls()

        _LOGGER.debug("KLS update for %s: %s", msg.address, msg.led_states)

        # Notify callback
        if self._message_callback:
            self._message_callback(
                HW_KEYPAD_LED_CHANGED, [msg.address, list(msg.led_states)]
            )

    def _handle_dimmer_message(self, msg: DimmerLevelMessage) -> None:
        """Handle DL (Dimmer Level) message."""
        if self._message_callback:
            self._message_callback(HW_LIGHT_CHANGED, [msg.address, msg.level])

    def _handle_button_message(self, msg: ButtonEventMessage) -> None:
        """Handle button event message."""
        if not self._message_callback:
            return

        # Map event type to callback type
        event_map = {
            ButtonEventType.PRESSED: HW_BUTTON_PRESSED,
            ButtonEventType.RELEASED: HW_BUTTON_RELEASED,
            ButtonEventType.HOLD: HW_BUTTON_HOLD,
            ButtonEventType.DOUBLE_TAP: HW_BUTTON_DOUBLE_TAP,
        }

        event_type = event_map.get(msg.event_type)
        if event_type:
            self._message_callback(event_type, [msg.address, msg.button])

    def _handle_keypad_enable_message(self, msg: KeypadEnableMessage) -> None:
        """Handle keypad enable/disable message."""
        if self._message_callback:
            self._message_callback(HW_KEYPAD_ENABLE_CHANGED, [msg.address, msg.enabled])

    def _handle_grafik_eye_message(self, msg: GrafikEyeSceneMessage) -> None:
        """Handle GRAFIK Eye scene message."""
        if self._message_callback:
            self._message_callback(
                HW_GRAFIK_EYE_SCENE_CHANGED, [msg.address, msg.scene]
            )

    def _handle_sivoia_message(self, msg: SivoiaSceneMessage) -> None:
        """Handle Sivoia scene message."""
        if self._message_callback:
            self._message_callback(
                HW_SIVOIA_SCENE_CHANGED, [msg.address, msg.command, msg.status]
            )

    # === Command Methods ===
    # These wrap the underlying client with rate limiting

    async def send_command(self, command: str) -> bool:
        """Send a raw command with rate limiting."""
        async with self._command_lock:
            result = await self._client.send_raw(command)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def fade_dim(
        self, level: float, fade_time: float, delay_time: float, address: str
    ) -> bool:
        """Fade a dimmer to a level."""
        async with self._command_lock:
            result = await self._client.fade_dim(address, level, fade_time, delay_time)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def request_dimmer_level(self, address: str) -> bool:
        """Request current dimmer level."""
        async with self._command_lock:
            result = await self._client.request_dimmer_level(address)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def request_keypad_led_states(self, address: str) -> bool:
        """Request keypad LED states (RKLS command)."""
        normalized = normalize_address(address)
        async with self._command_lock:
            result = await self._client.request_keypad_led_states(normalized)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def cco_close(self, address: str, relay: int) -> bool:
        """Close a CCO relay (turn ON)."""
        async with self._command_lock:
            result = await self._client.cco_close(address, relay)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def cco_open(self, address: str, relay: int) -> bool:
        """Open a CCO relay (turn OFF)."""
        async with self._command_lock:
            result = await self._client.cco_open(address, relay)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def cco_pulse(self, address: str, relay: int, pulse_time: float) -> bool:
        """Pulse a CCO relay."""
        async with self._command_lock:
            result = await self._client.cco_pulse(address, relay, pulse_time)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def motor_cover_up(self, address: str) -> bool:
        """Raise a motor cover (RPM module)."""
        async with self._command_lock:
            result = await self._client.motor_cover_up(address)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def motor_cover_down(self, address: str) -> bool:
        """Lower a motor cover (RPM module)."""
        async with self._command_lock:
            result = await self._client.motor_cover_down(address)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def motor_cover_stop(self, address: str) -> bool:
        """Stop a motor cover (RPM module)."""
        async with self._command_lock:
            result = await self._client.motor_cover_stop(address)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def stop_dim(self, address: str) -> bool:
        """Stop a dimmer/shade mid-fade (STOPDIM command)."""
        async with self._command_lock:
            result = await self._client.stop_dim(address)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def keypad_button_press(self, address: str, button: int) -> bool:
        """Simulate keypad button press."""
        async with self._command_lock:
            result = await self._client.keypad_button_press(address, button)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def keypad_button_release(self, address: str, button: int) -> bool:
        """Simulate keypad button release."""
        async with self._command_lock:
            result = await self._client.keypad_button_release(address, button)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def set_led(self, address: str, led_number: int, state: int) -> bool:
        """Set a single LED state."""
        async with self._command_lock:
            result = await self._client.set_led(address, led_number, state)
            await asyncio.sleep(self._config.command_delay)
            return result

    async def poll_all_kls(self) -> None:
        """Poll KLS for all registered addresses."""
        for address in list(self._kls_poll_addresses):
            await self.request_keypad_led_states(address)
