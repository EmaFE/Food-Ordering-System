import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
import httpx

logger = logging.getLogger(__name__)

# Circuit breaker's states
class CBState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """
    Class for the circuit breaker logic in main
    """
    def __init__(self, failure_threshold = 3, recovery_timeout = 15):
        self.state = CBState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout


    def _should_attempt(self):
        """
        Updates current state of the breaker based on time open
        Return value is whether a call should be let through
        """
        if self.state == CBState.CLOSED:
            return True

        if self.state == CBState.OPEN:
            elapsed = datetime.now(timezone.utc) - self.last_failure_time
            
            if elapsed > timedelta(seconds = self.recovery_timeout):
                logger.info("[CircuitBreaker] OPEN → HALF_OPEN")
                self.state = CBState.HALF_OPEN
                return True
            
            return False

        # self.state == CBState.HALF_OPEN - allow one probe through
        return True


    def record_success(self):
        logger.info("[CircuitBreaker] Success - resetting to CLOSED")
        self.state = CBState.CLOSED
        self.failure_count = 0


    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)

        # Circuit breaker state is updated to open if there have been too many failures
        if self.state == CBState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            logger.warning(f"[CircuitBreaker] OPEN (failures = {self.failure_count})")
            self.state = CBState.OPEN
        
        else:
            logger.warning(f"[CircuitBreaker] Failure {self.failure_count}/{self.failure_threshold}")


    async def call(self, coro):
        """
        Execture coro through circuit breaker.
        Throws an error if there is an issue
        """
        if not self._should_attempt():
            raise RuntimeError("Circuit breaker is OPEN - Payment service unavailable")
        
        try:
            result = await coro
            self.record_success()
            return result
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 402: # payment declined
                self.record_success()
                raise e
            
            self.record_failure()
            raise e

        except Exception as e:
            self.record_failure()
            raise e


    def status(self):
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }