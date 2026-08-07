from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Iterable


class SetupLifecycleState(StrEnum):
    OBSERVING = "observing"
    CONTEXT_ELIGIBLE = "context_eligible"
    LOCATION_ARMED = "location_armed"
    CATALYST_DETECTED = "catalyst_detected"
    CONFIRMATION_PENDING = "confirmation_pending"
    CANDIDATE_PRODUCED = "candidate_produced"
    EXPIRED = "expired"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


_TERMINAL = {
    SetupLifecycleState.CANDIDATE_PRODUCED,
    SetupLifecycleState.EXPIRED,
    SetupLifecycleState.REJECTED,
    SetupLifecycleState.INVALIDATED,
}

_ALLOWED: dict[SetupLifecycleState, frozenset[SetupLifecycleState]] = {
    SetupLifecycleState.OBSERVING: frozenset({
        SetupLifecycleState.CONTEXT_ELIGIBLE,
        SetupLifecycleState.REJECTED,
        SetupLifecycleState.EXPIRED,
    }),
    SetupLifecycleState.CONTEXT_ELIGIBLE: frozenset({
        SetupLifecycleState.LOCATION_ARMED,
        SetupLifecycleState.REJECTED,
        SetupLifecycleState.EXPIRED,
    }),
    SetupLifecycleState.LOCATION_ARMED: frozenset({
        SetupLifecycleState.CATALYST_DETECTED,
        SetupLifecycleState.INVALIDATED,
        SetupLifecycleState.EXPIRED,
    }),
    SetupLifecycleState.CATALYST_DETECTED: frozenset({
        SetupLifecycleState.CONFIRMATION_PENDING,
        SetupLifecycleState.INVALIDATED,
        SetupLifecycleState.EXPIRED,
    }),
    SetupLifecycleState.CONFIRMATION_PENDING: frozenset({
        SetupLifecycleState.CANDIDATE_PRODUCED,
        SetupLifecycleState.INVALIDATED,
        SetupLifecycleState.REJECTED,
        SetupLifecycleState.EXPIRED,
    }),
}


@dataclass(frozen=True, slots=True)
class SetupTransition:
    transition_id: str
    setup_id: str
    from_state: SetupLifecycleState
    to_state: SetupLifecycleState
    available_at: datetime
    event_id: str
    reason: str

    @classmethod
    def create(
        cls,
        *,
        setup_id: str,
        from_state: SetupLifecycleState,
        to_state: SetupLifecycleState,
        available_at: datetime,
        event_id: str,
        reason: str,
    ) -> "SetupTransition":
        if available_at.tzinfo is None:
            raise ValueError("transition time must be timezone-aware")
        if from_state in _TERMINAL or to_state not in _ALLOWED.get(from_state, frozenset()):
            raise ValueError(f"invalid setup transition {from_state.value}->{to_state.value}")
        raw = f"{setup_id}|{from_state.value}|{to_state.value}|{available_at.isoformat()}|{event_id}|{reason}"
        transition_id = hashlib.sha256(raw.encode()).hexdigest()[:28]
        return cls(transition_id, setup_id, from_state, to_state, available_at, event_id, reason)


@dataclass(frozen=True, slots=True)
class SetupInstance:
    setup_id: str
    instrument: str
    setup_family: str
    policy_version: str
    state: SetupLifecycleState
    created_at: datetime
    updated_at: datetime
    anchor_id: str

    @classmethod
    def create(
        cls,
        *,
        instrument: str,
        setup_family: str,
        policy_version: str,
        created_at: datetime,
        anchor_id: str,
    ) -> "SetupInstance":
        if created_at.tzinfo is None:
            raise ValueError("setup created_at must be timezone-aware")
        raw = f"{instrument.upper()}|{setup_family}|{policy_version}|{created_at.isoformat()}|{anchor_id}"
        setup_id = hashlib.sha256(raw.encode()).hexdigest()[:28]
        return cls(
            setup_id=setup_id,
            instrument=instrument.upper(),
            setup_family=setup_family,
            policy_version=policy_version,
            state=SetupLifecycleState.OBSERVING,
            created_at=created_at,
            updated_at=created_at,
            anchor_id=anchor_id,
        )

    def apply(self, transition: SetupTransition) -> "SetupInstance":
        if transition.setup_id != self.setup_id:
            raise ValueError("transition belongs to a different setup")
        if transition.from_state is not self.state:
            raise ValueError("transition from_state does not match setup state")
        if transition.available_at < self.updated_at:
            raise ValueError("transition cannot move setup time backwards")
        return SetupInstance(
            setup_id=self.setup_id,
            instrument=self.instrument,
            setup_family=self.setup_family,
            policy_version=self.policy_version,
            state=transition.to_state,
            created_at=self.created_at,
            updated_at=transition.available_at,
            anchor_id=self.anchor_id,
        )

    @property
    def terminal(self) -> bool:
        return self.state in _TERMINAL


def replay_setup(initial: SetupInstance, transitions: Iterable[SetupTransition]) -> SetupInstance:
    current = initial
    ordered = sorted(transitions, key=lambda item: (item.available_at, item.transition_id))
    for transition in ordered:
        current = current.apply(transition)
    return current
