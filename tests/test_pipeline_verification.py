import json
import subprocess
from types import SimpleNamespace

import pytest

from video_export import pipeline, verification
from video_export.common import ExportError
from video_export.state import RunState, fingerprint, identity, reuse_master


def test_render_failure_blocks_compressor(tmp_path, monkeypatch):
    def failed(*a, **kw):
        raise ExportError("render_job_failed", "test")
    monkeypatch.setattr(pipeline, "render_master", failed)
    monkeypatch.setattr(pipeline.compressor, "transcode", lambda *a, **k: pytest.fail("downstream"))
    with pytest.raises(ExportError):
        pipeline.execute({"output": str(tmp_path / "master.mov")}, [], RunState(tmp_path / "state"))


def test_master_verification_failure_blocks_compressor(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline.resolve, "call", lambda *a, **kw: {"timeline": {"duration": 2}})
    def invalid(*a, **kw):
        raise ExportError("media_invalid", "test")
    monkeypatch.setattr(pipeline, "verify", invalid)
    monkeypatch.setattr(pipeline.compressor, "transcode", lambda *a, **k: pytest.fail("downstream"))
    with pytest.raises(ExportError):
        pipeline.execute({"output": str(tmp_path / "master.mov")}, [], RunState(tmp_path / "state"))


def test_reuse_requires_matching_file_and_configuration(tmp_path):
    file = tmp_path / "master.mov"
    file.write_bytes(b"synthetic")
    config = {"output": str(file), "project": "Demo", "timeline": "Main", "preset": "ProRes"}
    state = RunState(tmp_path / "runs")
    state.save(master={"identity": identity(config), "fingerprint": fingerprint(file), "verified": True})
    assert reuse_master(state.filename, config)["verified"]
    for altered in ({**config, "timeline": "Other"}, config):
        if altered == config:
            file.write_bytes(b"changed")
        with pytest.raises(ExportError):
            reuse_master(state.filename, altered)


def test_writer_refused(tmp_path, monkeypatch):
    file = tmp_path / "source.mov"
    file.write_bytes(b"synthetic")
    monkeypatch.setattr(verification.shutil, "which", lambda _: "lsof")
    monkeypatch.setattr(verification.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout="p1\nf4\naw\n", stderr=""))
    with pytest.raises(ExportError) as error:
        verification.stable_file(file, 0)
    assert error.value.code == "source_unstable"


def test_changing_source_refused(tmp_path, monkeypatch):
    file = tmp_path / "source.mov"
    file.write_bytes(b"synthetic")
    monkeypatch.setattr(verification.shutil, "which", lambda _: "lsof")
    monkeypatch.setattr(verification.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=1, stdout="", stderr=""))
    monkeypatch.setattr(verification.time, "sleep", lambda _: file.write_bytes(b"changed"))
    with pytest.raises(ExportError) as error:
        verification.stable_file(file, 0)
    assert error.value.code == "source_unstable"


@pytest.mark.parametrize("duration", ["NaN", "inf", "0", "-1"])
def test_invalid_duration(duration, monkeypatch):
    monkeypatch.setattr(verification, "run", lambda *a: json.dumps(
        {"format": {"duration": duration}, "streams": [{"codec_type": "video"}]}))
    with pytest.raises(ExportError):
        verification.inspect_media("/path/to/video.mov")


def test_metadata_mismatch_and_decode_are_enforced(monkeypatch):
    monkeypatch.setattr(verification, "stable_file", lambda *a: None)
    monkeypatch.setattr(verification, "inspect_media", lambda *a:
                        {"duration": 2, "video": {"codec_name": "prores", "width": 1280}})
    with pytest.raises(ExportError):
        verification.verify("/path/video.mov", {"width": 1920})
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw:
                        calls.append(cmd) or SimpleNamespace(returncode=0, stderr=""))
    verification.verify("/path/video.mov", {"duration": 2}, decode=True)
    assert "-xerror" in calls[0]


@pytest.mark.parametrize("stage", ["writer", "decode"])
def test_subprocess_timeouts_return_json_through_cli(tmp_path, monkeypatch, capsys, stage):
    from video_export import cli
    file = tmp_path / "source.mov"
    file.write_bytes(b"synthetic")
    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("test", 1)
    monkeypatch.setattr(verification.subprocess, "run", timeout)
    monkeypatch.setattr(verification.shutil, "which", lambda _: "lsof")
    if stage == "decode":
        monkeypatch.setattr(verification, "stable_file", lambda *a: None)
        monkeypatch.setattr(verification, "inspect_media", lambda *a: {"duration": 2, "video": {}})
    def execute(args):
        verification.verify(file, decode=stage == "decode")
    monkeypatch.setattr(cli, "execute", execute)
    assert cli.main(["compressor", "doctor"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == (
        "writer_check_timeout" if stage == "writer" else "decode_timeout")
