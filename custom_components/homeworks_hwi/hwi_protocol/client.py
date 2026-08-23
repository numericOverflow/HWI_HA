"""High-level async client for Homeworks controller.

This module provides:
- Async connection management with auto-reconnect
- Message callback dispatching
- Typed command methods
- Connection health tracking

Uses transport layer for socket operations and protocol layer for parsing.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

from . import commands
from .exceptions import (
    HomeworksAuthenticationException,
    HomeworksConnectionLost,
    HomeworksException,
)
from .messages import (
    AnyMessage,
)
from .protocol import MessageParser
from .transport import HomeworksTransport

_LOGGER = logging.getLogger(__name__)

# Reconnection parameters
RECONNECT_DELAY_MIN = 1.0
RECONNECT_DELAY_MAX = 60.0
RECONNECT_DELAY_MULTIPLIER = 2.0

# Callback types
MessageCallback = Callable[[AnyMessage], None]
ReconnectCallback = Callable[[], None]


class HomeworksClient:
    """High-level async client for Homeworks controller.

    This class provides:
    - Async connection with automatic reconnection
    - Message parsing and callback dispatch
    - Typed command methods
    - Connection health tracking

    Example:
        async def on_message(msg):
            if isinstance(msg, KLSMessage):
                print(f"LED state: {msg.led_states}")

        client = HomeworksClient("192.168.1.100", 23, callback=on_message)
        await client.start()
        await client.fade_dim("[01:02:03:04:05]", 75.0, 2.0)
    """

    def __init__(
        self,
        host: str,
        port: int,
        callback: MessageCallback | None = None,
        credentials: str | None = None,
        reconnect_callback: ReconnectCallback | None = None,
    ) -> None:
        """Initialize client.

        Args:
            host: Controller hostname or IP
            port: Controller port
            callback: Function to call with parsed messages
            credentials: Login credentials (password or "user, password")
            reconnect_callback: Called after the read loop re-establishes the
                connection and re-subscribes to monitoring. Fires without
                waiting for inbound traffic, so state can be re-synced on a
                system that is otherwise silent.
        """
        self._transport = HomeworksTransport(host, port, credentials)
        self._parser = MessageParser()
        self._callback = callback
        self._reconnect_callback = reconnect_callback

        self._running = False
        self._read_task: asyncio.Task | None = None
        self._reconnect_delay = RECONNECT_DELAY_MIN

        # Health metrics
        self._connected_at: datetime | None = None
        self._last_message_at: datetime | None = None
        self._reconnect_count = 0
        self._message_count = 0

    @property
    def connected(self) -> bool:
        """Return True if connected."""
        return self._transport.connected

    @property
    def host(self) -> str:
        """Return host."""
        return self._transport.host

    @property
    def port(self) -> int:
        """Return port."""
        return self._transport.port

    @property
    def connected_at(self) -> datetime | None:
        """Return time of last successful connection."""
        return self._connected_at

    @property
    def last_message_at(self) -> datetime | None:
        """Return time of last received message."""
        return self._last_message_at

    @property
    def reconnect_count(self) -> int:
        """Return number of reconnections."""
        return self._reconnect_count

    @property
    def message_count(self) -> int:
        """Return total messages received."""
        return self._message_count

    async def start(self) -> None:
        """Start the client.

        Connects to the controller and starts the message read loop.
        Automatically reconnects on connection loss.
        """
        if self._running:
            return

        self._running = True
        self._read_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the client.

        Stops the read loop and closes the connection.
        """
        self._running = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None
        await self._transport.close()

    async def connect(self) -> bool:
        """Connect to the controller (without starting read loop).

        Returns:
            True if connected successfully

        Raises:
            HomeworksAuthenticationException: If authentication fails.
        """
        try:
            await self._transport.connect()
            await self._subscribe()
            self._connected_at = datetime.now(tz=timezone.utc)
            self._reconnect_delay = RECONNECT_DELAY_MIN
            return True
        except HomeworksAuthenticationException:
            raise
        except HomeworksException as err:
            _LOGGER.error("Connection failed: %s", err)
            return False

    async def _run(self) -> None:
        """Main read loop with auto-reconnect."""
        while self._running:
            if not self._transport.connected:
                try:
                    await self._transport.connect()
                    await self._subscribe()
                    self._connected_at = datetime.now(tz=timezone.utc)
                    self._reconnect_delay = RECONNECT_DELAY_MIN
                    _LOGGER.info("Connected to controller")
                    # Announce immediately. Relays may have moved while we
                    # were away, and on a quiet system no message may arrive
                    # for a long time — the listener needs to re-query now.
                    if self._reconnect_callback:
                        try:
                            self._reconnect_callback()
                        except Exception:  # noqa: BLE001
                            _LOGGER.exception("Reconnect callback error")
                except HomeworksException as err:
                    _LOGGER.warning("Connection failed: %s", err)
                    if self._running:
                        await asyncio.sleep(self._reconnect_delay)
                        self._reconnect_delay = min(
                            self._reconnect_delay * RECONNECT_DELAY_MULTIPLIER,
                            RECONNECT_DELAY_MAX,
                        )
                    continue

            try:
                data = await self._transport.read(timeout=1.0)
                if data:
                    messages = self._parser.feed(data)
                    for msg in messages:
                        self._message_count += 1
                        self._last_message_at = datetime.now(tz=timezone.utc)
                        if self._callback:
                            try:
                                self._callback(msg)
                            except Exception:  # noqa: BLE001
                                _LOGGER.exception("Callback error")
            except HomeworksConnectionLost:
                _LOGGER.warning("Connection lost, will reconnect")
                self._reconnect_count += 1
                self._parser.reset()
                await self._transport.close()
                if self._running:
                    await asyncio.sleep(self._reconnect_delay)

    async def _subscribe(self) -> None:
        """Subscribe to monitoring events."""
        await self._transport.write(commands.prompt_off())
        await self._transport.write(commands.enable_keypad_button_monitoring())
        await self._transport.write(commands.enable_grafik_eye_monitoring())
        await self._transport.write(commands.enable_dimmer_monitoring())
        await self._transport.write(commands.enable_keypad_led_monitoring())

    # =========================================================================
    # Command Methods
    # =========================================================================

    async def send_raw(self, command: str) -> bool:
        """Send a raw command string.

        Args:
            command: Command string (without CRLF)

        Returns:
            True if send succeeded
        """
        return await self._transport.write(command)

    async def fade_dim(
        self,
        address: str,
        intensity: float,
        fade_time: float = 0.0,
        delay_time: float = 0.0,
    ) -> bool:
        """Fade a dimmer to target intensity.

        Args:
            address: Dimmer address
            intensity: Target intensity 0-100
            fade_time: Fade time in seconds
            delay_time: Delay before starting

        Returns:
            True if send succeeded
        """
        cmd = commands.fade_dim(address, intensity, fade_time, delay_time)
        return await self._transport.write(cmd)

    async def raise_dim(self, address: str) -> bool:
        """Start raising dimmer level."""
        return await self._transport.write(commands.raise_dim(address))

    async def lower_dim(self, address: str) -> bool:
        """Start lowering dimmer level."""
        return await self._transport.write(commands.lower_dim(address))

    async def stop_dim(self, address: str) -> bool:
        """Stop dimmer raise/lower."""
        return await self._transport.write(commands.stop_dim(address))

    async def request_dimmer_level(self, address: str) -> bool:
        """Request current dimmer level."""
        return await self._transport.write(commands.request_dimmer_level(address))

    async def cco_close(self, address: str, relay: int) -> bool:
        """Close a CCO relay (turn ON).

        Args:
            address: CCO address [pp:ll:aa]
            relay: Relay number 1-8

        Returns:
            True if send succeeded
        """
        return await self._transport.write(commands.cco_close(address, relay))

    async def cco_open(self, address: str, relay: int) -> bool:
        """Open a CCO relay (turn OFF).

        Args:
            address: CCO address [pp:ll:aa]
            relay: Relay number 1-8

        Returns:
            True if send succeeded
        """
        return await self._transport.write(commands.cco_open(address, relay))

    async def cco_pulse(
        self, address: str, relay: int, duration_seconds: float
    ) -> bool:
        """Pulse a CCO relay.

        Args:
            address: CCO address
            relay: Relay number 1-8
            duration_seconds: Pulse duration (0.5-122.5 seconds)

        Returns:
            True if send succeeded
        """
        return await self._transport.write(
            commands.cco_pulse(address, relay, duration_seconds)
        )

    async def motor_cover_up(self, address: str) -> bool:
        """Raise a motor cover (RPM module).

        Args:
            address: Motor address [pp:ll:mi:mo:ou]

        Returns:
            True if send succeeded
        """
        return await self._transport.write(commands.motor_cover_up(address))

    async def motor_cover_down(self, address: str) -> bool:
        """Lower a motor cover (RPM module).

        Args:
            address: Motor address [pp:ll:mi:mo:ou]

        Returns:
            True if send succeeded
        """
        return await self._transport.write(commands.motor_cover_down(address))

    async def motor_cover_stop(self, address: str) -> bool:
        """Stop a motor cover (RPM module).

        Args:
            address: Motor address [pp:ll:mi:mo:ou]

        Returns:
            True if send succeeded
        """
        return await self._transport.write(commands.motor_cover_stop(address))

    async def request_keypad_led_states(self, address: str) -> bool:
        """Request keypad LED states (RKLS).

        Args:
            address: Keypad/CCO address

        Returns:
            True if send succeeded
        """
        return await self._transport.write(commands.request_keypad_led_states(address))

    async def keypad_button_press(self, address: str, button: int) -> bool:
        """Simulate keypad button press."""
        return await self._transport.write(
            commands.keypad_button_press(address, button)
        )

    async def keypad_button_release(self, address: str, button: int) -> bool:
        """Simulate keypad button release."""
        return await self._transport.write(
            commands.keypad_button_release(address, button)
        )

    async def keypad_button_hold(self, address: str, button: int) -> bool:
        """Simulate keypad button hold."""
        return await self._transport.write(commands.keypad_button_hold(address, button))

    async def keypad_button_double_tap(self, address: str, button: int) -> bool:
        """Simulate keypad button double-tap."""
        return await self._transport.write(
            commands.keypad_button_double_tap(address, button)
        )

    async def set_led(self, address: str, led_number: int, state: int) -> bool:
        """Set a single LED state.

        Args:
            address: Keypad address
            led_number: LED number 1-24
            state: 0=Off, 1=On, 2=Flash1, 3=Flash2

        Returns:
            True if send succeeded
        """
        return await self._transport.write(commands.set_led(address, led_number, state))

    async def grafik_eye_scene_select(self, address: str, scene: int) -> bool:
        """Select a GRAFIK Eye scene.

        Args:
            address: GRAFIK Eye address
            scene: Scene number 0-16 (0 = Off)

        Returns:
            True if send succeeded
        """
        return await self._transport.write(
            commands.grafik_eye_scene_select(address, scene)
        )

    async def request_grafik_eye_scene(self, address: str) -> bool:
        """Request current GRAFIK Eye scene."""
        return await self._transport.write(commands.request_grafik_eye_scene(address))

    async def sivoia_scene_select(
        self, address: str, command: str, delay_time: float = 0.0
    ) -> bool:
        """Select a Sivoia scene/action.

        Args:
            address: Sivoia control address
            command: Scene command (1, 2, 3, R, L, C, O, S)
            delay_time: Delay in seconds

        Returns:
            True if send succeeded
        """
        return await self._transport.write(
            commands.sivoia_scene_select(address, command, delay_time)
        )

    async def request_sivoia_scene(self, address: str) -> bool:
        """Request current Sivoia scene."""
        return await self._transport.write(commands.request_sivoia_scene(address))
