"""Reject output paths that would copy the new bundle back into its inputs."""
import pytest

import build_windows_portable as portable


@pytest.mark.parametrize("inside", ["web/dist/release", "runtime/release"])
def test_bundle_rejects_recursive_output(tmp_path, monkeypatch, inside):
    monkeypatch.setattr(portable, "ROOT", tmp_path)
    destination = tmp_path / inside
    with pytest.raises(ValueError, match="outside"):
        portable.bundle(tmp_path / "runtime", destination)
    assert not destination.exists()
