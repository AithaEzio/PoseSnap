# PoseSnap v1.1.1 for Windows

Extract one photo or depth reference at a time. Use a new folder and keep your previous working installation for rollback.

Open **PoseSnap.exe**. Private WebView2 is included; no system browser or Python installation is required to open the workspace. Keep the whole folder together when moving it.

This core contains the interface, preview assets, worker source, licences and pinned component manifests. Heavy engines and model weights are optional and are not included. Extraction and generation require their matching components.

## Add engines

Open **Settings → Engine**, choose **All modes** or **Pose + Expression**, then select **Set up PoseSnap**. The app downloads, checks and installs every component for that selection. The tested Python/CUDA, Kimodo, person-detector and licensed SAM body packs are served from [PoseSnap releases](https://github.com/AithaEzio/PoseSnap/releases); other models use their pinned upstream sources. No paid server, system Python, terminal commands or manual joining of download parts is needed. CLUE remains optional, off by default, and requires separate authorised upstream access.

Keep the app open during setup. Pause preserves resumable bytes. Retry continues from checked parts; existing working files are replaced only after validation. The interface reports required download/installed sizes and checks temporary disk headroom. All modes currently use about 22.8 GB installed; Pose + Expression uses about 13.5 GB. Setup can temporarily need more space while checking and replacing files. Offline Import folder/file remains available for recovery.

Install only the components you need. Kimodo creates body poses; facial extraction uses Expression studio. Approximate hand shapes is optional and off initially. Floor and partner-contact workflows remain experimental. Preview surfaces are simplified; inspect the result on your Genesis figure in DAZ Studio.

## Your files and recovery

PoseSnap creates **data**, **temp** and **logs** locally on first use. Your settings, history and connected rig metadata stay in data. Back up data before replacing an app folder. Do not copy someone else's data into your installation. Originals, character scale, identity and unrelated DAZ controls are preserved by the application workflow.

If startup fails, run **PoseSnap.exe --engine-setup** to verify or import Private WebView2 before opening the workspace. Re-extract corrupted archives into a new folder. Avoid merging versions. Keep the previous working folder as a rollback set until your own workflows are verified.

This is an unsigned v1.1.1 build. Live DAZ testing is outside this release verification. See manifest.json and manifests/build-receipt.json for exact file, component and source identities. Optional engine quality and hardware limits remain separate from runtime-ready badges. Component licences, including SAM, DINOv3 and MHR, remain applicable to their downloads and use.

## Extract pose

Choose Photo or Depth in Add as, then open a reference. Auto uses Pure for one person and Genesis Smart Fit for interactions by default. Select the people from the same image and inspect the resulting pose. Saved single-reference results stay editable in Pose Studio.

Install optional Image maps in Settings → Engine to inspect prepared depth, normals and albedo independently of extraction. The optional download is about 66 MB. ShadeNet estimates relative depth. Metric depth input needs original units and the matching calibrated camera. Automatic guidance can retain the baseline pose when it lacks usable evidence.

## Creator and credits

Want to support the creator? [Ko-fi](https://ko-fi.com/aithaezio) · [GitHub](https://github.com/AithaEzio?tab=repositories)

Artist attribution and engine licences are in THIRD_PARTY_NOTICES.md, licenses and About. Original source meshes and personal photos are not part of this core.
