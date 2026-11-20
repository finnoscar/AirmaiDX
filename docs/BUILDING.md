# Build and test

The source tree is self-contained for Swift and Python tests. It does not require another Airmai repository. A full macOS app build also needs a Windows cross compiler, .NET SDK, CMake, and a local installation to supply references for the managed compatibility bridges.

## Development setup

Use an Apple silicon Mac and Xcode 27.1 or a compatible later SDK. The macOS deployment target is 15.0. For the frozen worker, use an arm64 CPython 3.12 interpreter with a deployment target of macOS 15 or earlier. The release uses [CPython 3.12.16 from Python Build Standalone](https://github.com/astral-sh/python-build-standalone/releases/tag/20261110). Install the listed Python packages in a virtual environment:

```sh
python3.12 -m venv Tools/.venv-portable
Tools/.venv-portable/bin/python -m pip install -r Tools/requirements-worker.txt
swift test
Tools/.venv-portable/bin/python -m unittest discover -s Tests -p 'test_*.py'
```

Native tests that call an external compiler or a platform tool require that tool to be available. The preview adapter snapshot and both Xcode schemes are checked in. After changing the input list or native project layout, run `python3 Tools/generate_xcode_project.py` to regenerate the Xcode project. The iOS target needs your own signing team to run on an iPhone. It does not require Mac runtime components.

## Build the macOS app

Use LLVM-MinGW with the x86_64 Windows target, a .NET SDK with Roslyn, and CMake. Set `--game-references` to the `Package` directory of an installation you own. The build reads `Sinmai_Data/Managed/*.dll`, `MelonLoader/net35/MelonLoader.dll`, and `MelonLoader/net35/0Harmony.dll` as compiler references. It does not copy those files into the app or modify them.

```sh
Tools/.venv-portable/bin/python Tools/build_app.py \
  --game-references '/path/to/your/Package' \
  --mingw '/path/to/x86_64-w64-mingw32-gcc' \
  --dotnet '/path/to/dotnet'
Tools/.venv-portable/bin/python Tools/package_dmg.py --skip-build
```

The build produces `build/AirmaiDX.app`. With those resources present, open `AirmaiDX.xcodeproj` and choose the **AirmaiDX macOS** scheme to develop in Xcode. The disk image script verifies the app, creates the image in `dist`, mounts it read-only to check the contents, and writes a SHA-256 checksum. It does not notarize the result.

The app ships its worker, AirmaiDX’s helpers, and the chart audio decoder. It downloads the separate Windows runtime only when the user chooses **Download and Install** during setup. `Resources/Runtime/runtime-downloads.json` identifies the upstream downloads, versions, sizes, and hashes. Do not place local game files, runtime archives, credentials, or signing material in the source tree.
