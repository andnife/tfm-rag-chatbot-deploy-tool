from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Root SQLAlchemy declarative base. All ORM models inherit from this."""
    pass
