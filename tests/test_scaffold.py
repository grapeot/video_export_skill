from pathlib import Path


def test_root_skill_links_exist():
    root = Path(__file__).resolve().parents[1]
    for name in ("SKILL.md", "resolve.md", "compressor.md", "pipeline.md"):
        assert (root / "skills" / "video-export" / name).is_file()
