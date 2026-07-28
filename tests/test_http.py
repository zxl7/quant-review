#!/usr/bin/env python3

from __future__ import annotations

import http.client
import unittest
from unittest.mock import MagicMock, patch

from daily_review.http import HttpClient


class HttpClientTest(unittest.TestCase):
    def test_retries_truncated_response_body(self) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true}'
        client = HttpClient(base_url="https://example.invalid", token="token", retries=1)

        with (
            patch(
                "urllib.request.urlopen",
                side_effect=[http.client.IncompleteRead(b'{"ok"', 5), response],
            ) as urlopen,
            patch("daily_review.http.time.sleep"),
        ):
            result = client.api("test")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)

    def test_retries_invalid_utf8_response_body(self) -> None:
        broken = MagicMock()
        broken.__enter__.return_value.read.return_value = b'\xff'
        recovered = MagicMock()
        recovered.__enter__.return_value.read.return_value = b'{"rows": []}'
        client = HttpClient(base_url="https://example.invalid", token="token", retries=1)

        with (
            patch("urllib.request.urlopen", side_effect=[broken, recovered]) as urlopen,
            patch("daily_review.http.time.sleep"),
        ):
            result = client.api("test")

        self.assertEqual(result, {"rows": []})
        self.assertEqual(urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
