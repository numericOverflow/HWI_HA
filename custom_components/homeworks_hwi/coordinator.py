"""DataUpdateCoordinator for Lutron Homeworks integration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .client import (
    HW_BUTTON_DOUBLE_TAP,
    HW_BUTTON_HOLD,
    HW_BUTTON_PRESSED,
    HW_BUTTON_RELEASED,
    HW_CONNECTION_LOST,
    HW_CONNECTION_RESTORED,
    HW_KEYPAD_LED_CHANGED,
    HW_LIGHT_CHANGED,
    HomeworksClient,
    HomeworksClientConfig,
)
from .const import (
    BUTTON_EVENT_DOUBLE_TAP,
    BUTTON_EVENT_HOLD,
    BUTTON_EVENT_PRESSED,
    BUTTON_EVENT_RELEASED,
    CONF_ADDR,
    CONF_CCO_DEVICES,
    CONF_KEYPADS,
    DEFAULT_KLS_WINDOW_OFFSET,
    RPM_MOTOR_DOWN,
    RPM_MOTOR_STOP,
    RPM_MOTOR_UP,
)
from .hwi_protocol import (
    CCO_BUTTON_WINDOW_LENGTH,
    HomeworksAuthenticationException,
    parse_address,
)
from .models import (
    CCOAddress,
    CCODevice,
    ControllerHealth,
    normalize_address,
)

_LOGGER = logging.getLogger(__name__)

# Default polling interval for KLS (CCO state)
DEFAULT_KLS_POLL_INTERVAL = timedelta(seconds=10)

# Default polling interval for dimmer state
# Number of KLS poll cycles between dimmer polls
DIMMER_POLL_EVERY_N_CYCLES = 3

# How long after a CCO command a contradicting KLS is treated as a
# command/feedback mismatch worth logging. KLS is always authoritative;
# this only controls whether the disagreement is reported as suspicious
# (the processor rejected or ignored our command) rather than as a normal
# external change made at a keypad.
CCO_COMMAND_MISMATCH_WINDOW = 5.0


class HomeworksCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for Homeworks data updates.

    This coordinator:
    - Manages the async client connection
    - Polls KLS state for CCO devices at regular intervals
    - Maintains a unified state cache for all CCO entities
    - Dispatches state updates to entities
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config: HomeworksClientConfig,
        controller_id: str,
        config_entry: ConfigEntry,
        kls_poll_interval: timedelta = DEFAULT_KLS_POLL_INTERVAL,
        kls_window_offset: int = DEFAULT_KLS_WINDOW_OFFSET,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"Homeworks {controller_id}",
            update_interval=kls_poll_interval,
        )
        self._config = config
        self._controller_id = controller_id
        self._kls_window_offset = kls_window_offset
        self._poll_count: int = 0

        # Create client (no connection yet — lazy connect in _async_update_data)
        self._client = HomeworksClient(
            config=config,
            message_callback=self._handle_message,
        )

        # CCO device registry: unique_key -> CCODevice
        self._cco_devices: dict[tuple[int, int, int, int], CCODevice] = {}

        # CCO state cache: unique_key -> bool | None (is_on).
        # None means "not yet known" — no KLS seen, or a relay digit with no
        # documented meaning. CCO relays latch, so there is no safe default
        # to assume; entities must report unknown until the processor tells
        # us the real position. Never seed this with False.
        self._cco_states: dict[tuple[int, int, int, int], bool | None] = {}

        # Raw relay-window digit per CCO endpoint, for diagnostics: the
        # undecoded digit behind each state, so a wrong window offset or an
        # unexpected digit value is visible without a packet capture.
        self._cco_relay_digits: dict[tuple[int, int, int, int], int | None] = {}

        # How each CCO state was last established: "kls" (processor
        # feedback), "optimistic" (our own command, awaiting confirmation),
        # or "unknown" (nothing known yet).
        self._cco_state_sources: dict[tuple[int, int, int, int], str] = {}

        # Pending optimistic commands: unique_key -> (expected_state, sent_at).
        # Used only to decide whether a contradicting KLS is worth logging
        # as a mismatch. KLS always wins regardless.
        self._cco_pending_commands: dict[
            tuple[int, int, int, int], tuple[bool, float]
        ] = {}

        # Monotonic timestamp of the last KLS seen per module address.
        # Diagnostics only — no staleness gating is applied to state.
        self._kls_last_seen: dict[str, float] = {}

        # Dimmer state cache: address -> level (0-100)
        self._dimmer_states: dict[str, int] = {}

        # Keypad LED state cache: address -> list[int]
        self._keypad_led_states: dict[str, list[int]] = {}

        # CCI state cache: (processor, link, address, input) -> bool
        self._cci_states: dict[tuple[int, int, int, int], bool] = {}

        # CCI devices registry: unique_key -> CCIDevice
        self._cci_devices: dict[tuple[int, int, int, int], Any] = {}

        # Addresses that need KLS polling
        self._kls_poll_addresses: set[str] = set()

        # Dimmer addresses for polling
        self._dimmer_addresses: set[str] = set()

        # Event callbacks
        self._button_callbacks: dict[str, list[Callable[[str, int, str], None]]] = {}

        # CCI state change callbacks
        self._cci_callbacks: dict[tuple[int, int, int, int], list[Callable[[bool], None]]] = {}

        # Seed poll addresses from config so the very first refresh already
        # sweeps them. Entities register themselves in async_added_to_hass,
        # which runs after the first refresh — without this the startup
        # sweep would send nothing and every CCO would sit unknown until a
        # later poll tick. See L232/cco_kls_state.htm implementation note 2.
        self._preregister_poll_addresses_from_options()

    def _preregister_poll_addresses_from_options(self) -> None:
        """Populate KLS poll addresses from the config entry options.

        Collapses to one address per module (a set), so an 8-relay CCO board
        gets one RKLS rather than eight identical ones — implementation
        note 3 of L232/cco_kls_state.htm.
        """
        options = self.config_entry.options if self.config_entry else {}

        for device_config in options.get(CONF_CCO_DEVICES, []):
            # Strip any ",relay" suffix — polling is per module address.
            addr = str(device_config.get(CONF_ADDR) or "").split(",", 1)[0]
            self._add_validated_poll_address(addr, "CCO")

        for keypad in options.get(CONF_KEYPADS, []):
            self._add_validated_poll_address(
                str(keypad.get(CONF_ADDR) or ""), "keypad"
            )

        if self._kls_poll_addresses:
            _LOGGER.debug(
                "Pre-registered %d KLS poll address(es) from config",
                len(self._kls_poll_addresses),
            )

    def _add_validated_poll_address(self, address: str, kind: str) -> None:
        """Add a config address to the poll set if it parses as an address.

        normalize_address() only reformats and does not validate, so junk
        would otherwise be polled forever with no indication of why. Checked
        here rather than at poll time so the bad entry is named once at setup.
        """
        if not address:
            return
        try:
            parse_address(address)
        except ValueError:
            _LOGGER.warning("Skipping unparsable %s address: %s", kind, address)
            return
        self._kls_poll_addresses.add(normalize_address(address))

    def register_kls_poll_address(self, address: str) -> None:
        """Register an address for KLS polling."""
        normalized = normalize_address(address)
        self._kls_poll_addresses.add(normalized)
        if self._client:
            self._client.register_kls_address(normalized)

    def unregister_kls_poll_address(self, address: str) -> None:
        """Unregister an address from KLS polling."""
        normalized = normalize_address(address)
        self._kls_poll_addresses.discard(normalized)
        if self._client:
            self._client.unregister_kls_address(normalized)

    @property
    def controller_id(self) -> str:
        """Return the controller ID."""
        return self._controller_id

    @property
    def client(self) -> HomeworksClient | None:
        """Return the client instance."""
        return self._client

    @property
    def health(self) -> ControllerHealth:
        """Return controller health metrics."""
        if self._client:
            return self._client.health
        return ControllerHealth()

    @property
    def connected(self) -> bool:
        """Return True if connected to controller."""
        return self._client is not None and self._client.connected

    @property
    def cco_device_count(self) -> int:
        """Return number of registered CCO devices."""
        return len(self._cco_devices)

    @property
    def cco_state_count(self) -> int:
        """Return number of cached CCO states."""
        return len(self._cco_states)

    @property
    def cco_unknown_count(self) -> int:
        """Return number of CCO endpoints whose relay position is unknown."""
        return sum(1 for state in self._cco_states.values() if state is None)

    def kls_last_seen_ages(self) -> dict[str, float]:
        """Return seconds since the last KLS per polled module address.

        Diagnostics only — state is not gated on this. Addresses that have
        never answered are absent from the mapping.
        """
        now = self.hass.loop.time()
        return {
            address: round(now - seen, 1)
            for address, seen in self._kls_last_seen.items()
        }

    @property
    def kls_poll_address_count(self) -> int:
        """Return number of KLS addresses being polled."""
        return len(self._kls_poll_addresses)

    @property
    def keypad_led_state_count(self) -> int:
        """Return number of cached keypad LED states."""
        return len(self._keypad_led_states)

    @property
    def dimmer_address_count(self) -> int:
        """Return number of registered dimmer addresses."""
        return len(self._dimmer_addresses)

    @property
    def dimmer_state_count(self) -> int:
        """Return number of cached dimmer states."""
        return len(self._dimmer_states)

    def register_cco_device(self, device: CCODevice) -> None:
        """Register a CCO device for state tracking.

        State starts as None (unknown) and stays that way until a KLS
        arrives. Do not seed False: a CCO relay is latching and holds its
        last position across power loss, so "off" is a guess that is wrong
        about half the time.

        Safe to call repeatedly — an already-known state is preserved.
        """
        key = device.address.unique_key
        self._cco_devices[key] = device
        self._cco_states.setdefault(key, None)
        self._cco_relay_digits.setdefault(key, None)
        self._cco_state_sources.setdefault(key, "unknown")

        # Register the KLS address for polling
        kls_addr = device.address.to_kls_address()
        self._kls_poll_addresses.add(kls_addr)
        if self._client:
            self._client.register_kls_address(kls_addr)

        _LOGGER.debug(
            "Registered CCO device: %s (type=%s, inverted=%s)",
            device.address,
            device.entity_type.name,
            device.inverted,
        )

    def unregister_cco_device(self, address: CCOAddress) -> None:
        """Unregister a CCO device."""
        key = address.unique_key
        self._cco_devices.pop(key, None)
        self._cco_states.pop(key, None)
        self._cco_relay_digits.pop(key, None)
        self._cco_state_sources.pop(key, None)
        self._cco_pending_commands.pop(key, None)

        # Remove KLS poll address only if no other CCO device shares it
        kls_addr = address.to_kls_address()
        still_needed = any(
            d.address.to_kls_address() == kls_addr
            for d in self._cco_devices.values()
        )
        if not still_needed:
            self._kls_poll_addresses.discard(kls_addr)
            if self._client:
                self._client.unregister_kls_address(kls_addr)

    def register_dimmer(self, address: str) -> None:
        """Register a dimmer for state tracking."""
        normalized = normalize_address(address)
        self._dimmer_addresses.add(normalized)
        self._dimmer_states[normalized] = 0

    def unregister_dimmer(self, address: str) -> None:
        """Unregister a dimmer."""
        normalized = normalize_address(address)
        self._dimmer_addresses.discard(normalized)
        self._dimmer_states.pop(normalized, None)

    def get_cco_state(self, address: CCOAddress) -> bool | None:
        """Get the current state of a CCO device.

        Returns None when the relay position is not known — before the first
        KLS arrives, or when the processor reported a digit with no
        documented meaning. Callers must surface that as "unknown"; a CCO
        relay latches, so there is no safe default to substitute.
        """
        return self._cco_states.get(address.unique_key)

    def get_cco_diagnostics(self, address: CCOAddress) -> dict[str, Any]:
        """Return CCO relay feedback details for entity attributes.

        CCO-only. Keypad LED entities do not use this — their digits carry
        the standard kls_mon.htm LED meanings, not relay positions.
        """
        key = address.unique_key
        return {
            "kls_window_offset": self._kls_window_offset,
            "kls_index": self._kls_window_offset + (address.button - 1),
            "kls_raw_digit": self._cco_relay_digits.get(key),
            "state_source": self._cco_state_sources.get(key, "unknown"),
        }

    def get_dimmer_level(self, address: str) -> int:
        """Get the current dimmer level."""
        normalized = normalize_address(address)
        return self._dimmer_states.get(normalized, 0)

    def get_keypad_led_states(self, address: str) -> list[int] | None:
        """Get LED states for a keypad.

        Returns None when no KLS message has been seen for the address yet,
        so callers can report "unknown" instead of guessing "all off".
        """
        normalized = normalize_address(address)
        return self._keypad_led_states.get(normalized)

    def register_cci_device(
        self,
        address: str,
        input_number: int,
        device: Any,
    ) -> None:
        """Register a CCI device for state tracking."""
        normalized = normalize_address(address)
        parts = normalized.strip("[]").split(":")
        key = (int(parts[0]), int(parts[1]), int(parts[2]), input_number)
        self._cci_devices[key] = device
        self._cci_states[key] = False  # Default to off/open

        _LOGGER.debug(
            "Registered CCI device: %s input %d",
            normalized,
            input_number,
        )

    def unregister_cci_device(self, address: str, input_number: int) -> None:
        """Unregister a CCI device."""
        normalized = normalize_address(address)
        parts = normalized.strip("[]").split(":")
        key = (int(parts[0]), int(parts[1]), int(parts[2]), input_number)
        self._cci_devices.pop(key, None)
        self._cci_states.pop(key, None)

    def get_cci_state(self, address: str, input_number: int) -> bool:
        """Get the current state of a CCI input."""
        normalized = normalize_address(address)
        parts = normalized.strip("[]").split(":")
        key = (int(parts[0]), int(parts[1]), int(parts[2]), input_number)
        return self._cci_states.get(key, False)

    def register_cci_callback(
        self,
        address: str,
        input_number: int,
        callback: Callable[[bool], None],
    ) -> Callable[[], None]:
        """Register a callback for CCI state changes.

        Returns a function to unregister the callback.
        """
        normalized = normalize_address(address)
        parts = normalized.strip("[]").split(":")
        key = (int(parts[0]), int(parts[1]), int(parts[2]), input_number)

        if key not in self._cci_callbacks:
            self._cci_callbacks[key] = []
        self._cci_callbacks[key].append(callback)

        def unregister():
            self._cci_callbacks[key].remove(callback)
            if not self._cci_callbacks[key]:
                del self._cci_callbacks[key]

        return unregister

    def register_button_callback(
        self,
        address: str,
        callback: Callable[[str, int, str], None],
    ) -> Callable[[], None]:
        """Register a callback for button events.

        Returns a function to unregister the callback.
        """
        normalized = normalize_address(address)
        if normalized not in self._button_callbacks:
            self._button_callbacks[normalized] = []
        self._button_callbacks[normalized].append(callback)

        def unregister():
            self._button_callbacks[normalized].remove(callback)
            if not self._button_callbacks[normalized]:
                del self._button_callbacks[normalized]

        return unregister

    async def _connect_and_subscribe(self) -> None:
        """Connect to the controller and start the message read loop.

        Called lazily from _async_update_data on first poll or after
        connection loss.

        Raises:
            HomeworksAuthenticationException: If authentication fails.
            UpdateFailed: If connection fails for other reasons.
        """
        # Register any pending KLS addresses
        for addr in self._kls_poll_addresses:
            self._client.register_kls_address(addr)

        if not await self._client.connect():
            raise UpdateFailed("Failed to connect to Homeworks controller")

        await self._client.start()

    async def async_shutdown(self) -> None:
        """Shut down the coordinator."""
        await super().async_shutdown()
        if self._client:
            await self._client.stop()
            self._client = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from controller (called by DataUpdateCoordinator)."""
        if not self._client:
            raise UpdateFailed("Client not initialized")

        # Connect if not already connected (lazy connect / reconnect)
        if not self._client.connected:
            try:
                await self._connect_and_subscribe()
            except HomeworksAuthenticationException as err:
                raise ConfigEntryAuthFailed("Authentication failed") from err

        # Poll all KLS addresses
        await self._poll_kls_states()

        # Poll dimmer states periodically (every Nth cycle) to catch
        # missed DL monitoring messages after silent subscription drops
        self._poll_count += 1
        if self._dimmer_addresses and self._poll_count % DIMMER_POLL_EVERY_N_CYCLES == 0:
            await self._poll_dimmer_states()

        return {"connected": True, "poll_count": self._poll_count}

    async def _poll_all_states(self) -> None:
        """Poll all device states."""
        await self._poll_kls_states()
        await self._poll_dimmer_states()

    async def _poll_kls_states(self) -> None:
        """Poll KLS state for all registered addresses."""
        if not self._client:
            return

        for address in list(self._kls_poll_addresses):
            try:
                await self._client.request_keypad_led_states(address)
                # Small delay between requests
                await asyncio.sleep(0.1)
            except Exception as err:
                _LOGGER.warning("Failed to poll KLS for %s: %s", address, err)

    async def _poll_dimmer_states(self) -> None:
        """Poll dimmer levels for all registered dimmers."""
        if not self._client:
            return

        for address in list(self._dimmer_addresses):
            try:
                await self._client.request_dimmer_level(address)
                await asyncio.sleep(0.05)
            except Exception as err:
                _LOGGER.warning("Failed to poll dimmer %s: %s", address, err)

    @callback
    def _handle_message(self, msg_type: str, values: list[Any]) -> None:
        """Handle incoming messages from the controller."""
        if msg_type == HW_KEYPAD_LED_CHANGED:
            self._handle_kls_update(values[0], values[1])
        elif msg_type == HW_LIGHT_CHANGED:
            self._handle_dimmer_update(values[0], values[1])
        elif msg_type == HW_BUTTON_PRESSED:
            self._dispatch_button_event(values[0], values[1], BUTTON_EVENT_PRESSED)
        elif msg_type == HW_BUTTON_RELEASED:
            self._dispatch_button_event(values[0], values[1], BUTTON_EVENT_RELEASED)
            # CCI devices use KBR (release) to indicate OFF state
            self._handle_cci_button_event(values[0], values[1], False)
        elif msg_type == HW_BUTTON_HOLD:
            self._dispatch_button_event(values[0], values[1], BUTTON_EVENT_HOLD)
            # CCI devices use KBH (hold) to indicate ON state
            self._handle_cci_button_event(values[0], values[1], True)
        elif msg_type == HW_BUTTON_DOUBLE_TAP:
            self._dispatch_button_event(values[0], values[1], BUTTON_EVENT_DOUBLE_TAP)
        elif msg_type == HW_CONNECTION_LOST:
            _LOGGER.warning("Controller connection lost")
        elif msg_type == HW_CONNECTION_RESTORED:
            _LOGGER.info("Controller connection restored")
            # Re-poll all states after reconnection
            self.config_entry.async_create_background_task(
                self.hass,
                self._safe_poll_all_states(),
                name=f"homeworks_{self._controller_id}_reconnect_poll",
            )

    async def _safe_poll_all_states(self) -> None:
        """Poll all states with error handling for background tasks."""
        try:
            await self._poll_all_states()
        except Exception:
            _LOGGER.exception("Failed to poll states after reconnection")

    def _handle_kls_update(self, address: str, led_states: list[int]) -> None:
        """Handle a KLS (LED state) update.

        This is the core of the CCO state engine - it updates all CCO
        devices that match this address.
        """
        normalized = normalize_address(address)
        # Track LED changes separately from CCO state changes: a keypad with no
        # CCO devices registered still has LED binary sensors that must be
        # written as soon as the pushed KLS arrives, not at the next poll.
        led_changed = self._keypad_led_states.get(normalized) != led_states
        self._keypad_led_states[normalized] = led_states
        self._kls_last_seen[normalized] = self.hass.loop.time()

        _LOGGER.debug(
            "KLS update for %s: full=[%s] window_offset=%d",
            normalized,
            ",".join(str(x) for x in led_states),
            self._kls_window_offset,
        )

        # Parse the address to get processor/link/address
        try:
            parts = normalized.strip("[]").split(":")
            processor = int(parts[0])
            link = int(parts[1])
            addr = int(parts[2])
        except (ValueError, IndexError):
            _LOGGER.warning("Failed to parse KLS address: %s", normalized)
            if led_changed:
                self.async_set_updated_data(
                    {"connected": True, "poll_count": self._poll_count}
                )
            return

        # Update all CCO devices at this address
        state_changed = False
        for key, device in self._cco_devices.items():
            if (
                device.address.processor == processor
                and device.address.link == link
                and device.address.address == addr
            ):
                # Read the relay position from the relay window.
                # Relay N (1-8) is at index window_offset + (N-1).
                button = device.address.button
                if 1 <= button <= CCO_BUTTON_WINDOW_LENGTH:
                    index = self._kls_window_offset + (button - 1)
                    if index < len(led_states):
                        led_value = led_states[index]
                        # None when the digit has no documented meaning —
                        # kept as unknown rather than coerced to off.
                        new_state = device.interpret_state(led_value)
                        old_state = self._cco_states.get(key)

                        _LOGGER.debug(
                            "CCO %s (relay=%d idx=%d): digit=%d -> state=%s (was %s, inverted=%s)",
                            device.name,
                            button,
                            index,
                            led_value,
                            new_state,
                            old_state,
                            device.inverted,
                        )

                        if new_state is None:
                            _LOGGER.warning(
                                "CCO %s relay %d: KLS digit %d at index %d has no "
                                "documented meaning; reporting unknown. Full KLS for "
                                "%s: %s (window offset %d). An all-zero relay window "
                                "usually means the configured window offset is wrong.",
                                device.name,
                                button,
                                led_value,
                                index,
                                normalized,
                                "".join(str(x) for x in led_states),
                                self._kls_window_offset,
                            )

                        self._cco_relay_digits[key] = led_value
                        self._cco_state_sources[key] = (
                            "unknown" if new_state is None else "kls"
                        )
                        self._check_command_mismatch(key, device, new_state)

                        if old_state != new_state:
                            self._cco_states[key] = new_state
                            state_changed = True

        # Notify listeners if any LED or derived CCO state changed
        if led_changed or state_changed:
            self.async_set_updated_data(
                {"connected": True, "poll_count": self._poll_count}
            )

    def _check_command_mismatch(
        self,
        key: tuple[int, int, int, int],
        device: CCODevice,
        reported: bool | None,
    ) -> None:
        """Log when processor feedback contradicts a command we just sent.

        KLS is authoritative and always wins — this only surfaces the
        disagreement, which otherwise looks like an entity mysteriously
        flipping back. Common causes: the relay is not programmed into the
        processor database, or the configured address/relay number is wrong.
        """
        pending = self._cco_pending_commands.pop(key, None)
        if pending is None or reported is None:
            return

        expected, sent_at = pending
        if self.hass.loop.time() - sent_at > CCO_COMMAND_MISMATCH_WINDOW:
            return  # Too old to attribute to our command.
        if expected == reported:
            return  # Confirmed.

        _LOGGER.warning(
            "CCO %s (%s relay %d): commanded %s but processor reports %s. "
            "Using the processor's value. Check that this relay is programmed "
            "into the database and that the address and relay number are correct.",
            device.name,
            device.address.to_kls_address(),
            device.address.button,
            "ON" if expected else "OFF",
            "ON" if reported else "OFF",
        )

    def _handle_dimmer_update(self, address: str, level: int) -> None:
        """Handle a dimmer level update."""
        normalized = normalize_address(address)

        if normalized in self._dimmer_states:
            old_level = self._dimmer_states[normalized]
            if old_level != level:
                self._dimmer_states[normalized] = level
                _LOGGER.debug(
                    "Dimmer %s level changed: %d -> %d",
                    normalized,
                    old_level,
                    level,
                )
                self.async_set_updated_data(
                    {"connected": True, "poll_count": self._poll_count}
                )

    def _dispatch_button_event(
        self, address: str, button: int, event_type: str
    ) -> None:
        """Dispatch button event to registered callbacks."""
        normalized = normalize_address(address)
        callbacks = self._button_callbacks.get(normalized, [])

        for cb in callbacks:
            try:
                cb(normalized, button, event_type)
            except Exception as err:
                _LOGGER.error("Button callback error: %s", err)

    def _handle_cci_button_event(
        self, address: str, button: int, state: bool
    ) -> None:
        """Handle a CCI state change from button event.

        CCIs emulate keypads. When the physical key is:
        - Turned to ON: KBP then KBH (hold) = state is ON/closed
        - Turned to OFF: KBR (release) = state is OFF/open

        Args:
            address: Keypad/CCI address
            button: Button number (1-24)
            state: True for KBH (on), False for KBR (off)
        """
        normalized = normalize_address(address)

        # Parse the address to get processor/link/address
        try:
            parts = normalized.strip("[]").split(":")
            processor = int(parts[0])
            link = int(parts[1])
            addr = int(parts[2])
        except (ValueError, IndexError):
            return  # Not a valid CCI address format

        # Check if this is a registered CCI device
        key = (processor, link, addr, button)
        if key not in self._cci_devices:
            return  # Not a CCI device, ignore

        old_state = self._cci_states.get(key)

        _LOGGER.debug(
            "CCI %s button %d: %s -> %s (from %s event)",
            normalized,
            button,
            "ON" if old_state else "OFF",
            "ON" if state else "OFF",
            "KBH" if state else "KBR",
        )

        if old_state != state:
            self._cci_states[key] = state

            # Notify registered callbacks
            callbacks = self._cci_callbacks.get(key, [])
            for cb in callbacks:
                try:
                    cb(state)
                except Exception as err:
                    _LOGGER.error("CCI callback error: %s", err)

            # Notify coordinator listeners
            self.async_set_updated_data(
                {"connected": True, "poll_count": self._poll_count}
            )

    # === Command Methods (proxies to client) ===

    async def async_cco_turn_on(self, device: CCODevice) -> bool:
        """Turn on a CCO device (handles inversion internally).

        Sets the correct logical optimistic state regardless of inversion.
        """
        address = device.address
        if device.inverted:
            result = await self._send_cco_open(address)
        else:
            result = await self._send_cco_close(address)
        if result:
            self._record_optimistic_state(address.unique_key, True)  # Logical ON
            self.async_set_updated_data(
                {"connected": True, "poll_count": self._poll_count}
            )
        return result

    async def async_cco_turn_off(self, device: CCODevice) -> bool:
        """Turn off a CCO device (handles inversion internally).

        Sets the correct logical optimistic state regardless of inversion.
        """
        address = device.address
        if device.inverted:
            result = await self._send_cco_close(address)
        else:
            result = await self._send_cco_open(address)
        if result:
            self._record_optimistic_state(address.unique_key, False)  # Logical OFF
            self.async_set_updated_data(
                {"connected": True, "poll_count": self._poll_count}
            )
        return result

    def _record_optimistic_state(
        self, key: tuple[int, int, int, int], state: bool
    ) -> None:
        """Apply an optimistic state and note it pending KLS confirmation.

        The next KLS for this relay is authoritative; the pending record only
        lets a contradiction be reported rather than silently reverting.
        """
        self._cco_states[key] = state
        self._cco_state_sources[key] = "optimistic"
        self._cco_pending_commands[key] = (state, self.hass.loop.time())

    async def _send_cco_close(self, address: CCOAddress) -> bool:
        """Send physical CCO close command."""
        if not self._client:
            return False
        return await self._client.cco_close(
            address.to_command_address(), address.button
        )

    async def _send_cco_open(self, address: CCOAddress) -> bool:
        """Send physical CCO open command."""
        if not self._client:
            return False
        return await self._client.cco_open(
            address.to_command_address(), address.button
        )

    async def async_fade_dim(
        self,
        address: str,
        level: float,
        fade_time: float = 1.0,
        delay_time: float = 0.0,
    ) -> bool:
        """Fade a dimmer to a level."""
        if not self._client:
            return False
        normalized = normalize_address(address)
        return await self._client.fade_dim(level, fade_time, delay_time, normalized)

    async def async_request_dimmer_level(self, address: str) -> bool:
        """Request current dimmer level."""
        if not self._client:
            return False
        normalized = normalize_address(address)
        return await self._client.request_dimmer_level(normalized)

    async def async_motor_cover_up(self, address: str) -> bool:
        """Raise a motor cover (RPM module)."""
        if not self._client:
            return False
        normalized = normalize_address(address)
        result = await self._client.motor_cover_up(normalized)
        if result:
            # Optimistically update the dimmer state
            self._dimmer_states[normalized] = RPM_MOTOR_UP
            self.async_set_updated_data({"motor_cover_update": normalized})
        return result

    async def async_motor_cover_down(self, address: str) -> bool:
        """Lower a motor cover (RPM module)."""
        if not self._client:
            return False
        normalized = normalize_address(address)
        result = await self._client.motor_cover_down(normalized)
        if result:
            # Optimistically update the dimmer state
            self._dimmer_states[normalized] = RPM_MOTOR_DOWN
            self.async_set_updated_data({"motor_cover_update": normalized})
        return result

    async def async_motor_cover_stop(self, address: str) -> bool:
        """Stop a motor cover (RPM module)."""
        if not self._client:
            return False
        normalized = normalize_address(address)
        result = await self._client.motor_cover_stop(normalized)
        if result:
            # Optimistically update the dimmer state
            self._dimmer_states[normalized] = RPM_MOTOR_STOP
            self.async_set_updated_data({"motor_cover_update": normalized})
        return result

    async def async_stop_dim(self, address: str) -> bool:
        """Stop a dimmer/shade mid-fade."""
        if not self._client:
            return False
        normalized = normalize_address(address)
        return await self._client.stop_dim(normalized)

    async def async_keypad_button_press(self, address: str, button: int) -> bool:
        """Simulate a keypad button press."""
        if not self._client:
            return False
        normalized = normalize_address(address)
        return await self._client.keypad_button_press(normalized, button)

    async def async_keypad_button_release(self, address: str, button: int) -> bool:
        """Simulate a keypad button release."""
        if not self._client:
            return False
        normalized = normalize_address(address)
        return await self._client.keypad_button_release(normalized, button)

    async def async_request_keypad_led_states(self, address: str) -> bool:
        """Request keypad LED states."""
        if not self._client:
            return False
        normalized = normalize_address(address)
        return await self._client.request_keypad_led_states(normalized)
