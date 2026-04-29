from locust import HttpUser, task, between
import uuid
import random

class RateLimitTester(HttpUser):
    # Wait between 0.1 and 0.5 seconds between tasks to simulate high load
    wait_time = between(0.1, 0.5)

    def on_start(self):
        """Prepare unique IDs for different test cases"""
        self.user_ids = [f"user_{i}" for i in range(10)]
        self.random_id = str(uuid.uuid4())

    @task(3)
    def test_token_bucket(self):
        """Standard user hitting the default token bucket rule"""
        user_id = random.choice(self.user_ids)
        self.client.get("/health", headers={"X-Client-ID": user_id})

    @task(1)
    def test_sliding_window(self):
        """Simulate a different endpoint to trigger other rules"""
        # Note: You can create a rule in Postgres for '/api/v1/data' 
        # using 'sliding_window' to test that specific logic!
        self.client.get("/api/v1/data", headers={"X-Client-ID": f"heavy_{self.random_id}"})

    @task(1)
    def test_no_header(self):
        """Test the fallback logic (using IP address)"""
        self.client.get("/health")