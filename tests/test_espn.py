import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from rosterlab.espn import ESPNAuthenticationError, ESPNClient, ESPNConfig


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def http_error(url, code):
    return HTTPError(url, code, "error", {}, io.BytesIO(b"{}"))


class ESPNClientTests(unittest.TestCase):
    @patch("rosterlab.espn.time.sleep", return_value=None)
    @patch("rosterlab.espn.urlopen")
    def test_authenticated_request_sends_cookie_and_falls_back_to_alternate_host(
        self, urlopen, _sleep
    ):
        urlopen.side_effect = [
            http_error("https://lm-api-reads.fantasy.espn.com", 401),
            FakeResponse({"settings": {}, "teams": [{"id": 1}]}),
        ]
        client = ESPNClient(ESPNConfig(99, 2026, "session-cookie", "{owner}"))
        result = client.fetch_league()
        self.assertEqual(result["teams"][0]["id"], 1)
        first_request = urlopen.call_args_list[0].args[0]
        second_request = urlopen.call_args_list[1].args[0]
        self.assertIn("espn_s2=session-cookie", first_request.get_header("Cookie"))
        self.assertIn("fantasy.espn.com", second_request.full_url)

    @patch("rosterlab.espn.time.sleep", return_value=None)
    @patch("rosterlab.espn.urlopen")
    def test_rejected_session_has_actionable_error_without_echoing_cookie(
        self, urlopen, _sleep
    ):
        urlopen.side_effect = [
            http_error("https://example.test", 401),
            http_error("https://example.test", 401),
            http_error("https://example.test", 401),
        ]
        client = ESPNClient(ESPNConfig(99, 2026, "do-not-echo", "{owner}"))
        with self.assertRaises(ESPNAuthenticationError) as caught:
            client.fetch_league()
        self.assertIn("rosterlab login", str(caught.exception))
        self.assertNotIn("do-not-echo", str(caught.exception))

    @patch("rosterlab.espn.urlopen")
    def test_player_pool_requests_explicit_weekly_projection_id(self, urlopen):
        urlopen.return_value = FakeResponse({"players": [{"id": 7, "player": {"id": 7}}]})
        client = ESPNClient(ESPNConfig(99, 2026))
        client.fetch_player_pool(9, page_size=10)
        request = urlopen.call_args.args[0]
        fantasy_filter = json.loads(request.get_header("X-fantasy-filter"))
        stats_filter = fantasy_filter["players"]["filterStatsForTopScoringPeriodIds"]
        self.assertEqual(stats_filter["value"], 5)
        self.assertEqual(
            stats_filter["additionalValue"],
            ["002026", "102026", "1120269"],
        )


if __name__ == "__main__":
    unittest.main()
