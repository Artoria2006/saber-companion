import unittest
from fastapi.testclient import TestClient
from scripts.run_asr_api import create_app


class AsrHealthTests(unittest.TestCase):
    def test_health_reports_selected_model(self):
        with TestClient(create_app(object(), {}, 'small')) as client:
            response = client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['model'], 'small')


if __name__ == '__main__':
    unittest.main()
