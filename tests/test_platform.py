from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_sottotitoli import platform


class PlatformIntegrationTests(unittest.TestCase):
    def test_linux_data_and_config_dirs_follow_xdg(self) -> None:
        with patch.dict(
            os.environ,
            {
                "XDG_DATA_HOME": "/tmp/test-data",
                "XDG_CONFIG_HOME": "/tmp/test-config",
                "XDG_STATE_HOME": "/tmp/test-state",
            },
        ), patch.object(platform, "sys") as system:
            system.platform = "linux"
            self.assertEqual(platform.data_dir(), Path("/tmp/test-data/SRT Compass"))
            self.assertEqual(platform.config_dir(), Path("/tmp/test-config/SRT Compass"))
            self.assertEqual(platform.state_dir(), Path("/tmp/test-state/srt-compass"))

    def test_macos_paths_keep_legacy_storage(self) -> None:
        with patch.object(platform, "sys") as system:
            system.platform = "darwin"
            self.assertEqual(
                platform.data_dir(),
                Path.home() / "Library" / "Application Support" / "VideoSottotitoli",
            )

    def test_linux_open_path_uses_xdg_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "captions.srt"
            target.write_text("1", encoding="utf-8")
            with (
                patch.object(platform, "sys") as system,
                patch("video_sottotitoli.platform.shutil.which", return_value="/usr/bin/xdg-open"),
                patch("video_sottotitoli.platform.subprocess.Popen") as popen,
            ):
                system.platform = "linux"
                platform.open_path(target)
            popen.assert_called_once()
            self.assertEqual(popen.call_args.args[0], ["/usr/bin/xdg-open", str(target)])


if __name__ == "__main__":
    unittest.main()
