# Optional local Expression engine

SDK: Google MediaPipe Tasks Vision 1.1.0, unmodified version-pinned JavaScript
and WASM. The upstream Apache 2.0 license is included in LICENSE.txt.

Model: the official `face_landmarker/float16/1/face_landmarker.task` bundle.
Download URL: https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task

Model cards:
- https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf
- https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf

The model cards identify Apache 2.0 and describe failures with distance,
occlusion and extreme head angles. Expression coefficients are movement
amounts, not confidence. This component is not a biometric identification tool.

File sizes, exact source URLs, SHA-256 pins and mirror fallbacks are recorded in
assets/expression/engine-lock.json and the source engine catalogue. Runtime
inference uses only those local files; no SDK CDN or photo upload is used.
