import unittest
from unittest.mock import patch

from usage import UsageError, lookup_client


TEMPLATE = "https://panel.example.com/base/panel/api/clients/get/{name}"


class ClientLookupTests(unittest.TestCase):
    @patch("usage._request_client")
    def test_panel_volume_response_is_normalized_without_credentials(self, request_client):
        request_client.return_value = {
            "success": True,
            "obj": {
                "client": {
                    "email": "alice",
                    "password": "must-stay-on-server",
                    "totalGB": 21_474_836_480,
                    "expiryTime": 0,
                    "enable": True,
                },
                "usedTraffic": 21_257_943_356,
                "inboundIds": [4],
            },
        }

        result = lookup_client("alice", template=TEMPLATE, api_token="token", timeout=2).public_dict()

        self.assertEqual(result["usedTraffic"], 21_257_943_356)
        self.assertEqual(result["totalGB"], 21_474_836_480)
        self.assertEqual(result["remainingTraffic"], 216_893_124)
        self.assertEqual(result["inboundIds"], [4])
        self.assertNotIn("password", result)
        self.assertNotIn("client", result)
        request_client.assert_called_once_with(
            "https://panel.example.com/base/panel/api/clients/get/alice", "token", 2
        )

    @patch("usage._request_client")
    def test_name_is_encoded_in_url(self, request_client):
        request_client.return_value = {
            "success": True,
            "obj": {
                "client": {"totalGB": 0, "expiryTime": 0, "enable": True},
                "usedTraffic": 100,
                "inboundIds": [],
            },
        }
        result = lookup_client("alice@example.com", template=TEMPLATE, api_token="token", timeout=2)
        self.assertIsNone(result.remainingTraffic)
        self.assertEqual(
            request_client.call_args.args[0],
            "https://panel.example.com/base/panel/api/clients/get/alice%40example.com",
        )

    @patch("usage._request_client")
    def test_missing_volume_is_rejected_instead_of_shown_as_zero(self, request_client):
        request_client.return_value = {
            "success": True,
            "obj": {
                "client": {"totalGB": 1000, "expiryTime": 0, "enable": True},
                "inboundIds": [],
            },
        }
        with self.assertRaises(UsageError):
            lookup_client("alice", template=TEMPLATE, api_token="token", timeout=2)

    def test_invalid_name_is_rejected_before_request(self):
        with self.assertRaises(UsageError) as context:
            lookup_client("../alice", template=TEMPLATE, api_token="token", timeout=2)
        self.assertEqual(context.exception.code, "invalid_name")


if __name__ == "__main__":
    unittest.main()
