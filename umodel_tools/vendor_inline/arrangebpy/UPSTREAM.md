# arrangebpy source provenance

This directory vendors the reusable layout core from
[`BradyAJohnston/arrangebpy`](https://github.com/BradyAJohnston/arrangebpy),
which is derived from the Node Arrange Blender add-on.

- Version: `0.1.0`
- Upstream commit: `9facd9704040065ecf349c8c83a1b29653b3ee5c`
- Upstream commit date: 2026-01-15
- License: GPL-3.0; individual source files identify GPL-2.0-or-later

Local compatibility changes are intentionally narrow:

- estimate node dimensions when Blender background mode reports `(0, 0)`;
- fall back safely when socket runtime coordinates are unavailable.

UModel Tools calls only the Sugiyama layout with reroute insertion and collapsed
node stacking disabled.
