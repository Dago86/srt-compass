# Model catalog and review policy

`src/video_sottotitoli/model_catalog.json` is the public, reviewed source for
models that can be selected for SRT translation and contextual revision. The
provider model lists are intentionally not used as a price or quality API.

## What a model record must establish

Before a model is marked executable, a maintainer records its provider model
identifier, the official source URLs and verification date, input and output
prices, supported request parameters, Responses support and the structured
output contract required by SRT Compass. A record that lacks any of these facts
is visible as discovered but cannot be selected.

DeepSeek records include peak and off-peak rates. The application selects the
applicable published band at estimate time and saves it with the job. OpenAI
records include the model-specific reasoning setting; for example, GPT-6.1 Sol
uses a supported reasoning level rather than an unsupported `none` value.

## Expected quality

The labels **economy**, **balanced** and **advanced** are a documented product
assessment, not an API field and not a claim of objective translation accuracy.
Every rated entry names the assessed date and relevant subtitle languages. The
assessment must review the maintained fixtures for English, Italian, Japanese
and French, including sentence boundaries, names, numbers, technical terms and
long cues, and record human findings before publication. It may be updated when
a new model version, prompt contract or regression result warrants it.

The application never sends an additional request to score a completed result.
Instead it reports local checks for structure, non-empty cues, identifiers,
numbers, language hints and readability. Those checks cannot prove fidelity to
the original audio.

## Publishing a catalog update

1. Verify the identifiers and capabilities with official provider documentation
   and simulated structured-response tests.
2. Verify published pricing, currency and time-band conditions; add source URLs
   and the verification date.
3. Run the subtitle fixture review and document the quality assessment in the
   record.
4. Run `python -m unittest discover -s tests` and `ruff check src tests run.py`.
5. Update the catalog version and publish it with the application source.

Installed applications fetch this file at most once every 24 hours. If the
network, remote catalog or ECB exchange reference is unavailable, they preserve
the last valid local data and clearly fall back to USD where necessary.
