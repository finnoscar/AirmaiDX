# Third-party components

AirmaiDX does not contain a game, a Windows prefix, user data, or Apple’s Game Porting Toolkit. User-supplied software and data keep their original terms.

## Included in the source and app

- **AirMai and Airmai Editor**: The chart preview adapter uses an MIT-licensed snapshot of the parser, renderer, and playback sources. The snapshot, preview resources, and license are in [`Vendor/EditorPreview`](../Vendor/EditorPreview). The touch geometry also retains the simai_flutter authors’ MIT notice.
- **AquaMai**: The configuration reference is extracted from the Apache-2.0 source at commit `c64077a2e2ecaa4f557f09fec84028a058940944`. Its license and notice are included alongside the metadata. AquaMai binaries are not provided. The [controller notice](ADX-PROTOCOL-NOTICE.md) lists the protocol references.
- **CPython and PyInstaller**: The worker uses CPython under the PSF license. PyInstaller’s bootloader is distributed under its license and application bundling exception. The Python distribution notices and the Python package notices ship under `Contents/Resources/Service/Licenses`. Build-time packages are listed in `Tools/requirements-worker.txt`.
- **vgmstream**: The chart player uses a standalone decoder built from [`6802153425adde134e49394fc653455166d7d2f2`](https://github.com/vgmstream/vgmstream/tree/6802153425adde134e49394fc653455166d7d2f2), without optional FFmpeg or other external audio decoders. `Tools/build_music_decoder.py` records the pinned source and build options. The app includes the decoder’s `COPYING` file.

## Installed separately on the user’s Mac

- **Wine and Wine Mono**: Used to run the selected Windows program. Setup downloads the Sikarugir Wine engine from its upstream release, including the engine’s accompanying Mono and Gecko files. Each component keeps its upstream license.
- **DXMT and runtime libraries**: Setup takes the required DXMT files and host libraries from pinned [Sikarugir](https://github.com/Sikarugir-App) releases. It does not install D3DMetal or use a template’s Windows prefix.
- **Microsoft Visual C++ 2012 Update 4 (x64)**: Setup downloads the installer directly from Microsoft and verifies its SHA-256 checksum before the Windows runtime uses it.

The precise upstream download locations and SHA-256 checksums are in the [runtime lock file](../Resources/Runtime/runtime-downloads.json). These downloads are not mirrored in the repository or release assets.
