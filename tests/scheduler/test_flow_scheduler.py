from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from saap.scheduler.flow_scheduler import CampaignEnrollment, FlowScheduler, InMemoryEnrollmentStore

NOW = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)


class ScriptedConsentRegistry:
    def __init__(self, revoked_purposes: frozenset[str] = frozenset()) -> None:
        self._revoked = revoked_purposes

    async def has_consent(self, tenant_id: UUID, principal_id: str, purpose: str) -> bool:
        return purpose not in self._revoked


class RecordingDispatcher:
    def __init__(self, fail_for: frozenset[str] = frozenset()) -> None:
        self.calls: list[CampaignEnrollment] = []
        self._fail_for = fail_for

    async def dispatch(self, enrollment: CampaignEnrollment) -> None:
        self.calls.append(enrollment)
        if enrollment.campaign in self._fail_for:
            raise RuntimeError(f"boom: {enrollment.campaign}")


def _enrollment(campaign: str, *, due: datetime | None = NOW, state: str = "pending") -> CampaignEnrollment:
    return CampaignEnrollment(
        id=uuid4(),
        tenant_id=uuid4(),
        principal_id="patient-1",
        campaign=campaign,
        state=state,
        next_action_at=due,
        version=1,
    )


async def test_tick_dispatches_due_enrollment_and_marks_it_done() -> None:
    enrollment = _enrollment("dental_recall")
    store = InMemoryEnrollmentStore([enrollment])
    dispatcher = RecordingDispatcher()
    scheduler = FlowScheduler(store, ScriptedConsentRegistry(), dispatcher)

    await scheduler.tick(NOW)

    assert [e.campaign for e in dispatcher.calls] == ["dental_recall"]
    assert (await store.due(NOW)) == []  # no longer pending


async def test_tick_skips_enrollments_not_yet_due() -> None:
    not_due = _enrollment("dental_recall", due=NOW + timedelta(days=1))
    store = InMemoryEnrollmentStore([not_due])
    dispatcher = RecordingDispatcher()
    scheduler = FlowScheduler(store, ScriptedConsentRegistry(), dispatcher)

    await scheduler.tick(NOW)

    assert dispatcher.calls == []


async def test_tick_halts_on_revoked_consent_without_dispatching() -> None:
    enrollment = _enrollment("dental_recall")
    store = InMemoryEnrollmentStore([enrollment])
    dispatcher = RecordingDispatcher()
    scheduler = FlowScheduler(
        store, ScriptedConsentRegistry(revoked_purposes=frozenset({"dental_recall"})), dispatcher
    )

    await scheduler.tick(NOW)

    assert dispatcher.calls == []
    remaining = store._rows[enrollment.id]  # noqa: SLF001 - white-box assertion on the fake store
    assert remaining.state == "failed"


async def test_tick_marks_failed_on_dispatch_error_without_raising() -> None:
    ok = _enrollment("welcome_series")
    bad = _enrollment("broken_campaign")
    store = InMemoryEnrollmentStore([bad, ok])
    dispatcher = RecordingDispatcher(fail_for=frozenset({"broken_campaign"}))
    scheduler = FlowScheduler(store, ScriptedConsentRegistry(), dispatcher)

    await scheduler.tick(NOW)  # must not raise despite one dispatch failing

    assert {e.campaign for e in dispatcher.calls} == {"broken_campaign", "welcome_series"}
    assert store._rows[bad.id].state == "failed"  # noqa: SLF001
    assert store._rows[ok.id].state == "done"  # noqa: SLF001


async def test_claim_is_a_compare_and_swap() -> None:
    enrollment = _enrollment("dental_recall")
    store = InMemoryEnrollmentStore([enrollment])

    first = await store.claim(enrollment.id, expected_version=enrollment.version)
    second = await store.claim(enrollment.id, expected_version=enrollment.version)  # stale now

    assert first is not None and first.state == "in_progress"
    assert second is None


async def test_tick_never_redispatches_a_row_left_in_progress_by_a_crashed_run() -> None:
    enrollment = _enrollment("dental_recall")
    store = InMemoryEnrollmentStore([enrollment])
    # Simulate a prior scheduler run that claimed the row and crashed
    # before completing it — this is exactly the "kill the scheduler
    # mid-run" acceptance criterion (Epic 2.3/4.3): the row is no
    # longer "pending", so a fresh tick must leave it alone rather
    # than dispatching it a second time.
    await store.claim(enrollment.id, expected_version=enrollment.version)
    dispatcher = RecordingDispatcher()
    scheduler = FlowScheduler(store, ScriptedConsentRegistry(), dispatcher)

    await scheduler.tick(NOW)

    assert dispatcher.calls == []
