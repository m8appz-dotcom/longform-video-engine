# Pipeline boundaries

`engine.longform_pipeline` is the active long-form entry point. `engine/longform/planning.py` owns direction parsing, script display copy, avatar selection, evidence routes, and closing/CTA planning. The entry point re-exports those helpers for compatibility; the existing regression suite covers that boundary. Media routing, production-mode checks, rendering, and QA remain separate existing modules.

The older `engine.pipeline` is the vertical-video workflow. It is retained for historical compatibility and is not the long-form quickstart. Shared asset/media helpers serve both paths. The optional asset library has its own [manifest and recovery instructions](../asset-library/README.md); it is not required by the offline tests or authored contract/render example.

`tools/create_demo.py` validates an authored script contract and optionally invokes the actual Remotion Longform composition for a still. Its evidence explicitly excludes voice generation, footage selection, human editorial approval, and full production QA. Fixture checks and a rendered still do not establish full-video quality.
