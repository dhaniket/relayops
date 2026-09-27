import hashlib
import json

from services.handoff_service.app.schemas import (
    HandoffCreateRequest,
)


def build_fingerprints(
    request: HandoffCreateRequest,
    idempotency_key: str,
) -> tuple[str, str]:

    key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()

    payload = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )

    request_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    return key_hash, request_hash
