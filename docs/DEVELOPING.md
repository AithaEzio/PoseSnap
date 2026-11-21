# Build PoseSnap v1.1.1

This checkout contains the Windows x64 app source and distributable preview assets. The [PoseSnap licence](../LICENSE) applies to original code. The [third-party notices](../THIRD_PARTY_NOTICES.md) describe separate terms.

Install Node.js 22.12 or newer, the Rust Windows MSVC toolchain and Visual C++ Build Tools with the Windows SDK. In a configured Developer PowerShell, run:

    npm ci
    npm run check
    npm run build
    npm run tauri -- build --no-bundle

This compiles the app from the checked-in source and locked build dependencies. The executable needs the pinned portable files to run. In debug builds, POSESNAP_DEV_ROOT can point to an isolated development installation. See the [portable guide](PORTABLE.md) for engine setup. Python and model weights are separate from the core.

## Portable packaging

Use Python 3.11 or newer for the packaging scripts. Supply the pinned runtime/webview2 files from an independently verified official installation. Their sizes and hashes are in the checked-in catalogue. A matching v1.0.1 official Windows ZIP supplies the previously distributed compatibility data at its pinned hash:

    python scripts/prepare-source-rig.py path-to-verified-v1.0.1.zip

This file is a local packaging input, outside the Git tree and the source licence. The package build receipt records its hash. Never put personal connected-figure data into the source tree.

Record the source identity with python scripts/package.py --source-signature before building. Build in that same tree with compiler path remapping for the checkout and Cargo dependency sources. Record the binary with python scripts/package.py --record-build --expect-source followed by the saved signature. Then run python scripts/package.py --final --zip.

The suites exercise frontend state, native components and the private Python worker. Some tests need separately installed runtime files and reviewed fixtures. The checked-in test code and the clean portable startup are separate from fresh GPU inference and live DAZ checks.
