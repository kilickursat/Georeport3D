# GeoReport3D — Technical References and Current Assumptions

The implementation should check the pinned versions against current upstream documentation when the coder sets up the environment. The references below are the basis for the initial architecture as checked during project preparation.

## Qwen3.6-27B NVFP4

Unsloth Hugging Face model:

https://huggingface.co/unsloth/Qwen3.6-27B-NVFP4

Observed current facts:

- Apache-2.0 license.
- Image-text-to-text model metadata.
- Published NVFP4 checkpoint.
- Model card says it works on a 24 GB VRAM GPU.
- Model card provides vLLM serving instructions.
- Model card says not to use the Marlin backend for this checkpoint and recommends native/cute-DSL/CUTLASS/FlashInfer-related paths.

Source: citeturn459153search0turn459153search6

## vLLM

Supported-model documentation indicates multimodal models can accept combinations such as text + image, and some multimodal models can use a text-only mode to reduce GPU memory when vision is not required.

Source: citeturn349019search5

## Modal

Current Modal pricing checked for this project lists the L4 at $0.000222/sec. Modal documents autoscaling controls including `max_containers`, `min_containers`, `buffer_containers`, and `scaledown_window`.

Source: citeturn349019search3turn349019search4

## Docling

Current Docling documentation lists PDF and DOCX as supported inputs and JSON/JSONL-related outputs, including lossless Docling JSON and chunked JSONL.

Source: citeturn349019search0

## PostGIS

PostGIS `ST_Transform` transforms coordinates between spatial reference systems; `ST_SetSRID` only labels the geometry with an SRID and does not change the underlying coordinates.

Source: citeturn349019search1turn349019search7

## Important note

All performance numbers are model/vendor benchmarks, not GeoReport3D benchmarks. The project must create its own geotechnical benchmark before choosing the final production configuration.
