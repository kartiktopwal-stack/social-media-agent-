from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.orchestrator.celery_app import finalize_daily_run, start_daily_run


def test_finalize_daily_run_requires_and_returns_run_id() -> None:
    results = [
        {"total": 2, "completed": 2, "failed": 0},
        {"total": 3, "completed": 2, "failed": 1},
    ]

    summary = finalize_daily_run(results, "run-123")

    assert summary["run_id"] == "run-123"
    assert summary["total"] == 5
    assert summary["completed"] == 4
    assert summary["failed"] == 1


@patch("src.orchestrator.celery_app.load_niches", return_value={"tech": object(), "finance": object()})
@patch("src.orchestrator.celery_app.chord")
@patch("src.orchestrator.celery_app.group")
def test_start_daily_run_binds_run_id_to_chord_callback(
    mock_group: MagicMock,
    mock_chord: MagicMock,
    _mock_load_niches: MagicMock,
) -> None:
    mock_chord_runner = MagicMock()
    mock_chord.return_value = mock_chord_runner

    run_id = start_daily_run(niche_names=["tech"], dry_run=True)

    assert run_id.startswith("run-")

    callback_sig = mock_chord_runner.call_args.args[0]
    assert callback_sig.task == "orchestrator.finalize_daily_run"
    assert callback_sig.args == (run_id,)
