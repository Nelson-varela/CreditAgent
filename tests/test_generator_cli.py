import json
from pathlib import Path

from credit_agent.generator.__main__ import main
from credit_agent.generator.models import GeneratedFile


def test_cli_writes_ground_truth_and_manifest(tmp_path: Path) -> None:
    main(["--n", "20", "--seed", "3", "--out-dir", str(tmp_path)])
    files = sorted(tmp_path.glob("APP-*.json"))
    assert len(files) == 20
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["n_files"] == 20 and manifest["seed"] == 3
    assert sum(manifest["split"].values()) == 20
    parsed = GeneratedFile.model_validate_json(files[0].read_text(encoding="utf-8"))
    assert parsed.application.application_id == "APP-0001"


def test_cli_output_is_byte_identical_across_runs(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    main(["--n", "12", "--seed", "9", "--out-dir", str(a)])
    main(["--n", "12", "--seed", "9", "--out-dir", str(b)])
    assert {p.name: p.read_bytes() for p in a.iterdir()} == {
        p.name: p.read_bytes() for p in b.iterdir()
    }


def test_cli_replaces_stale_files(tmp_path: Path) -> None:
    main(["--n", "20", "--seed", "3", "--out-dir", str(tmp_path)])
    main(["--n", "10", "--seed", "3", "--out-dir", str(tmp_path)])
    assert len(list(tmp_path.glob("APP-*.json"))) == 10
