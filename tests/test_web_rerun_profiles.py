from web_rerun_recorder import web_profile_layers


def test_web_recording_profiles_form_a_cumulative_diagnostic_ladder():
    assert web_profile_layers("empty") == frozenset()
    assert web_profile_layers("trajectory") == frozenset({"trajectory"})
    assert web_profile_layers("scalar") == frozenset({"trajectory", "scalar"})
    assert web_profile_layers("pose") == frozenset({"trajectory", "scalar", "pose"})
    assert web_profile_layers("full") == frozenset(
        {"trajectory", "scalar", "pose", "anomaly", "heavy"}
    )


def test_web_recording_profile_rejects_unknown_value():
    try:
        web_profile_layers("unknown")
    except ValueError as exc:
        assert "unknown web recording profile" in str(exc)
    else:
        raise AssertionError("unknown web recording profile must be rejected")
