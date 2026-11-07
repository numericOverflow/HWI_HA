"""Fake Homeworks controller for testing."""

import asyncio
import logging
from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)


class FakeHomeworksController:
    """A fake Homeworks controller for testing.

    Simulates the RS-232 interface behavior including:
    - Login handling
    - KLS responses to RKLS commands
    - DL responses to RDL commands
    - CCOOPEN/CCOCLOSE commands with KLS feedback
    """

    def __init__(
        self,
        port: int = 0,
        require_login: bool = False,
        credentials: bytes = b"test, test",
    ):
        """Initialize the fake controller."""
        self._port = port
        self._require_login = require_login
        self._credentials = credentials
        self._server: asyncio.Server | None = None
        self._clients: list[asyncio.StreamWriter] = []
        self._running = False

        # Simulated state
        self._kls_states: dict[str, list[int]] = {}
        self._dimmer_levels: dict[str, int] = {}

        # Event hooks for testing
        self._on_command: Callable[[str], None] | None = None

    @property
    def port(self) -> int:
        """Return the server port."""
        return self._port

    def set_kls_state(self, address: str, led_states: list[int]) -> None:
        """Set the KLS state for an address."""
        self._kls_states[address] = led_states

    def set_dimmer_level(self, address: str, level: int) -> None:
        """Set the dimmer level for an address."""
        self._dimmer_levels[address] = level

    def set_cco_state(self, address: str, button: int, is_on: bool) -> None:
        """Set the CCO state for a specific button.

        Args:
            address: The KLS address (e.g., "[02:06:03]")
            button: The button number (1-24)
            is_on: True for ON (1), False for OFF (2)
        """
        if address not in self._kls_states:
            self._kls_states[address] = [0] * 24

        # Set the button state: 1 = ON, 2 = OFF
        self._kls_states[address][button - 1] = 1 if is_on else 2

    async def start(self) -> None:
        """Start the fake controller server."""
        self._running = True
        self._server = await asyncio.start_server(
            self._handle_client,
            "127.0.0.1",
            self._port,
        )
        # Get the actual port if we used port 0
        if self._port == 0:
            self._port = self._server.sockets[0].getsockname()[1]

        _LOGGER.info("Fake controller started on port %d", self._port)

    async def stop(self) -> None:
        """Stop the fake controller server."""
        self._running = False

        # Close all client connections
        for writer in self._clients:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001, S110 - teardown is best effort
                pass

        self._clients.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a client connection."""
        self._clients.append(writer)
        _LOGGER.debug("Client connected")

        try:
            # Send login prompt if required
            if self._require_login:
                writer.write(b"LOGIN: ")
                await writer.drain()

                # Wait for credentials
                data = await reader.readline()
                if data.strip() == self._credentials:
                    writer.write(b"login successful\r\n")
                else:
                    writer.write(b"login incorrect\r\n")
                    writer.close()
                    return
                await writer.drain()

            # Process commands
            buffer = b""
            while self._running:
                try:
                    data = await asyncio.wait_for(reader.read(1024), timeout=1.0)
                    if not data:
                        break

                    buffer += data

                    # Process complete commands
                    while b"\r\n" in buffer:
                        command, buffer = buffer.split(b"\r\n", 1)
                        if command:
                            await self._process_command(command.decode("utf-8"), writer)

                except TimeoutError:
                    continue

        except Exception as err:  # noqa: BLE001 - a client error must not stop the server
            _LOGGER.debug("Client error: %s", err)
        finally:
            if writer in self._clients:
                self._clients.remove(writer)
            writer.close()

    async def _process_command(
        self, command: str, writer: asyncio.StreamWriter
    ) -> None:
        """Process a command from the client."""
        _LOGGER.debug("Received command: %s", command)

        if self._on_command:
            self._on_command(command)

        parts = command.split(", ")
        cmd = parts[0].upper()

        if cmd == "PROMPTOFF":
            pass  # No response needed

        elif cmd == "KBMON":
            writer.write(b"Keypad button monitoring enabled\r\n")
            await writer.drain()

        elif cmd == "DLMON":
            writer.write(b"Dimmer level monitoring enabled\r\n")
            await writer.drain()

        elif cmd == "KLMON":
            writer.write(b"Keypad led monitoring enabled\r\n")
            await writer.drain()

        elif cmd == "GSMON":
            writer.write(b"GrafikEye scene monitoring enabled\r\n")
            await writer.drain()

        elif cmd == "RKLS" and len(parts) >= 2:
            # Request keypad LED states
            address = parts[1].strip()
            led_states = self._kls_states.get(address, [0] * 24)
            led_string = "".join(str(s) for s in led_states)
            response = f"KLS, {address}, {led_string}\r\n"
            writer.write(response.encode())
            await writer.drain()

        elif cmd == "RDL" and len(parts) >= 2:
            # Request dimmer level
            address = parts[1].strip()
            level = self._dimmer_levels.get(address, 0)
            response = f"DL, {address}, {level}\r\n"
            writer.write(response.encode())
            await writer.drain()

        elif cmd == "CCOCLOSE" and len(parts) >= 3:
            # Close CCO relay
            address = parts[1].strip()
            button = int(parts[2].strip())
            self.set_cco_state(address, button, True)

            # Send KLS update
            led_states = self._kls_states.get(address, [0] * 24)
            led_string = "".join(str(s) for s in led_states)
            response = f"KLS, {address}, {led_string}\r\n"
            writer.write(response.encode())
            await writer.drain()

        elif cmd == "CCOOPEN" and len(parts) >= 3:
            # Open CCO relay
            address = parts[1].strip()
            button = int(parts[2].strip())
            self.set_cco_state(address, button, False)

            # Send KLS update
            led_states = self._kls_states.get(address, [0] * 24)
            led_string = "".join(str(s) for s in led_states)
            response = f"KLS, {address}, {led_string}\r\n"
            writer.write(response.encode())
            await writer.drain()

        elif cmd == "FADEDIM" and len(parts) >= 5:
            # Fade dimmer
            level = int(float(parts[1].strip()))
            address = parts[4].strip()
            self._dimmer_levels[address] = level

            # Send DL update
            response = f"DL, {address}, {level}\r\n"
            writer.write(response.encode())
            await writer.drain()

    async def simulate_kls_change(self, address: str) -> None:
        """Simulate a KLS change (broadcast to all clients)."""
        led_states = self._kls_states.get(address, [0] * 24)
        led_string = "".join(str(s) for s in led_states)
        message = f"KLS, {address}, {led_string}\r\n"

        for writer in self._clients:
            try:
                writer.write(message.encode())
                await writer.drain()
            except Exception:  # noqa: BLE001, S110 - skip clients that already left
                pass

    async def simulate_disconnect(self) -> None:
        """Simulate a disconnect (close all client connections)."""
        for writer in self._clients:
            writer.close()
        self._clients.clear()
