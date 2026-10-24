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


@pytest.mark.parametrize("backend", ["resolve", "compressor", "pipeline"])
def test_rate_policy_dry_run_is_read_only(tmp_path, setting, capsys, monkeypatch, backend):
    monkeypatch.setattr("video_export.resolve.call", lambda *a, **k: pytest.fail("backend invoked"))
    monkeypatch.setattr("video_export.compressor.verify", lambda *a, **k: pytest.fail("source probed"))
    source = tmp_path / "input.mov"
    source.write_bytes(b"placeholder")
    state = tmp_path / "runs"
    args = [backend, {"resolve": "render", "compressor": "transcode", "pipeline": "run"}[backend],
            "--state-dir", str(state)]
    if backend != "compressor":
        args += ["--project", "Demo", "--timeline", "Main", "--preset", "ProRes", "--output",
                 str(tmp_path / "master.mov"), "--resolution", "7680x4320", "--frame-rate", "29.97",
                 "--audio-codec", "lpcm", "--audio-bit-depth", "24", "--audio-sample-rate", "48000"]
    if backend != "resolve":
        args += ["--setting", str(setting), "--max-frame-rate", "60"]
    if backend == "compressor":
        args += ["--input", str(source)]
    before = setting.read_bytes()
    assert main(args) == 0
    plan = json.loads(capsys.readouterr().out)["data"]["plan"]
    if backend != "resolve":
        assert plan["targets"][0]["max_frame_rate"] == "60.0"
    if backend != "compressor":
        assert plan["resolve"]["frame_rate"] == 29.97
        assert plan["resolve"]["audio_bit_depth"] == 24
    assert setting.read_bytes() == before and not state.exists()


@pytest.mark.parametrize("key,value", [("resolution", "1920x0"), ("resolution", "bad"),
    ("frame_rate", "nan"), ("audio_bit_depth", "zero"), ("audio_sample_rate", "-1")])
def test_invalid_render_override_rejected(key, value):
    profile = {"resolve": {"project": "Demo", "timeline": "Main", "preset": "ProRes",
                            "output": "/tmp/master.mov", key: value}}
    with pytest.raises(ExportError):
        resolve_options(Namespace(), profile)


def test_new_profile_values_and_cli_precedence(tmp_path, setting):
    file = tmp_path / "profile.toml"
    file.write_text('[resolve]\nproject="Demo"\ntimeline="Main"\npreset="ProRes"\n'
        'output="/tmp/master.mov"\nresolution="3840x2160"\nframe_rate="59.94"\n'
        'audio_codec="lpcm"\naudio_bit_depth="16"\naudio_sample_rate="44100"\n'
        '[compressor]\nmax_frame_rate=30\n[[compressor.targets]]\n'
        f'setting="{setting}"\nsuffix="-delivery"\n')
    profile = load_profile(file)
    values = resolve_options(Namespace(resolution="7680x4320", frame_rate="29.97",
        audio_codec="lpcm", audio_bit_depth="24", audio_sample_rate="48000"), profile)
    assert values["resolution"] == "7680x4320" and values["frame_rate"] == 29.97
    assert values["audio_bit_depth"] == 24 and values["audio_sample_rate"] == 48000
    from video_export.compressor import plan_targets
    assert plan_targets(tmp_path / "in.mov", profile, max_frame_rate=60)[0]["max_frame_rate"] == "60"
    assert profile["resolve"]["frame_rate"] == "59.94"


def test_invalid_profile_cap(tmp_path):
    file = tmp_path / "profile.toml"
    file.write_text('[compressor]\nmax_frame_rate="nan"')
    with pytest.raises(ExportError):
        load_profile(file)
