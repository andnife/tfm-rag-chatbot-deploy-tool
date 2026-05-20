from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OAuthProfile:
    sub: str
    email: str
    email_verified: bool


class OAuthVerifier(ABC):
    @abstractmethod
    async def verify(self, id_token: str) -> OAuthProfile:
        """Verify the id_token signature + claims. Raises if invalid."""
