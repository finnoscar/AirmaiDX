# Architecture

AirmaiDX has three layers: the macOS interface, a local worker, and the runtime that runs the selected Windows program. The interface never needs to execute a game binary to inspect an installation.

| Path | Responsibility |
| --- | --- |
| `Sources/AirmaiDX` | SwiftUI launcher, library, setup, controls, display settings, reader pairing, and diagnostics. |
| `Sources/AirmaiCore` | Configuration and chart models, localized resources, and worker process management. |
| `Sources/AirmaiEditorPreview` | Chart conversion and playback adapter. The preview engine is built from a limited snapshot in `Vendor/EditorPreview`. |
| `Service` | Python worker: library transactions, compatibility checks, launch planning, controller bridges, runtime setup, and reader service. |
| `Native` | macOS device helpers and Windows bridge source for input, display, and the reader. |
| `Sources/AirmaiDXMobile`, `AirmaiMobileCore`, and `AirmaiTouchKit` | iOS companion target and shared touch and pairing code included in this workspace. |
| `Tools`, `Resources`, and `Tests` | Packaging and project generation, icons and runtime manifests, and tests. |

## Launch flow

1. The app sends the worker an operation and a JSON request. The worker streams progress and returns a result or a structured setup requirement.
2. Import records the selected folder. It does not make a second copy of the game. The source volume must remain available. The game itself can write to its folder, and AirmaiDX backs up managed configuration before making changes.
3. The worker checks the package, local prerequisites, and required configuration. If runtime setup is needed, the app asks before fetching locked upstream files. The worker checks both file size and SHA-256 before assembly and installs the runtime into the user’s Application Support directory.
4. The worker starts the game through Wine in a per-installation prefix. DXMT provides the Direct3D 11 to Metal path. A session owns the processes, temporary files, controller routing, and display settings it starts.
5. On exit the worker stops session helpers and restores temporary configuration. Recovery information and logs stay local.

## Data and devices

`~/Library/Application Support/AirmaiDX` stores library references, runtime versions, prefixes, settings, backups, and logs. Do not publish an Application Support directory or a raw game log: either can contain user or machine information. The app does not automatically upload diagnostics.

Supported controllers use platform device interfaces where available. A connected controller can supply buttons and touch independently; the mouse input path is separate. See the [ADX protocol notes](ADX-PROTOCOL-NOTICE.md) for the tested boundaries of that integration.

The reader discovers the Mac on the local network. A short-lived pairing code authorizes a device, and subsequent card events use its pairing credential. The local bridge delivers each accepted event into the active game session. Card values, pairing state, and identifiers are intentionally absent from the repository and installer.
