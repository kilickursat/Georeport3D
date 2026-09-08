from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from georeport3d.extraction_identity import EXTRACTION_CONTRACT_VERSION


@dataclass(frozen=True)
class CacheKeyParts:
    document_sha256: str
    figure_sha256: str
    model_id: str
    model_revision: str | None
    prompt_version: str
    preprocess_version: str
    extraction_contract_version: str = EXTRACTION_CONTRACT_VERSION


def make_cache_key(parts: CacheKeyParts) -> str:
    raw = json.dumps(
        {
            "schema": "georeport3d-cache-key-v1",
            "document_sha256": parts.document_sha256,
            "figure_sha256": parts.figure_sha256,
            "model_id": parts.model_id,
            "model_revision": parts.model_revision,
            "prompt_version": parts.prompt_version,
            "preprocess_version": parts.preprocess_version,
            "extraction_contract_version": parts.extraction_contract_version,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
