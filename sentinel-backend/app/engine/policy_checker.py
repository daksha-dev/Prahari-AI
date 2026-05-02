from __future__ import annotations

from dataclasses import dataclass

FORBIDDEN_PORTS = {23, 4444, 5555, 6667}


@dataclass
class PolicyViolation:
    rule: str
    penalty: float
    detail: str


def check_policy(features: dict[str, float], ports: list[int] | None = None) -> tuple[float, list[PolicyViolation]]:
    violations: list[PolicyViolation] = []
    ports = ports or []

    if features.get("new_dst_count", 0.0) > 20:
        violations.append(PolicyViolation("new_dst_count", 15.0, "New destination count exceeded 20."))
    if features.get("bytes_per_sec", 0.0) > 100_000:
        violations.append(PolicyViolation("bytes_per_sec", 20.0, "Traffic exceeded 100k bytes/sec."))
    bad_ports = sorted(FORBIDDEN_PORTS.intersection(ports))
    if bad_ports:
        violations.append(PolicyViolation("forbidden_port", 25.0, f"Forbidden ports observed: {bad_ports}."))
    if features.get("syn_ack_ratio", 0.0) > 5.0:
        violations.append(PolicyViolation("syn_ack_ratio", 15.0, "SYN/ACK ratio exceeded 5.0."))

    return sum(v.penalty for v in violations), violations
