from __future__ import annotations

from pathlib import Path

from bench.common import run_match_once
from bench.view_log import generate_viewer


def test_generate_viewer_html_from_run_log(tmp_path: Path) -> None:
    log_path = tmp_path / "run.json"
    run_match_once(seed=7, model_name="dummy_v0_1", output_path=log_path)

    output_html = tmp_path / "dashboard.html"
    generated = generate_viewer(log_path=log_path, output_path=output_html, title="Viewer Test")

    assert generated == output_html
    assert output_html.exists()

    rendered = output_html.read_text(encoding="utf-8")
    assert "TinyWorld Run Dashboard" in rendered
    assert "Viewer Test" in rendered
    assert "dummy_v0_1" in rendered
    assert "agent_position_after" in rendered
    assert "protocolPanel" in rendered
    assert "Protocol:" in rendered
