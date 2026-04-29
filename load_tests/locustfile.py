from locust import HttpUser, task, between
import random

class RateLimitTester(HttpUser):
    wait_time = between(0.05, 0.2)

    def on_start(self):
        self.user_ids = [f"user_{i}" for i in range(20)]

    @task(4)
    def test_token_bucket(self):
        user_id = random.choice(self.user_ids)
        self.client.get(
            "/api/v1/check",
            headers={"X-Client-ID": user_id}
        )

    @task(1)
    def test_sliding_window(self):
        user_id = random.choice(self.user_ids)
        self.client.post(
            "/api/v1/rules",
            json={
                "client_id": user_id,
                "endpoint": "/api/v1/check",
                "algorithm": "sliding_window",
                "limit_count": 5,
                "window_seconds": 10
            }
        )