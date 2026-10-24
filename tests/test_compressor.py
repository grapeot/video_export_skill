import json

import pytest

from video_export import compressor
from video_export.common import ExportError, noisy_json
from video_export.state import RunState


def test_preset_reports_actual_bounds(setting):
    result = compressor.preset(setting)
    assert result["resolution_mode"] == "follow_source"
    assert result["codec"] == "hvc1" and result["extension"] == "mov"


def test_fixed_bounds_and_invalid_xml(setting):
    setting.write_text(setting.read_text().replace('width="-100" height="-100"',
                                                 'width="1920" height="1080"'))
    assert compressor.preset(setting)["width"] == "1920"
    setting.write_text("not XML")
    with pytest.raises(ExportError):
        compressor.preset(setting)


def test_noisy_json():
    assert noisy_json('diagnostic [invalid]\n{"batch":{"batchID":"b"}}\nend')["batch"]["batchID"] == "b"


def test_exact_submission_and_monitor_order(tmp_path, monkeypatch):
    source = tmp_path / "input with space.mov"
    command = compressor.submit_command(source, [{"setting": "/path/p.compressorsetting",
                                                  "output": "/path/out.mov"}])
    assert source.as_uri() in command
    assert command[-2:] == ["-outputformat", "json"]
    commands = []
    monkeypatch.setattr(compressor, "run", lambda cmd, **kw: commands.append(cmd) or '{}')
    compressor.status("batch")
    assert commands[0][1:] == ["-monitor", "-format", "json", "-batchid", "batch", "-once"]


def test_status_never_accepts_success_of_other_batch_or_child():
    payload = {"batches": [{"batchid": "other", "status": "Successful"},
                           {"batchid": "ours", "status": "Waiting", "jobs": [{"status": "Successful"}]}]}
    assert compressor.batch_status(payload, "ours") == "Waiting"
    assert compressor.batch_status({"jobs": [{"status": "Successful"}]}, "ours") is None


@pytest.mark.parametrize("terminal", ["Successful", "Failed", "Cancelled"])
def test_queue_waits_and_checks_all_targets(tmp_path, monkeypatch, terminal):
    calls = []
    monkeypatch.setattr(compressor, "verify", lambda file, *a, **k:
                        calls.append(str(file)) or {"duration": 2})
    monkeypatch.setattr(compressor, "run", lambda cmd: json.dumps(
        {"batch": {"batchID": "ours", "jobs": [{"jobID": "shared"}]}}))
    states = iter(["Waiting", "Processing", terminal])
    monkeypatch.setattr(compressor, "status", lambda batch, **kw: {"batchid": batch, "status": next(states)})
    monkeypatch.setattr(compressor.time, "sleep", lambda _: None)
    targets = [{"output": str(tmp_path / f"out{i}.mov"), "setting": "/path/to/preset"} for i in range(2)]
    state = RunState(tmp_path / "runs")
    if terminal == "Successful":
        result = compressor.transcode(tmp_path / "in.mov", targets, state)
        assert len(result["outputs"]) == 2 and len(calls) == 3
    else:
        with pytest.raises(ExportError) as error:
            compressor.transcode(tmp_path / "in.mov", targets, state)
        assert error.value.code == "compressor_batch_failed" and len(calls) == 1


def test_source_verification_failure_blocks_submission(tmp_path, monkeypatch):
    def invalid(*args, **kwargs):
        raise ExportError("source_unstable", "writer")
    monkeypatch.setattr(compressor, "verify", invalid)
    monkeypatch.setattr(compressor, "run", lambda *a: pytest.fail("submitted"))
    with pytest.raises(ExportError):
        compressor.transcode(tmp_path / "in.mov", [], RunState(tmp_path / "state"))


def test_duration_expectation_cannot_allow_truncation(tmp_path, monkeypatch):
    from video_export import verification
    monkeypatch.setattr(verification, "stable_file", lambda *a: None)
    monkeypatch.setattr(verification, "inspect_media", lambda *a: {"duration": 120, "video": {}})
    monkeypatch.setattr(compressor, "verify", verification.verify)
    monkeypatch.setattr(compressor, "run", lambda *a, **k: pytest.fail("submitted wrong duration"))
    with pytest.raises(ExportError, match="duration"):
        compressor.transcode(tmp_path / "source.mov", [], RunState(tmp_path / "runs"),
                              expected={"duration": 2})


@pytest.mark.parametrize("wrong", ["codec", "dimensions", None])
def test_distinct_target_expectations_verified(tmp_path, monkeypatch, wrong):
    from video_export import verification
    monkeypatch.setattr(verification, "stable_file", lambda *a: None)
    def media(file):
        video = {"codec_name": "hevc", "width": 1920 if "one" in str(file) else 1280, "height": 720}
        if "source" in str(file):
            video = {"codec_name": "prores", "width": 1920, "height": 720}
        elif wrong == "codec":
            video["codec_name"] = "h264"
        elif wrong == "dimensions":
            video["width"] = 640
        return {"duration": 2, "video": video}
    monkeypatch.setattr(verification, "inspect_media", media)
    monkeypatch.setattr(compressor, "verify", verification.verify)
    monkeypatch.setattr(compressor, "run", lambda *a, **kw: '{"batch":{"batchID":"b"}}')
    monkeypatch.setattr(compressor, "status", lambda *a, **kw: {"batchid": "b", "status": "Successful"})
    targets = [{"output": str(tmp_path / f"{name}.mov"), "setting": "/path/preset",
                "preset": {"codec": "hvc1", "width": str(width), "height": "720"}}
               for name, width in (("one", 1920), ("two", 1280))]
    if wrong:
        with pytest.raises(ExportError) as error:
            compressor.transcode(tmp_path / "source.mov", targets, RunState(tmp_path / "runs"))
        assert error.value.code == "media_mismatch"
    else:
        assert len(compressor.transcode(tmp_path / "source.mov", targets,
                                       RunState(tmp_path / "runs"))["outputs"]) == 2


def test_monitor_deadline_and_remaining_budget(tmp_path, monkeypatch):
    clock, budgets = [0], []
    monkeypatch.setattr(compressor.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(compressor, "verify", lambda *a, **k: {"duration": 2})
    monkeypatch.setattr(compressor, "run", lambda *a, **kw: '{"batch":{"batchID":"b"}}')
    def late_status(batch, timeout):
        budgets.append(timeout)
        clock[0] += 2
        return {"batchid": batch, "status": "Successful"}
    monkeypatch.setattr(compressor, "status", late_status)
    with pytest.raises(ExportError) as error:
        compressor.transcode(tmp_path / "source.mov", [], RunState(tmp_path / "runs"), timeout=1)
    assert error.value.code == "compressor_timeout" and budgets == [1]
