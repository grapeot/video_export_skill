from types import SimpleNamespace

import pytest

from video_export.common import ExportError
from video_export.resolve_worker import choose_project, operate


def test_foreign_project_is_never_closed():
    manager = SimpleNamespace(GetCurrentProject=lambda: SimpleNamespace(GetName=lambda: "Other"),
                              LoadProject=lambda name: pytest.fail("switched project"))
    with pytest.raises(ExportError) as error:
        choose_project(manager, "Demo")
    assert error.value.code == "foreign_project_loaded"


@pytest.mark.parametrize("owned,current", [(False, "Untitled Project"), (True, "Other")])
def test_allowed_project_load(owned, current):
    manager = SimpleNamespace(GetCurrentProject=lambda: SimpleNamespace(GetName=lambda: current),
                              LoadProject=lambda name: "loaded")
    assert choose_project(manager, "Demo", owned) == "loaded"


def fake_project(output, terminal="Complete"):
    calls = []
    timeline = SimpleNamespace(GetName=lambda: "Main", GetStartFrame=lambda: 86400,
                               GetEndFrame=lambda: 86448,
                               GetSetting=lambda key: {"timelineFrameRate": "24",
                                    "timelineResolutionWidth": "1280",
                                    "timelineResolutionHeight": "720"}[key])
    project = SimpleNamespace(
        GetName=lambda: "Demo", IsRenderingInProgress=lambda: False, GetTimelineCount=lambda: 1,
        GetTimelineByIndex=lambda index: timeline, GetRenderPresetList=lambda: ["ProRes"],
        SetCurrentTimeline=lambda t: True, LoadRenderPreset=lambda p: True,
        SetCurrentRenderMode=lambda mode: True,
        GetCurrentRenderFormatAndCodec=lambda: {"format": "mov", "codec": "ProRes422HQ"},
        SetRenderSettings=lambda settings: calls.append(settings) or True,
        AddRenderJob=lambda: "ours", StartRendering=lambda jobs: calls.append(jobs) or True,
        GetRenderJobStatus=lambda job: {"JobStatus": terminal, "CompletionPercentage": 100},
        GetRenderJobList=lambda: [{"JobId": "ours", "OutputFilename": output.name}])
    manager = SimpleNamespace(GetCurrentProject=lambda: project)
    return SimpleNamespace(GetProjectManager=lambda: manager), calls


@pytest.mark.parametrize("timeout", [1, 5, 10, 60])
def test_render_only_starts_own_job_and_uses_full_timeline(tmp_path, timeout):
    output = tmp_path / "master.mov"
    resolve, calls = fake_project(output)
    result = operate(resolve, {"action": "render", "options": {"project": "Demo", "timeline": "Main",
                   "preset": "ProRes", "output": str(output)}, "timeout": timeout})
    assert result["timeline"]["duration"] == 2
    assert calls[-1] == ["ours"] and calls[0]["SelectAllFrames"] is True


def test_failed_render_is_not_success(tmp_path):
    output = tmp_path / "master.mov"
    resolve, _ = fake_project(output, "Failed")
    with pytest.raises(ExportError) as error:
        operate(resolve, {"action": "render", "options": {"project": "Demo", "timeline": "Main",
                  "preset": "ProRes", "output": str(output)}, "timeout": 60})
    assert error.value.code == "render_job_failed"


def test_late_headless_readiness_never_submits_job(tmp_path, monkeypatch):
    import sys
    from video_export import resolve_worker as worker
    clock, calls = [0], []
    project = SimpleNamespace(IsRenderingInProgress=lambda: False)
    resolve = SimpleNamespace(GetProjectManager=lambda: SimpleNamespace(GetCurrentProject=lambda: project),
                              Quit=lambda: calls.append("quit"))
    api = SimpleNamespace(scriptapp=lambda _: resolve if clock[0] >= 1 else None)
    monkeypatch.setitem(sys.modules, "DaVinciResolveScript", api)
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(worker.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *a, **k: SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(worker, "operate", lambda *a: pytest.fail("submitted after deadline"))
    with pytest.raises(ExportError) as error:
        worker.dispatch({"action": "render", "timeout": 1, "headless": True,
                         "checkpoint": str(tmp_path / "checkpoint.json")})
    assert error.value.code == "resolve_render_timeout" and calls == ["quit"]
    assert clock[0] == 1
