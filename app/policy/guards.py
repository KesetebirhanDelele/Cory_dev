from datetime import datetime, time
from typing import Tuple

class PolicyDenied(Exception):
    def __init__(self, code: str, reason: str): super().__init__(reason); self.code = code

def check_quiet_hours(now: datetime, start=time(21,0), end=time(8,0)) -> None:
    n = now.time()
    if (start <= n) or (n < end):
        raise PolicyDenied("quiet_hours", "Sending blocked during quiet hours")

def check_consent(has_consent: bool) -> None:
    if not has_consent:
        raise PolicyDenied("no_consent", "Missing contact consent")

def check_frequency(sent_last_hours: int, cap:int=3) -> None:
    if sent_last_hours >= cap:
        raise PolicyDenied("freq_cap", "Frequency cap reached")
