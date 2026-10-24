import json
from argparse import Namespace
from pathlib import Path

import pytest

from video_export.cli import main
from video_export.common import ExportError, outputs_available
from video_export.config import load_profile, resolve_options


@pytest.mark.parametrize("content", [
    "[unknown]\nx=1", '[resolve]\npresett="x"', '[outputs]\nkeep_master=false',
    '[resolve]\npreset=42', '[compressor]\ntargets="invalid"',
    '[[compressor.targets]]\nsetting="x"\nsuffix="../escape"',
    '[[compressor.targets]]\nsetting="x"\noutput=3',
])
def test_reject_invalid_profile(tmp_path, content):
    file = tmp_path / "profile.toml"
    file.write_text(content)
    with pytest.raises(ExportError, match="."):
        load_profile(file)


def test_explicit_arguments_override_profile():
    profile = {"resolve": {"project": "Demo", "timeline": "Main", "preset": "A", "output": "/tmp/a.mov"}}
    values = resolve_options(Namespace(preset="B", output="/tmp/b.mov"), profile)
    assert values["preset"] == "B" and values["output"] == str(Path("/tmp/b.mov").resolve())
    assert profile["resolve"]["preset"] == "A"


def test_duplicate_paths_and_existing_input_refused(tmp_path):
    item = tmp_path / "a.mov"
    for outputs, inputs in (([item, item], []), ([item], [item])):
        with pytest.raises(ExportError) as error:
            outputs_available(outputs, inputs)
        assert error.value.code == "output_collision"
    item.write_bytes(b"source")
    with pytest.raises(ExportError):
        outputs_available([item])


def test_dry_run_has_no_run_state_or_backend_activity(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("video_export.resolve.call", lambda *a, **k: pytest.fail("backend invoked"))
    state = tmp_path / "state"
    args = ["resolve", "render", "--project", "Demo", "--timeline", "Main", "--preset", "ProRes",
            "--output", str(tmp_path / "out.mov"), "--state-dir", str(state)]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["data"]["dry_run"] is True
    assert not state.exists()


@pytest.mark.parametrize("argv", [[], ["bogus"], ["compressor", "status"],
                                   ["resolve", "render", "--timeout", "nan"],
                                   ["resolve", "render", "--timeout", "-1"]])
def test_invalid_arguments_are_single_json(argv, capsys):
    assert main(argv) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "invalid_arguments"


def test_target_extension_from_setting_not_source(tmp_path, setting, capsys):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"placeholder")
    assert main(["compressor", "transcode", "--input", str(source), "--setting", str(setting)]) == 0
    result = json.loads(capsys.readouterr().out)["data"]["plan"]
    assert result["targets"][0]["output"].endswith("input-1.mov")
