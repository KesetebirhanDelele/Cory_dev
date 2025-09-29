from datetime import timedelta

SMS  = dict(start_to_close_timeout=timedelta(seconds=20), retry_policy={"maximum_attempts": 3, "backoff_coefficient": 2.0})
EMAIL= dict(start_to_close_timeout=timedelta(seconds=20), retry_policy={"maximum_attempts": 3, "backoff_coefficient": 2.0})
VOICE= dict(start_to_close_timeout=timedelta(seconds=30), retry_policy={"maximum_attempts": 2, "backoff_coefficient": 2.0})
