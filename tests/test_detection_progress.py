from marine_track.detection_pipeline import report_progress


def test_report_progress_calls_callback():
    messages: list[str] = []

    report_progress(messages.append, "2/5 materialize")

    assert messages == ["2/5 materialize"]


def test_report_progress_accepts_none_callback():
    report_progress(None, "3/5 detect")
