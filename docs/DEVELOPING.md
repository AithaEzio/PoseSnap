# PoseSnap source snapshot

This snapshot contains application source and distributable preview derivatives, not a copy of the maintainer’s private workspace. Version remains 1.0.1. The application-code baseline is e0a7b825453118e6851628eb6812037cc5159f954d54d73303b85bcb1c02f1d0; licence/documentation additions are later. The application and engine download bytes are unchanged by this publication.

## Frontend

Use Node >=22.12, then `npm ci`, `npm run check`, `npm test` and `npm run build`. The public test command selects a 15-case transaction/engine-status smoke subset, not the private 701-check qualification corpus. In-tree historical tests that depend on withheld fixtures are excluded from the public test and TypeScript-check configurations. Browser development (`npm run dev`) displays the interface; it is not GPU inference. Fixture-only validation URLs intentionally have no private backing data.

## Native development

Use Rust’s Windows MSVC toolchain, Microsoft C++ build tools and a Windows SDK including rc.exe. In a configured developer PowerShell, set `$env:POSESNAP_DEV_ROOT=(Get-Location).Path` and run `npm run tauri -- dev`. The pinned private-browser setup is still required. Heavy engines install through the app; do not point a development checkout at someone else’s data. Source-only compilation can use `npm run tauri -- build --no-bundle`; that command alone does not assemble a complete portable distribution.

## Runtime and interoperability data

The Python worker is separate from the frontend/native build. Its pinned dependency requirements and model/component contracts are included; engine payloads and vendor installations are not. Download or import official components using the app.

`worker/default-rigs.json` and captured rig fixtures are deliberately withheld from this new source publication pending explicit redistribution-provenance review. The official application already supplies its compatibility data for app use; this new licence does not relicense it. The source code can be inspected and compiled, but the snapshot is not a self-contained body-posing installation. Do not replace that missing data with personal connected-figure captures when sharing a fork.

The public snapshot does not ship the private 701-check release environment, training/evaluation material, or maintainer toolchains. Model inference, full public-checkout test reproducibility and live DAZ remain separate qualifications. No private script’s budget ledger should be copied or reused as authorisation for a new run.

## Separate licences

Original application code/documentation uses the root custom licence. Preview assets retain the adjacent CC BY licences. Upstream libraries, models and runtimes retain their notices. A source snapshot licence is not permission to relicense third-party content or sell the application.
