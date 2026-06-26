"""Synchronization test for normalize_address across all three implementations.

Ensures that models.py, hwi_protocol/protocol.py, and hwi_protocol/commands.py
all produce identical output for the same inputs.

This test catches drift if one implementation is modified without updating the others.
See: improvements_spec.md Part 6 (normalize_address Triplication)
"""

import pytest

from custom_components.homeworks_hwi.models import normalize_address as models_normalize
from custom_components.homeworks_hwi.hwi_protocol.protocol import normalize_address as proto_normalize


def _get_commands_normalize():
    """Try to import commands.normalize_address if it exists separately."""
    try:
        from custom_components.homeworks_hwi.hwi_protocol.commands import normalize_address as cmd_normalize
        return cmd_normalize
    except ImportError:
        # commands.py may import from protocol.py — that's fine
        return None


# Test cases covering all address formats
SYNC_TEST_CASES = [
    pytest.param("1:2:3", "[01:02:03]", id="bare_3part"),
    pytest.param("[01:02:03]", "[01:02:03]", id="already_normalized_3part"),
    pytest.param("[1:2:3]", "[01:02:03]", id="bracketed_unpadded"),
    pytest.param("1:2:3:4:5", "[01:02:03:04:05]", id="bare_5part"),
    pytest.param("[1:2:3:4:5]", "[01:02:03:04:05]", id="bracketed_5part"),
    pytest.param("[01:01:00:02:04]", "[01:01:00:02:04]", id="already_normalized_5part"),
    pytest.param("01:02:03", "[01:02:03]", id="padded_no_brackets"),
    pytest.param("2:6:3", "[02:06:03]", id="typical_keypad"),
    pytest.param("[02:06:03]", "[02:06:03]", id="typical_keypad_normalized"),
    pytest.param("1:4:1:1", "[01:04:01:01]", id="4part_qed"),
    pytest.param("1:4:1:1:1", "[01:04:01:01:01]", id="5part_dimmer"),
    pytest.param("[10:20:30]", "[10:20:30]", id="large_numbers"),
]


class TestNormalizeAddressSynchronization:
    """Ensure all normalize_address implementations produce identical output."""

    @pytest.mark.parametrize("input_addr,expected", SYNC_TEST_CASES)
    def test_models_implementation(self, input_addr, expected):
        """models.py normalize_address produces expected output."""
        assert models_normalize(input_addr) == expected

    @pytest.mark.parametrize("input_addr,expected", SYNC_TEST_CASES)
    def test_protocol_implementation(self, input_addr, expected):
        """hwi_protocol/protocol.py normalize_address produces expected output."""
        assert proto_normalize(input_addr) == expected

    @pytest.mark.parametrize("input_addr,expected", SYNC_TEST_CASES)
    def test_implementations_match(self, input_addr, expected):
        """All implementations produce identical output for the same input."""
        models_result = models_normalize(input_addr)
        proto_result = proto_normalize(input_addr)

        assert models_result == proto_result, (
            f"Mismatch for '{input_addr}': "
            f"models={models_result}, protocol={proto_result}"
        )

        # Check commands.py if it has its own implementation
        cmd_normalize = _get_commands_normalize()
        if cmd_normalize is not None and cmd_normalize is not proto_normalize:
            cmd_result = cmd_normalize(input_addr)
            assert models_result == cmd_result, (
                f"Mismatch for '{input_addr}': "
                f"models={models_result}, commands={cmd_result}"
            )


class TestNormalizeAddressEdgeCases:
    """Edge cases that all implementations must handle consistently."""

    @pytest.mark.parametrize(
        "input_addr",
        [
            pytest.param("0:0:0", id="all_zeros"),
            pytest.param("99:99:99", id="large_values"),
            pytest.param("[00:00:00]", id="zero_padded_brackets"),
        ],
    )
    def test_edge_cases_match(self, input_addr):
        """Edge cases produce matching results across implementations."""
        models_result = models_normalize(input_addr)
        proto_result = proto_normalize(input_addr)
        assert models_result == proto_result

    def test_normalize_is_idempotent(self):
        """Normalizing an already-normalized address returns the same string."""
        normalized = "[02:06:03]"
        assert models_normalize(normalized) == normalized
        assert proto_normalize(normalized) == normalized

        # Double-normalize
        assert models_normalize(models_normalize("2:6:3")) == "[02:06:03]"

    def test_normalize_strips_brackets(self):
        """Brackets are stripped before processing and re-added."""
        assert models_normalize("[1:2:3]") == models_normalize("1:2:3")
