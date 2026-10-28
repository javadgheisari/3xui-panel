import json
import unittest
from unittest.mock import patch

from usage import UsageError, lookup_admin_uuid, lookup_subscription


class UsageLookupTests(unittest.TestCase):
    @patch("usage._request_json")
    def test_subscription_view_model_is_normalized(self, request_json):
        request_json.return_value = (
            {
                "enabled": True,
                "isOnline": True,
                "uploadByte": 100,
                "downloadByte": 300,
                "totalByte": 1000,
                "expire": 2_000_000_000,
                "lastOnline": 2_000_000_000_000,
                "subTitle": "  Gold   plan  ",
            },
            {},
        )

        result = lookup_subscription(
            "abc-1234",
            template="https://sub.example.com/random-path/{id}",
            timeout=2,
        )

        self.assertEqual(result.used_bytes, 400)
        self.assertEqual(result.remaining_bytes, 600)
        self.assertEqual(result.expires_at, 2_000_000_000_000)
        self.assertEqual(result.title, "Gold plan")
        called_url = request_json.call_args.args[0]
        self.assertEqual(called_url, "https://sub.example.com/random-path/abc-1234?format=info")

    @patch("usage._request_json")
    def test_subscription_headers_are_an_older_panel_fallback(self, request_json):
        request_json.return_value = (
            {"enabled": True},
            {"subscription-userinfo": "upload=10; download=20; total=100; expire=2000000000"},
        )
        result = lookup_subscription(
            "abcd1234",
            template="https://sub.example.com/sub/{id}",
            timeout=2,
        )
        self.assertEqual((result.upload_bytes, result.download_bytes), (10, 20))
        self.assertEqual(result.remaining_bytes, 70)

    @patch("usage._request_json")
    def test_admin_uuid_finds_nested_client_and_traffic(self, request_json):
        uuid = "e18c9a96-71bf-48d4-933f-8b9a46d4290c"
        request_json.return_value = (
            {
                "success": True,
                "obj": [
                    {
                        "enable": True,
                        "remark": "Primary",
                        "settings": json.dumps({"clients": [{"id": uuid, "email": "alice", "enable": True, "totalGB": 1000, "expiryTime": 2_000_000_000_000}]}),
                        "clientStats": [{"email": "alice", "up": 100, "down": 250, "enable": True}],
                    }
                ],
            },
            {},
        )
        result = lookup_admin_uuid(uuid, panel_url="https://panel.example.com/base", api_token="secret", timeout=2)
        self.assertEqual(result.used_bytes, 350)
        self.assertEqual(result.remaining_bytes, 650)
        self.assertEqual(result.title, "Primary")

    def test_invalid_subscription_id_is_rejected_before_network(self):
        with self.assertRaises(UsageError) as context:
            lookup_subscription("bad/id", template="https://example.com/{id}", timeout=2)
        self.assertEqual(context.exception.code, "invalid_id")


if __name__ == "__main__":
    unittest.main()

