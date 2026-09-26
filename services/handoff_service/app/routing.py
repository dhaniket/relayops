REASON_TO_SKILL = {
    "PAYMENT_FAILURE": "billing",
    "CLAIM_DISPUTE": "claims",
    "POLICY_CHANGE": "policy_servicing",
}


def required_skill_for_reason(
    reason: str,
) -> str:
    return REASON_TO_SKILL[reason]
