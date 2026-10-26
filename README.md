# PoseSnap

Local pose extraction, pose editing, expression extraction and Kimodo Text to Pose for Genesis figures in DAZ Studio.

**[Download PoseSnap for Windows x64](https://github.com/AithaEzio/PoseSnap/releases/download/v1.0.1-rc3/PoseSnap-1.0.1-public-rc3-Windows-x64.zip)** · [Release notes and checksums](https://github.com/AithaEzio/PoseSnap/releases/tag/v1.0.1-rc3)

## Start here

1. Download the named **Windows-x64.zip** above. GitHub's automatic **Source code** archives are not the Windows app.
2. Extract it into a **new folder** and run **PoseSnap.exe**. Keep the entire folder together. Private WebView2 is included.
3. Open **Settings → Engine**, choose **All modes** or **Pose + Expression**, and click **Set up PoseSnap**.
4. Leave PoseSnap open while it downloads, verifies and installs the selected components. Then open a reference image or visit Text to Pose.

Ordinary setup needs no GitHub account, system Python, terminal commands, manual joining of archive parts or separate model imports. Engine files download once and run locally afterward. PoseSnap checks each download and installed file against its pinned SHA-256 hash. Pause/retry retains resumable parts.

The old 1.0.0 core cannot install the new multipart packs. Use this 1.0.1 RC3 download if an older copy says a compatible runtime is not hosted.

## Choose your setup

| Setup | Additional engine download | Total installed, including core |
|---|---:|---:|
| Portable core only | None; Windows ZIP is approximately 306 MiB | Approximately 687 MiB |
| Pose + Expression | Approximately 7.49 GB | Approximately 13.5 GB |
| All modes, including Kimodo | Approximately 16.77 GB | Approximately 22.8 GB |

Keep extra free disk space for checked downloads, extraction and safe replacement. Setup displays the current component sizes and checks temporary disk headroom. All modes includes the components required by the four creation/editing modes, rather than every optional diagnostic or fallback.

**Requirements:** Windows x64 and a compatible NVIDIA graphics driver for pose extraction and Kimodo body generation. Pose extraction requires at least 8 GB VRAM. The interface opens without system Python or a system WebView2 installation; private components stay inside the portable folder.

**CLUE is optional and off by default.** This source-uncertainty diagnostic is not needed by either setup profile. It still requires separately authorised upstream files. A missing CLUE component does not block ordinary extraction or generation.

## Work locally

- **Extract pose:** choose a person and extract using Pure, Genesis Smart Fit or Auto.
- **Pose studio:** refine body joints, placement and hand poses, using the existing editable workflows.
- **Expression studio:** extract and refine facial expressions from a photograph.
- **Text to Pose:** describe a body pose for Kimodo, preview choices and refine the accepted result in Pose Studio. Approximate hand shapes is optional and initially off. Text to Pose does not generate facial expressions.

Floor and partner-contact workflows remain experimental. Preview meshes provide a quick judgement of movement; inspect the final appearance on your Genesis figure in DAZ Studio. Engine-ready badges indicate runtime health, separately from a workflow's quality qualification.

## Your files and recovery

Settings, history and connected rig metadata stay in the app's local **data** folder. Keep a backup before replacing an installation. Preserve your old working folder, extract new versions separately, and migrate only your own data after backing it up. Do not merge application versions or copy someone else's data.

If a transfer fails, retry setup or use the existing offline import controls. If the core archive is damaged, extract the Windows ZIP into another new folder. Browser repair is available through **PoseSnap.exe --engine-setup**.

The published app and engine assets exclude personal settings, photos, history, connected rigs, credentials and development/training data. This repository currently hosts official downloads and setup documentation.

## Verification and current limits

This is an **unsigned release candidate**. The release records frontend, worker and native test results, a relocated native installation smoke test, private-runtime dependency imports, published asset hashes and download availability. Large existing model files were reused in the installation test; it is not a claim that every model was downloaded from scratch. Live DAZ checks and other hardware/Windows configurations remain unverified.

The Windows ZIP SHA-256 is:

```text
62f58000b4aaee402b63faf8c2a84621871a76fa504e392a22f3c290594bca9f
```

The release also provides its checksum file and complete portable-core manifest.

## Licences and credits

Component licences and artist credits accompany the app in **THIRD_PARTY_NOTICES.md**, **licenses** and **About**. Model and runtime downloads retain their provider terms. **Built with Meta Llama 3.**

[Component licence bundle](https://github.com/AithaEzio/PoseSnap/releases/download/engines-20261026-v1/PoseSnap-Component-Licences-20261026.zip) · [Base engine assets](https://github.com/AithaEzio/PoseSnap/releases/tag/engines-20261026-v1) · [Runtime supplement](https://github.com/AithaEzio/PoseSnap/releases/tag/engines-20261027-v2)

## Support the creator

Enjoying PoseSnap? [Support Aitha on Ko-fi](https://ko-fi.com/aithaezio) or [explore Aitha's GitHub projects](https://github.com/AithaEzio?tab=repositories).
