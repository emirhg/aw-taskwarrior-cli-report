"""
Unit tests for ActivityWatch event fetching (tw_report.core.events).

Tests verify bucket ID construction and event fetching with graceful degradation
on connection errors. Uses mocking to avoid requiring a live ActivityWatch server.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from aw_core.models import Event

from tw_report.core.events import get_bucket_id, get_events


class TestGetBucketId:
    """Test bucket ID construction."""

    def test_bucket_id_format(self):
        """Bucket ID should follow aw-watcher-{name}_{hostname} format."""
        bucket_id = get_bucket_id("window")
        assert bucket_id.startswith("aw-watcher-window_")
        assert "_" in bucket_id  # Has hostname after underscore

    def test_bucket_id_includes_hostname(self):
        """Bucket ID should include current hostname."""
        import platform

        hostname = platform.node()
        bucket_id = get_bucket_id("afk")
        assert hostname in bucket_id
        assert bucket_id == f"aw-watcher-afk_{hostname}"

    def test_bucket_id_different_names(self):
        """Different bucket names should produce different IDs."""
        window_id = get_bucket_id("window")
        afk_id = get_bucket_id("afk")
        task_id = get_bucket_id("taskwarrior")

        assert window_id != afk_id
        assert afk_id != task_id
        assert "window" in window_id
        assert "afk" in afk_id
        assert "taskwarrior" in task_id


class TestGetEvents:
    """Test event fetching with connection error handling."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock ActivityWatchClient."""
        return Mock()

    @pytest.fixture
    def time_range(self):
        """Create a sample time range for testing."""
        start = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 7, 2, 0, 0, tzinfo=timezone.utc)
        return start, end

    @pytest.fixture
    def sample_events(self):
        """Create sample window events for testing."""
        now = datetime.now(timezone.utc)
        return [
            Event(
                timestamp=now,
                duration=timedelta(seconds=60),
                data={"app": "vim", "title": "file.py"},
            ),
            Event(
                timestamp=now + timedelta(seconds=60),
                duration=timedelta(seconds=120),
                data={"app": "chrome", "title": "GitHub - PR review"},
            ),
        ]

    def test_successful_fetch(self, mock_client, time_range, sample_events):
        """Successful fetch should return events list."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        result = get_events(mock_client, "aw-watcher-window_host", start, end)

        assert len(result) == 2
        assert result == sample_events
        mock_client.get_events.assert_called_once_with(
            "aw-watcher-window_host", start=start, end=end, limit=-1
        )

    def test_empty_bucket(self, mock_client, time_range):
        """Empty bucket should return empty list."""
        start, end = time_range
        mock_client.get_events.return_value = []

        result = get_events(mock_client, "aw-watcher-window_host", start, end)

        assert result == []
        assert isinstance(result, list)

    def test_connection_error_degrades_gracefully(self, mock_client, time_range):
        """Connection error should log warning and return empty list (degrade gracefully)."""
        start, end = time_range
        mock_client.get_events.side_effect = ConnectionError("Server unreachable")

        result = get_events(mock_client, "aw-watcher-window_host", start, end)

        # Should degrade gracefully, not raise
        assert result == []
        assert isinstance(result, list)

    def test_timeout_error_degrades_gracefully(self, mock_client, time_range):
        """Timeout error should log warning and return empty list."""
        start, end = time_range
        mock_client.get_events.side_effect = TimeoutError("Request timed out")

        result = get_events(mock_client, "aw-watcher-window_host", start, end)

        assert result == []

    def test_generic_exception_degrades_gracefully(self, mock_client, time_range):
        """Generic exception should log warning and return empty list."""
        start, end = time_range
        mock_client.get_events.side_effect = Exception(
            "Unexpected error from AW server"
        )

        result = get_events(mock_client, "aw-watcher-window_host", start, end)

        assert result == []

    def test_malformed_response_degrades_gracefully(self, mock_client, time_range):
        """Malformed response from server should degrade gracefully."""
        start, end = time_range
        # Simulate server returning invalid data
        mock_client.get_events.side_effect = ValueError(
            "Invalid JSON from server"
        )

        result = get_events(mock_client, "aw-watcher-window_host", start, end)

        assert result == []

    def test_uses_limit_all(self, mock_client, time_range):
        """get_events should request all events (limit=-1)."""
        start, end = time_range
        mock_client.get_events.return_value = []

        get_events(mock_client, "aw-watcher-window_host", start, end)

        # Verify limit=-1 is used (fetch all events, no pagination)
        call_kwargs = mock_client.get_events.call_args.kwargs
        assert call_kwargs["limit"] == -1

    def test_logging_on_success(self, mock_client, time_range, sample_events, caplog):
        """Successful fetch should log debug message."""
        import logging

        start, end = time_range
        mock_client.get_events.return_value = sample_events

        with caplog.at_level(logging.DEBUG, logger="tw_report.core.events"):
            get_events(mock_client, "aw-watcher-window_host", start, end)

        assert any("Fetched 2 events" in record.message for record in caplog.records)

    def test_logging_on_error(self, mock_client, time_range, caplog):
        """Failed fetch should log warning with exc_info."""
        import logging

        start, end = time_range
        mock_client.get_events.side_effect = ConnectionError("Server offline")

        with caplog.at_level(logging.WARNING, logger="tw_report.core.events"):
            get_events(mock_client, "aw-watcher-window_host", start, end)

        assert any(
            "Could not fetch events" in record.message for record in caplog.records
        )
        # exc_info=True should have been set
        assert any(record.exc_info for record in caplog.records)

    def test_different_buckets(self, mock_client, time_range, sample_events):
        """Should correctly handle different bucket IDs."""
        start, end = time_range
        mock_client.get_events.return_value = sample_events

        # Fetch from different buckets
        window_events = get_events(mock_client, "aw-watcher-window_host", start, end)
        afk_events = get_events(mock_client, "aw-watcher-afk_host", start, end)
        task_events = get_events(
            mock_client, "aw-watcher-taskwarrior_host", start, end
        )

        # All should be the same (mock returns same events)
        assert len(window_events) == 2
        assert len(afk_events) == 2
        assert len(task_events) == 2

        # Verify different bucket IDs were used
        calls = [call.args[0] for call in mock_client.get_events.call_args_list]
        assert "aw-watcher-window_host" in calls
        assert "aw-watcher-afk_host" in calls
        assert "aw-watcher-taskwarrior_host" in calls
