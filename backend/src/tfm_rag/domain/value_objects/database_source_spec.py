"""Value object: request shape for attaching a DatabaseSource.

Carries the PLAINTEXT password. The use case encrypts it before
persisting into Source.payload. The VO itself is short-lived (request
scope) so we don't bother zeroing memory on drop.
"""
from dataclasses import dataclass
from typing import Literal

DatabaseDriver = Literal["postgres", "mysql"]
SslMode = Literal["disable", "require"]


@dataclass(frozen=True, slots=True)
class DatabaseSourceSpec:
    driver: DatabaseDriver
    host: str
    port: int
    db_name: str
    username: str
    password: str
    ssl_mode: SslMode = "disable"

    def to_connector_spec(self) -> dict[str, str | int]:
        """Plaintext dict shape that DatabaseConnector.test_connection /
        introspect_schema consumes."""
        return {
            "driver": self.driver,
            "host": self.host,
            "port": self.port,
            "db_name": self.db_name,
            "username": self.username,
            "password": self.password,
            "ssl_mode": self.ssl_mode,
        }
