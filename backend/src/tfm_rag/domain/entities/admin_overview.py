"""Domain shapes for the cross-tenant superadmin overview surface.

These are read-only reporting projections (never persisted), returned by
`AdminOverviewReaderPort`. Credentials are METADATA ONLY — the encrypted
`api_key_encrypted` blob is never exposed here.
"""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantUserSummary:
    id: UUID
    email: str
    is_superadmin: bool
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class TenantOverview:
    tenant_id: UUID
    name: str
    users: list[TenantUserSummary]


@dataclass(frozen=True, slots=True)
class ChatbotSummary:
    id: UUID
    name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeBaseSummary:
    id: UUID
    name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class CredentialSummary:
    id: UUID
    provider_id: str
    label: str
    base_url: str | None
    config_source: str


@dataclass(frozen=True, slots=True)
class TenantDetail:
    tenant_id: UUID
    chatbots: list[ChatbotSummary]
    knowledge_bases: list[KnowledgeBaseSummary]
    credentials: list[CredentialSummary]
