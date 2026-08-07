from forex_trader.application.runner import run_cycles


def test_runner_executes_multiple_cycles_without_sleep(engine) -> None:  # type: ignore[no-untyped-def]
    sleeps: list[float] = []
    traces = run_cycles(
        engine,
        ["EUR_USD"],
        execute=False,
        interval_seconds=0.25,
        max_cycles=2,
        sleeper=sleeps.append,
    )
    assert len(traces) == 2
    assert sleeps == [0.25]


def test_runner_validates_input(engine) -> None:  # type: ignore[no-untyped-def]
    import pytest

    with pytest.raises(ValueError):
        run_cycles(engine, [], execute=False, max_cycles=1)
    with pytest.raises(ValueError):
        run_cycles(engine, ["EUR_USD"], execute=False, interval_seconds=-1, max_cycles=1)
