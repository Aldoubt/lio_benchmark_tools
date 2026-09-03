import numpy as np

from web_rerun_recorder import (
    send_point_series_columns,
    send_scalar_series_columns,
)


class _FakeColumnFactory:
    def __init__(self, kind, calls):
        self.kind = kind
        self.calls = calls

    def columns(self, **kwargs):
        self.calls.append((f"{self.kind}.columns", kwargs))
        return [(self.kind, kwargs)]


class FakeRerun:
    def __init__(self):
        self.calls = []
        self.Scalars = _FakeColumnFactory("Scalars", self.calls)
        self.Points3D = _FakeColumnFactory("Points3D", self.calls)

    def TimeColumn(self, name, *, duration):
        values = np.asarray(duration, dtype=np.float64)
        self.calls.append(("TimeColumn", name, values.copy()))
        return ("time", name, values)

    def send_columns(self, entity_path, *, indexes, columns):
        self.calls.append(("send_columns", entity_path, indexes, columns))

    def log(self, *args, **kwargs):
        raise AssertionError("columnar helpers must not fall back to row-oriented rr.log")


def test_scalar_series_is_sent_as_one_columnar_chunk():
    rr = FakeRerun()
    times = np.asarray([0.0, 0.1, 0.2], dtype=np.float64)
    values = np.asarray([1.0, 2.0, 3.0], dtype=np.float64)

    send_scalar_series_columns(rr, "metrics/cpu/fast_livo2", times, values)

    send_calls = [call for call in rr.calls if call[0] == "send_columns"]
    assert len(send_calls) == 1
    assert send_calls[0][1] == "metrics/cpu/fast_livo2"
    assert any(call[0] == "TimeColumn" and call[1] == "bag_time" for call in rr.calls)
    scalar_columns = [call for call in rr.calls if call[0] == "Scalars.columns"]
    assert len(scalar_columns) == 1
    assert np.array_equal(scalar_columns[0][1]["scalars"], values)


def test_current_pose_series_is_sent_as_one_columnar_chunk():
    rr = FakeRerun()
    times = np.asarray([1.0, 1.1, 1.2], dtype=np.float64)
    positions = np.asarray(
        [[0.0, 0.0, 0.0], [0.1, 0.0, 0.0], [0.2, 0.0, 0.0]],
        dtype=np.float64,
    )

    send_point_series_columns(
        rr,
        "world/algorithms/fast_livo2/current",
        times,
        positions,
        color_rgb=[230, 126, 34],
        radius=0.18,
        label="FAST-LIVO2",
    )

    send_calls = [call for call in rr.calls if call[0] == "send_columns"]
    assert len(send_calls) == 1
    assert send_calls[0][1] == "world/algorithms/fast_livo2/current"
    point_columns = [call for call in rr.calls if call[0] == "Points3D.columns"]
    assert len(point_columns) == 1
    kwargs = point_columns[0][1]
    assert np.array_equal(kwargs["positions"], positions)
    assert kwargs["colors"] == [[230, 126, 34]] * len(times)
    assert kwargs["radii"] == [0.18] * len(times)
    assert kwargs["labels"] == ["FAST-LIVO2"] * len(times)


def test_columnar_helpers_drop_non_finite_rows_consistently():
    rr = FakeRerun()
    times = np.asarray([0.0, 0.1, 0.2], dtype=np.float64)
    values = np.asarray([1.0, np.nan, 3.0], dtype=np.float64)

    send_scalar_series_columns(rr, "metrics/rss/fast_livo2", times, values)

    time_call = next(call for call in rr.calls if call[0] == "TimeColumn")
    scalar_call = next(call for call in rr.calls if call[0] == "Scalars.columns")
    assert np.array_equal(time_call[2], np.asarray([0.0, 0.2]))
    assert np.array_equal(scalar_call[1]["scalars"], np.asarray([1.0, 3.0]))
