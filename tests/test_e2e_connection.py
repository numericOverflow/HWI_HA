"""Tests for end-to-end connection flow using FakeHomeworksController.

These tests validate the full TCP interaction:
- Connect to controller
- Login sequence (when required)
- RKLS command → KLS response
- RDL command → DL response
- CCOCLOSE/CCOOPEN → state change + KLS broadcast
- FADEDIM → DL broadcast
- Disconnect handling
"""

import asyncio

import pytest

from tests.fake_controller import FakeHomeworksController


@pytest.fixture
async def controller():
    """Start a fresh fake controller for each test."""
    ctrl = FakeHomeworksController(port=0, require_login=False)
    await ctrl.start()
    yield ctrl
    await ctrl.stop()


@pytest.fixture
async def controller_with_login():
    """Start a fake controller that requires login."""
    ctrl = FakeHomeworksController(port=0, require_login=True)
    await ctrl.start()
    yield ctrl
    await ctrl.stop()


# =============================================================================
# Basic Connectivity Tests
# =============================================================================


class TestBasicConnectivity:
    """Tests for basic TCP connection behavior."""

    @pytest.mark.asyncio
    async def test_connect_to_controller(self, controller):
        """Client can connect to the fake controller."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", controller.port
        )
        assert reader is not None
        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_multiple_clients(self, controller):
        """Controller accepts multiple simultaneous clients."""
        connections = []
        for _ in range(3):
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", controller.port
            )
            connections.append((reader, writer))

        assert len(connections) == 3

        for _, writer in connections:
            writer.close()
            await writer.wait_closed()


# =============================================================================
# Login Tests
# =============================================================================


class TestLoginFlow:
    """Tests for the login authentication flow."""

    @pytest.mark.asyncio
    async def test_login_success(self, controller_with_login):
        """Correct credentials receive 'login successful'."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", controller_with_login.port
        )

        # Read login prompt
        prompt = await asyncio.wait_for(reader.read(100), timeout=2.0)
        assert b"LOGIN:" in prompt

        # Send credentials
        writer.write(b"test, test\r\n")
        await writer.drain()

        # Read response
        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert b"login successful" in response

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_login_failure(self, controller_with_login):
        """Wrong credentials get rejected."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", controller_with_login.port
        )

        # Read login prompt
        await asyncio.wait_for(reader.read(100), timeout=2.0)

        # Send wrong credentials
        writer.write(b"wrong, wrong\r\n")
        await writer.drain()

        # Read response
        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert b"login incorrect" in response

        writer.close()
        await writer.wait_closed()


# =============================================================================
# KLS Command Tests
# =============================================================================


class TestKLSCommands:
    """Tests for RKLS request/response cycle."""

    @pytest.mark.asyncio
    async def test_rkls_default_all_zeros(self, controller):
        """RKLS for unknown address returns all zeros."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", controller.port
        )

        writer.write(b"RKLS, [02:06:03]\r\n")
        await writer.drain()

        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert b"KLS, [02:06:03]," in response
        # Default state is all zeros (24 digits)
        kls_part = response.decode().strip().split(", ")[2]
        assert len(kls_part) == 24
        assert kls_part == "0" * 24

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_rkls_returns_set_state(self, controller):
        """RKLS returns previously set KLS state."""
        controller.set_kls_state("[02:06:03]", [0] * 9 + [2, 2, 2, 1, 1, 2, 1, 1] + [0] * 7)

        reader, writer = await asyncio.open_connection(
            "127.0.0.1", controller.port
        )

        writer.write(b"RKLS, [02:06:03]\r\n")
        await writer.drain()

        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        kls_part = response.decode().strip().split(", ")[2]
        assert kls_part == "000000000222112110000000"

        writer.close()
        await writer.wait_closed()


# =============================================================================
# CCO Command Tests
# =============================================================================


class TestCCOCommands:
    """Tests for CCOCLOSE/CCOOPEN command behavior."""

    @pytest.mark.asyncio
    async def test_ccoclose_updates_state(self, controller):
        """CCOCLOSE sets the button state to ON and broadcasts KLS."""
        controller.set_kls_state("[02:06:03]", [0] * 24)

        reader, writer = await asyncio.open_connection(
            "127.0.0.1", controller.port
        )

        writer.write(b"CCOCLOSE, [02:06:03], 6\r\n")
        await writer.drain()

        # Should get KLS response
        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert b"KLS, [02:06:03]," in response

        # Button 6 (0-indexed position 5) should be 1 (ON)
        kls_part = response.decode().strip().split(", ")[2]
        assert kls_part[5] == "1"

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_ccoopen_updates_state(self, controller):
        """CCOOPEN sets the button state to OFF and broadcasts KLS."""
        # First set button 6 to ON
        controller.set_cco_state("[02:06:03]", 6, True)

        reader, writer = await asyncio.open_connection(
            "127.0.0.1", controller.port
        )

        writer.write(b"CCOOPEN, [02:06:03], 6\r\n")
        await writer.drain()

        # Should get KLS response
        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert b"KLS, [02:06:03]," in response

        # Button 6 should now be 2 (OFF)
        kls_part = response.decode().strip().split(", ")[2]
        assert kls_part[5] == "2"

        writer.close()
        await writer.wait_closed()


# =============================================================================
# Dimmer Command Tests
# =============================================================================


class TestDimmerCommands:
    """Tests for FADEDIM/RDL command behavior."""

    @pytest.mark.asyncio
    async def test_rdl_returns_level(self, controller):
        """RDL returns the current dimmer level."""
        controller.set_dimmer_level("[01:01:00:02:04]", 75)

        reader, writer = await asyncio.open_connection(
            "127.0.0.1", controller.port
        )

        writer.write(b"RDL, [01:01:00:02:04]\r\n")
        await writer.drain()

        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert b"DL, [01:01:00:02:04], 75" in response

        writer.close()
        await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_fadedim_updates_level(self, controller):
        """FADEDIM sets level and returns DL response."""
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", controller.port
        )

        writer.write(b"FADEDIM, 80, 1, 0, [01:01:00:02:04]\r\n")
        await writer.drain()

        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert b"DL, [01:01:00:02:04], 80" in response

        writer.close()
        await writer.wait_closed()


# =============================================================================
# Broadcast Tests
# =============================================================================


class TestBroadcasts:
    """Tests for simulated broadcasts to connected clients."""

    @pytest.mark.asyncio
    async def test_kls_broadcast_to_client(self, controller):
        """simulate_kls_change sends KLS to all connected clients."""
        controller.set_kls_state("[02:06:03]", [1] * 24)

        reader, writer = await asyncio.open_connection(
            "127.0.0.1", controller.port
        )

        # Give connection time to register
        await asyncio.sleep(0.1)

        # Simulate broadcast
        await controller.simulate_kls_change("[02:06:03]")

        response = await asyncio.wait_for(reader.readline(), timeout=2.0)
        assert b"KLS, [02:06:03]," in response

        writer.close()
        await writer.wait_closed()
