# PoseSnap third-party notices

PoseSnap includes the following components. Their licenses continue to apply separately.
The original PoseSnap application and logo do not change upstream license terms.
No DAZ figure mesh, morph, texture, personal connected-rig profile, reference photo, or user history is included in this source publication. Built-in interoperability metadata is withheld pending provenance review and is not relicensed here.
Pose previews use the credited mannequin. Expression preview adapts the supplied
Face Sculpting 108th (female) model by ComputerCat. DAZ connections read metadata
without copying figure geometry.

## Expression face asset

**Face Sculpting 108th (female)** by **ComputerCat (@ComputerCats)**,
[original model](https://sketchfab.com/3d-models/face-sculpting-108th-female-b6638e38d0b24ec7be39b578df25727b),
[artist](https://sketchfab.com/ComputerCats), licensed
[Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
The official Sketchfab metadata identifies this license. PoseSnap reduces the mesh
for local preview, adds facial controls, changes material presentation and converts
its coordinate system. The artist does not endorse these modifications. The
original supplied `Face Model.blend` remains unchanged. Attribution also appears
in Settings → About and alongside the derived asset.

| Component | Version | License / source |
|---|---|---|
| Python | 3.11.9 | PSF; licenses/Python-3.11.9.txt |
| SAM 3D Body DINOv3 | b5c765a | SAM License; licenses/sam-3d-body/LICENSE |
| DINOv3 | 6876159 | DINOv3 License; licenses/dinov3/LICENSE.md |
| MHR weights | official SAM 3D Body asset | Apache 2.0; licenses/MHR/LICENSE |
| SAM 2.1 Tiny | 2b90b9f | Apache 2.0; licenses/sam2/LICENSE |
| MoGe-2 | 74fbce0 | MIT; licenses/MoGe/LICENSE |
| YOLOX-s ONNX | release 0.1.1rc0 | Apache 2.0; licenses/YOLOX.txt |
| WebView2 Fixed Version x64 | 154.0.4258.62 | Microsoft runtime terms; licenses/WebView2-runtime.html |
| MSVC runtime | 14.44 | Microsoft redistributable terms; licenses/Microsoft-VC-runtime.md |
| Tauri | locked Cargo.lock | MIT / Apache 2.0; licenses/rust/ |
| MediaPipe Tasks Vision (optional Expression engine) | 1.1.0 | Apache 2.0; licenses/mediapipe/LICENSE.txt; https://github.com/google-ai-edge/mediapipe |
| Face Landmarker task, float16, version 1 | official Google model | Face mesh and blendshape model cards identify Apache 2.0; licenses/mediapipe/README.md |

SAM and DINOv3 license agreements are included in full. They grant redistribution under their respective terms and impose use restrictions. Redistributors must preserve these agreements. Microsoft runtime redistribution is subject to Microsoft's terms and the redistributor's licensing eligibility.

PyTorch's packaged LICENSE and NOTICE include its CUDA and other third-party components.
WebView2's existing runtime notices remain inside runtime/webview2.

## Private Python packages

| Package | Version | License |
|---|---|---|
| aiohappyeyeballs | 2.7.1 | PSF-2.0 |
| aiohttp | 3.14.4 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache 2.0 |
| antlr4-python3-runtime | 4.9.3 | BSD |
| anyio | 4.15.1 | MIT |
| attrs | 26.1.0 | MIT |
| braceexpand | 0.1.7 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | See packaged license/metadata |
| coloredlogs | 15.0.1 | MIT |
| einops | 0.8.1 | MIT |
| filelock | 3.32.3 | MIT |
| flatbuffers | 25.12.19 | Apache 2.0 |
| frozenlist | 1.8.0 | Apache-2.0 |
| fsspec | 2026.7.0 | BSD-3-Clause |
| fvcore | 0.1.5.post20221221 | Apache 2.0 |
| glcontext | 3.0.0 | MIT |
| h11 | 0.16.0 | MIT |
| hf-xet | 1.6.0 | Apache-2.0 |
| httpcore2 | 2.13.1 | BSD-3-Clause |
| httpx2 | 2.13.1 | BSD-3-Clause |
| huggingface_hub | 2.1.1 | Apache-2.0 |
| humanfriendly | 10.0 | MIT |
| hydra-core | 1.3.2 | MIT |
| idna | 3.20 | BSD-3-Clause |
| iopath | 0.1.10 | MIT licensed, as found in the LICENSE file |
| Jinja2 | 3.1.6 | See packaged license/metadata |
| lightning-utilities | 0.15.3 | Apache-2.0 |
| loguru | 0.7.3 | See packaged license/metadata |
| markdown-it-py | 4.2.0 | See packaged license/metadata |
| MarkupSafe | 3.0.3 | BSD-3-Clause |
| mdurl | 0.1.2 | See packaged license/metadata |
| moderngl | 5.12.0 | MIT |
| mpmath | 1.3.0 | BSD |
| multidict | 6.9.1 | Apache License 2.0 |
| networkx | 3.2.1 | See packaged license/metadata |
| numpy | 2.2.6 | See packaged license/metadata |
| omegaconf | 2.3.0 | See packaged license/metadata |
| onnxruntime | 1.22.1 | MIT License |
| opencv-python-headless | 4.12.0.88 | Apache 2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pillow | 11.3.0 | MIT-CMU |
| pip | 26.2.1 | MIT |
| portalocker | 4.4.0 | BSD-3-Clause |
| propcache | 0.5.4 | Apache-2.0 |
| protobuf | 7.36.2 | 3-Clause BSD License |
| Pygments | 2.21.0 | BSD-2-Clause |
| pyreadline3 | 3.5.6 | BSD |
| pytorch-lightning | 2.5.5 | Apache-2.0 |
| PyYAML | 6.0.3 | MIT |
| rich | 14.1.0 | MIT |
| roma | 1.5.3 | See packaged license/metadata |
| safetensors | 0.8.0 | See packaged license/metadata |
| scipy | 1.15.3 | See packaged license/metadata |
| setuptools | 84.0.0 | MIT |
| sympy | 1.14.0 | BSD |
| tabulate | 0.10.0 | MIT |
| termcolor | 3.3.0 | MIT |
| timm | 1.0.19 | Apache-2.0 |
| torch | 2.8.0+cu128 | BSD-3-Clause |
| torchmetrics | 1.9.0 | Apache-2.0 |
| torchvision | 0.23.0+cu128 | BSD |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| trimesh | 4.8.2 | See packaged license/metadata |
| truststore | 0.10.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| utils3d | 1.7 | MIT |
| webdataset | 1.0.2 | BSD-3-Clause |
| wheel | 0.48.0 | MIT |
| win32_setctime | 1.2.0 | MIT license |
| yacs | 0.1.8 | UNKNOWN |
| yarl | 1.25.1 | Apache-2.0 |

## Rust dependency inventory

MPL-2.0 component source is included under the corresponding `licenses/rust/*/source/` folder.

| Crate | Version | License |
|---|---|---|
| adler2 | 2.0.1 | 0BSD OR MIT OR Apache-2.0 |
| aho-corasick | 1.1.5 | Unlicense OR MIT |
| alloc-no-stdlib | 3.0.0 | BSD-3-Clause |
| alloc-stdlib | 0.3.0 | BSD-3-Clause |
| anyhow | 1.0.104 | MIT OR Apache-2.0 |
| arboard | 3.6.1 | MIT OR Apache-2.0 |
| autocfg | 1.5.1 | Apache-2.0 OR MIT |
| base64 | 0.22.1 | MIT OR Apache-2.0 |
| base64 | 0.23.1 | MIT OR Apache-2.0 |
| bit-set | 0.8.0 | Apache-2.0 OR MIT |
| bit-vec | 0.8.0 | Apache-2.0 OR MIT |
| bitflags | 1.3.2 | MIT/Apache-2.0 |
| bitflags | 2.13.2 | MIT OR Apache-2.0 |
| block-buffer | 0.10.4 | MIT OR Apache-2.0 |
| brotli | 9.0.0 | BSD-3-Clause AND MIT |
| brotli-decompressor | 6.0.1 | BSD-3-Clause/MIT |
| bs58 | 0.5.1 | MIT/Apache-2.0 |
| bytemuck | 1.25.2 | Zlib OR Apache-2.0 OR MIT |
| byteorder | 1.5.0 | Unlicense OR MIT |
| byteorder-lite | 0.1.0 | Unlicense OR MIT |
| bytes | 1.12.1 | MIT |
| camino | 1.2.6 | MIT OR Apache-2.0 |
| cargo-platform | 0.1.9 | MIT OR Apache-2.0 |
| cargo_metadata | 0.19.2 | MIT |
| cargo_toml | 1.0.1 | Apache-2.0 OR MIT |
| cc | 1.6.0 | MIT OR Apache-2.0 |
| cfb | 0.14.0 | MIT |
| cfg-if | 1.0.5 | MIT OR Apache-2.0 |
| chrono | 0.4.45 | MIT OR Apache-2.0 |
| clipboard-win | 5.4.1 | BSL-1.0 |
| cookie | 0.18.2 | MIT OR Apache-2.0 |
| cpufeatures | 0.2.17 | MIT OR Apache-2.0 |
| crc32fast | 1.5.2 | MIT OR Apache-2.0 |
| crossbeam-channel | 0.5.17 | MIT OR Apache-2.0 |
| crossbeam-utils | 0.8.23 | MIT OR Apache-2.0 |
| crypto-common | 0.1.7 | MIT OR Apache-2.0 |
| cssparser | 0.37.0 | MPL-2.0 |
| cssparser-macros | 0.7.1 | MPL-2.0 |
| ctor | 1.0.13 | Apache-2.0 OR MIT |
| darling | 0.24.1 | MIT |
| darling_core | 0.24.1 | MIT |
| darling_macro | 0.24.1 | MIT |
| defmt | 1.1.1 | MIT OR Apache-2.0 |
| defmt-macros | 1.1.1 | MIT OR Apache-2.0 |
| defmt-parser | 1.0.0 | MIT OR Apache-2.0 |
| deranged | 0.5.8 | MIT OR Apache-2.0 |
| derive_more | 2.1.1 | MIT |
| derive_more-impl | 2.1.1 | MIT |
| digest | 0.10.7 | MIT OR Apache-2.0 |
| dirs | 7.0.0 | MIT OR Apache-2.0 |
| dirs-sys | 0.5.0 | MIT OR Apache-2.0 |
| displaydoc | 0.2.7 | MIT OR Apache-2.0 |
| dom_query | 0.28.0 | MIT |
| dpi | 0.1.2 | Apache-2.0 AND MIT |
| dtoa | 1.0.11 | MIT OR Apache-2.0 |
| dtoa-short | 0.3.5 | MPL-2.0 |
| dunce | 1.0.5 | CC0-1.0 OR MIT-0 OR Apache-2.0 |
| dyn-clone | 1.0.20 | MIT OR Apache-2.0 |
| embed-resource | 3.0.12 | MIT |
| equivalent | 1.0.2 | Apache-2.0 OR MIT |
| erased-serde | 0.4.10 | MIT OR Apache-2.0 |
| error-code | 3.4.0 | BSL-1.0 |
| fastrand | 2.5.0 | Apache-2.0 OR MIT |
| fax | 0.2.7 | MIT |
| fdeflate | 0.3.7 | MIT OR Apache-2.0 |
| find-msvc-tools | 0.1.14 | MIT OR Apache-2.0 |
| flate2 | 1.1.10 | MIT OR Apache-2.0 |
| fnv | 1.0.7 | Apache-2.0 / MIT |
| foldhash | 0.2.0 | Zlib |
| form_urlencoded | 1.2.2 | MIT OR Apache-2.0 |
| generic-array | 0.14.7 | MIT |
| getrandom | 0.3.4 | MIT OR Apache-2.0 |
| getrandom | 0.4.3 | MIT OR Apache-2.0 |
| glob | 0.3.4 | MIT OR Apache-2.0 |
| half | 2.7.1 | MIT OR Apache-2.0 |
| hashbrown | 0.12.3 | MIT OR Apache-2.0 |
| hashbrown | 0.17.1 | MIT OR Apache-2.0 |
| heck | 0.5.0 | MIT OR Apache-2.0 |
| hex | 0.4.3 | MIT OR Apache-2.0 |
| html5ever | 0.39.0 | MIT OR Apache-2.0 |
| http | 1.5.0 | MIT OR Apache-2.0 |
| ico | 0.5.0 | MIT |
| icu_collections | 2.3.0 | Unicode-3.0 |
| icu_locale_core | 2.3.0 | Unicode-3.0 |
| icu_normalizer | 2.3.0 | Unicode-3.0 |
| icu_normalizer_data | 2.3.0 | Unicode-3.0 |
| icu_properties | 2.3.0 | Unicode-3.0 |
| icu_properties_data | 2.3.0 | Unicode-3.0 |
| icu_provider | 2.3.1 | Unicode-3.0 |
| ident_case | 1.0.1 | MIT/Apache-2.0 |
| idna | 1.1.0 | MIT OR Apache-2.0 |
| idna_adapter | 1.2.2 | Apache-2.0 OR MIT |
| image | 0.25.10 | MIT OR Apache-2.0 |
| indexmap | 1.9.3 | Apache-2.0 OR MIT |
| indexmap | 2.14.2 | Apache-2.0 OR MIT |
| infer | 0.22.0 | MIT |
| itoa | 1.0.18 | MIT OR Apache-2.0 |
| jiff | 0.2.38 | Unlicense OR MIT |
| jiff-core | 0.1.1 | Unlicense OR MIT |
| jiff-tzdb | 0.1.9 | Unlicense OR MIT |
| jiff-tzdb-platform | 0.1.3 | Unlicense OR MIT |
| json-patch | 4.2.0 | MIT/Apache-2.0 |
| jsonptr | 0.7.1 | MIT OR Apache-2.0 |
| keyboard-types | 0.8.3 | MIT OR Apache-2.0 |
| libc | 0.2.190 | MIT OR Apache-2.0 |
| litemap | 0.8.3 | Unicode-3.0 |
| lock_api | 0.4.14 | MIT OR Apache-2.0 |
| log | 0.4.34 | MIT OR Apache-2.0 |
| markup5ever | 0.39.0 | MIT OR Apache-2.0 |
| memchr | 2.8.3 | Unlicense OR MIT |
| mime | 0.3.17 | MIT OR Apache-2.0 |
| miniz_oxide | 0.8.9 | MIT OR Zlib OR Apache-2.0 |
| miniz_oxide | 0.9.1 | MIT OR Zlib OR Apache-2.0 |
| mio | 1.2.4 | MIT |
| moxcms | 0.8.1 | BSD-3-Clause OR Apache-2.0 |
| muda | 0.20.0 | Apache-2.0 OR MIT |
| new_debug_unreachable | 1.0.6 | MIT |
| num-conv | 0.2.2 | MIT OR Apache-2.0 |
| num-traits | 0.2.19 | MIT OR Apache-2.0 |
| once_cell | 1.21.4 | MIT OR Apache-2.0 |
| option-ext | 0.2.0 | MPL-2.0 |
| parking_lot | 0.12.5 | MIT OR Apache-2.0 |
| parking_lot_core | 0.9.12 | MIT OR Apache-2.0 |
| percent-encoding | 2.3.2 | MIT OR Apache-2.0 |
| phf | 0.13.1 | MIT |
| phf_codegen | 0.13.1 | MIT |
| phf_generator | 0.13.1 | MIT |
| phf_macros | 0.13.1 | MIT |
| phf_shared | 0.13.1 | MIT |
| pin-project-lite | 0.2.17 | Apache-2.0 OR MIT |
| plist | 1.10.1 | MIT |
| png | 0.17.16 | MIT OR Apache-2.0 |
| png | 0.18.1 | MIT OR Apache-2.0 |
| potential_utf | 0.1.6 | Unicode-3.0 |
| powerfmt | 0.2.1 | MIT OR Apache-2.0 |
| precomputed-hash | 0.1.1 | MIT |
| proc-macro2 | 1.0.107 | MIT OR Apache-2.0 |
| pxfm | 0.1.30 | BSD-3-Clause OR Apache-2.0 |
| quick-error | 2.0.1 | MIT/Apache-2.0 |
| quick-xml | 0.42.0 | MIT |
| quote | 1.0.47 | MIT OR Apache-2.0 |
| raw-window-handle | 0.6.2 | MIT OR Apache-2.0 OR Zlib |
| ref-cast | 1.0.27 | MIT OR Apache-2.0 |
| ref-cast-impl | 1.0.27 | MIT OR Apache-2.0 |
| regex | 1.13.1 | MIT OR Apache-2.0 |
| regex-automata | 0.4.18 | MIT OR Apache-2.0 |
| regex-syntax | 0.8.11 | MIT OR Apache-2.0 |
| rfd | 0.16.0 | MIT |
| rustc-hash | 2.1.3 | Apache-2.0 OR MIT |
| rustc_version | 0.4.1 | MIT OR Apache-2.0 |
| same-file | 1.0.6 | Unlicense/MIT |
| schemars | 0.8.22 | MIT |
| schemars | 0.9.0 | MIT |
| schemars | 1.2.2 | MIT |
| schemars_derive | 0.8.22 | MIT |
| scopeguard | 1.2.0 | MIT OR Apache-2.0 |
| selectors | 0.38.0 | MPL-2.0 |
| semver | 1.0.28 | MIT OR Apache-2.0 |
| serde | 1.0.229 | MIT OR Apache-2.0 |
| serde-untagged | 0.1.9 | MIT OR Apache-2.0 |
| serde_core | 1.0.229 | MIT OR Apache-2.0 |
| serde_derive | 1.0.229 | MIT OR Apache-2.0 |
| serde_derive_internals | 0.29.1 | MIT OR Apache-2.0 |
| serde_json | 1.0.151 | MIT OR Apache-2.0 |
| serde_repr | 0.1.21 | MIT OR Apache-2.0 |
| serde_spanned | 1.1.1 | MIT OR Apache-2.0 |
| serde_with | 3.24.0 | MIT OR Apache-2.0 |
| serde_with_macros | 3.24.0 | MIT OR Apache-2.0 |
| serialize-to-javascript | 0.1.2 | MIT OR Apache-2.0 |
| serialize-to-javascript-impl | 0.1.2 | MIT OR Apache-2.0 |
| servo_arc | 0.4.3 | MIT OR Apache-2.0 |
| sha2 | 0.10.9 | MIT OR Apache-2.0 |
| shlex | 2.0.1 | MIT OR Apache-2.0 |
| simd-adler32 | 0.3.10 | MIT |
| siphasher | 1.0.4 | MIT OR Apache-2.0 |
| smallvec | 1.16.2 | MIT OR Apache-2.0 |
| socket2 | 0.6.5 | MIT OR Apache-2.0 |
| softbuffer | 0.4.8 | MIT OR Apache-2.0 |
| stable_deref_trait | 1.2.1 | MIT OR Apache-2.0 |
| string_cache | 0.9.0 | MIT OR Apache-2.0 |
| string_cache_codegen | 0.6.1 | MIT OR Apache-2.0 |
| strsim | 0.11.1 | MIT |
| syn | 2.0.119 | MIT OR Apache-2.0 |
| syn | 3.0.6 | MIT OR Apache-2.0 |
| synstructure | 0.14.0 | MIT |
| tao | 0.37.1 | Apache-2.0 |
| tauri | 2.12.1 | Apache-2.0 OR MIT |
| tauri-build | 2.7.1 | Apache-2.0 OR MIT |
| tauri-codegen | 2.7.1 | Apache-2.0 OR MIT |
| tauri-macros | 2.7.1 | Apache-2.0 OR MIT |
| tauri-plugin | 2.7.1 | Apache-2.0 OR MIT |
| tauri-plugin-dialog | 2.8.1 | Apache-2.0 OR MIT |
| tauri-plugin-fs | 2.6.0 | Apache-2.0 OR MIT |
| tauri-runtime | 2.12.1 | Apache-2.0 OR MIT |
| tauri-runtime-wry | 2.12.1 | Apache-2.0 OR MIT |
| tauri-utils | 2.10.1 | Apache-2.0 OR MIT |
| tauri-winres | 0.3.6 | MIT |
| tendril | 0.5.1 | MIT OR Apache-2.0 |
| thiserror | 2.0.21 | MIT OR Apache-2.0 |
| thiserror-impl | 2.0.21 | MIT OR Apache-2.0 |
| tiff | 0.11.3 | MIT |
| time | 0.3.55 | MIT OR Apache-2.0 |
| time-core | 0.1.9 | MIT OR Apache-2.0 |
| time-macros | 0.2.32 | MIT OR Apache-2.0 |
| tinystr | 0.8.4 | Unicode-3.0 |
| tinyvec | 1.13.3 | Zlib OR Apache-2.0 OR MIT |
| tokio | 1.53.2 | MIT |
| toml | 1.1.6+spec-1.1.0 | MIT OR Apache-2.0 |
| toml_datetime | 1.1.1+spec-1.1.0 | MIT OR Apache-2.0 |
| toml_parser | 1.1.3+spec-1.1.0 | MIT OR Apache-2.0 |
| toml_writer | 1.1.2+spec-1.1.0 | MIT OR Apache-2.0 |
| tracing | 0.1.44 | MIT |
| tracing-core | 0.1.36 | MIT |
| tray-icon | 0.25.1 | MIT OR Apache-2.0 |
| typeid | 1.0.3 | MIT OR Apache-2.0 |
| typenum | 1.20.1 | MIT OR Apache-2.0 |
| unicode-ident | 1.0.26 | (MIT OR Apache-2.0) AND Unicode-3.0 |
| unicode-segmentation | 1.13.3 | MIT OR Apache-2.0 |
| url | 2.5.8 | MIT OR Apache-2.0 |
| urlpattern | 0.6.0 | MIT |
| utf8_iter | 1.0.4 | Apache-2.0 OR MIT |
| uuid | 1.27.0 | Apache-2.0 OR MIT |
| version_check | 0.9.5 | MIT/Apache-2.0 |
| vswhom | 0.1.0 | MIT |
| vswhom-sys | 0.1.3 | MIT |
| walkdir | 2.5.0 | Unlicense/MIT |
| web-time | 1.1.0 | MIT OR Apache-2.0 |
| web_atoms | 0.2.6 | MIT OR Apache-2.0 |
| webview2-com | 0.39.1 | MIT |
| webview2-com-macros | 0.8.1 | MIT |
| webview2-com-sys | 0.39.1 | MIT |
| weezl | 0.1.12 | MIT OR Apache-2.0 |
| winapi-util | 0.1.11 | Unlicense OR MIT |
| window-vibrancy | 0.8.1 | Apache-2.0 OR MIT |
| windows | 0.62.2 | MIT OR Apache-2.0 |
| windows-collections | 0.3.2 | MIT OR Apache-2.0 |
| windows-core | 0.62.2 | MIT OR Apache-2.0 |
| windows-future | 0.3.2 | MIT OR Apache-2.0 |
| windows-implement | 0.60.2 | MIT OR Apache-2.0 |
| windows-interface | 0.59.3 | MIT OR Apache-2.0 |
| windows-link | 0.2.1 | MIT OR Apache-2.0 |
| windows-numerics | 0.3.1 | MIT OR Apache-2.0 |
| windows-result | 0.4.1 | MIT OR Apache-2.0 |
| windows-strings | 0.5.1 | MIT OR Apache-2.0 |
| windows-sys | 0.60.2 | MIT OR Apache-2.0 |
| windows-sys | 0.61.2 | MIT OR Apache-2.0 |
| windows-targets | 0.53.5 | MIT OR Apache-2.0 |
| windows-threading | 0.2.1 | MIT OR Apache-2.0 |
| windows-version | 0.1.7 | MIT OR Apache-2.0 |
| windows_x86_64_msvc | 0.53.1 | MIT OR Apache-2.0 |
| winnow | 1.0.4 | MIT |
| winreg | 0.56.0 | MIT |
| writeable | 0.6.4 | Unicode-3.0 |
| wry | 0.57.0 | Apache-2.0 OR MIT |
| yoke | 0.8.3 | Unicode-3.0 |
| yoke-derive | 0.8.4 | Unicode-3.0 |
| zerocopy | 0.8.60 | BSD-2-Clause OR Apache-2.0 OR MIT |
| zerocopy-derive | 0.8.60 | BSD-2-Clause OR Apache-2.0 OR MIT |
| zerofrom | 0.1.8 | Unicode-3.0 |
| zerofrom-derive | 0.1.8 | Unicode-3.0 |
| zerotrie | 0.2.5 | Unicode-3.0 |
| zerovec | 0.11.8 | Unicode-3.0 |
| zerovec-derive | 0.11.6 | Unicode-3.0 |
| zlib-rs | 0.6.8 | Zlib |
| zmij | 1.0.23 | MIT |
| zune-core | 0.5.3 | MIT OR Apache-2.0 OR Zlib |
| zune-jpeg | 0.5.15 | MIT OR Apache-2.0 OR Zlib |

## Current body preview mannequin

[Rigged Character](https://sketchfab.com/3d-models/rigged-character-6ead91e980434073bfb15799d3e674bb) by [BLENDERJO](https://sketchfab.com/BLENDERJO), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The current derived surface is identified by public/mannequin/LICENSE.txt. Adapted and rigged for PoseSnap's preview; Genesis shapes may differ. Original authoring assets are preserved privately.

Earlier development used Quaternius's CC0 Universal Base Characters. That historical asset is not the current BLENDERJO preview and is not included in this source snapshot. Its retained original notice remains with the historical development files.

## Development-only whole-body and hand measurements

RTMW-L (384 × 288) and RTMPose hand (256 × 256) ONNX checkpoints are official OpenMMLab MMPose exports. Their source URLs and SHA-256 digests are recorded in `.tools/refinement/models.json`. These weights are development assets and are not bundled into any distributed runtime by this change. The adapter uses the existing private ONNX Runtime; it does not distribute or install MMPose/MMCV.

Upstream project and model documentation: https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose

Upstream framework license: https://github.com/open-mmlab/mmpose/blob/main/LICENSE

Before any later distribution, review the checkpoint/model and training-data redistribution terms, preserve applicable notices, and include the required license material. MediaPipe Heavy is a benchmark comparison input only; no MediaPipe runtime or task model is added to the app.

## Development-only expressive pose training

The isolated `.tools/training` workspace contains the **100STYLE Dataset**, credited to **Ian Mason**, under **CC BY 4.0**. Motion samples are converted to semantic descriptions and original primitive reference renders. Publisher: https://www.ianxmason.com/100style/ · License: https://creativecommons.org/licenses/by/4.0/ . Source URLs and checksums remain in the development source manifest.

The official **Qwen3.5-0.8B** checkpoint is by the **Qwen Team**, under **Apache 2.0**: https://huggingface.co/Qwen/Qwen3.5-0.8B . This is historical development attribution. Qwen components and exclusively Qwen training artifacts are retired; their provenance and evaluation records are retained.

Selected COCO photographs retain independently checked photo-specific CC BY/CC0 license and photographer attribution receipts. COCO annotations do not license all photographs. Each export's `training-sources.json` records the applicable source URLs, author credits and rights; `TRAINING-NOTICE.md` travels with a future qualified pack. No source photographs are bundled in the app. See `training/README.md` for the exact current data and qualification limits.

## Optional Kimodo body generator

**Kimodo-SOMA-RP-v1.2** is by NVIDIA, under the NVIDIA Open Model License. Its
checkpoint, configuration, statistics and license are installed only when this
optional component is chosen. Source: https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2 .
The headless Kimodo code and official MotionCorrection extension are Apache 2.0;
their source license and attributions are retained in `runtime/kimodo/core`.
The only package change makes optional training/retrieval imports lazy. No
diffusion, skeleton or contact-correction algorithm is replaced.

The CPU text encoder uses LocalAI's pinned **Llama-3-Kimodo Q8_0** conversion of
Meta Llama 3 and McGill LLM2Vec adapters. **Built with Meta Llama 3.** The Meta
Llama 3 Community License and upstream notice accompany the installed encoder
in `models/kimodo/encoder`. Source: https://huggingface.co/LocalAI-io/Llama-3-Kimodo-GGML .
The encoder bridge builds against Apache-2.0 kimodo.cpp and MIT GGML. Private
validation dependencies retain their wheel license material. Eigen headers
(MPL 2.0) are used only to build the official motion correction extension;
MSVC runtime redistribution follows Microsoft's applicable terms. No Kimodo
training datasets, skin meshes, demo UI or BF16 reference weights are installed.
# CLUE body-prior diagnostics

PoseSnap includes the self-contained SAM 3D Body CLUE plugin at commit
`df00480954d0fc5d4c2f4165f08da0c886ec3991`, under the BSD-3-Clause-Clear license
in `licenses/clue/LICENSE`. This license grants no patent rights.
Source: https://github.com/vita-epfl/CLUE . The optional gated uncertainty-head
weights remain separately licensed under the upstream SAM License; PoseSnap
requires an authorized local import and does not authenticate or download them
at runtime. The larger separately trained decoder is not included.

Citation: Shukla et al., *Modeling Uncertainty Propagation in 3D Morphable Models*,
2026, https://arxiv.org/abs/2610.24646 . Diagnostics describe the initial SAM
body prior only; global placement, refined hands and expressions are excluded.

