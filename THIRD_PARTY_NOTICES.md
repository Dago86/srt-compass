# Third-party notices

The source repository does not include third-party executables. The macOS build
script downloads the official yt-dlp 2026.08.19 executable and Deno 2.9.7 for
Apple Silicon, verifies their pinned checksums, and bundles them in the local
application. Their upstream license texts are included in the application
resources under `licenses/` and in this source tree under `vendor/licenses/`.

- yt-dlp is released under the Unlicense; its official PyInstaller executable
  includes GPL-3.0-or-later components. The corresponding license text is
  included as `GPL-3.0.txt` and `yt-dlp-LICENSE`.
- Deno is distributed under the MIT License; its notice is included as
  `deno-LICENSE.md`.
- The yt-dlp executable includes the EJS scripts required for full YouTube
  support. The bundled Deno runtime is selected explicitly; the application
  does not download code components while running.

Upstream sources and pinned binary checksums are recorded in
`vendor/versions.txt`.
