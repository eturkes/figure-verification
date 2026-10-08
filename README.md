# figure-verification

figure-verification lets a language model draw charts in Open WebUI, but the model never supplies a
plotted value. The model writes a Python program that draws the chart. A separate verifier checks
the program and recomputes every plotted value from the user's own CSV file or from the function
that the user states. The chart appears only when every check passes. Otherwise the chat shows
`Figure verification failed, no image produced`, and a status line above that message states the
reason. Each chart reply also has a `Show checks` list of every check and its result. Click a check
to open it: it shows what the check does, the program lines that it read and why it failed. It also
links to its section of the [verification reference](docs/verification.md).

## What this repository delivers

- **Two files to paste into Open WebUI.** `paste-in/figure_verification_tool.py` and
  `paste-in/figure_verification_filter.py` contain the complete verifier. They need only the Python
  standard library and what Open WebUI 0.10.2 already contains. They make no network calls.
- **An administrator guide in English and Japanese.** Read [docs/admin/README.md](docs/admin/README.md)
  or [docs/admin/README.ja.md](docs/admin/README.ja.md) to install the two files.
- **A demo harness.** One command starts a local Open WebUI with a local model or a stub model. The
  harness also holds the measurement tools and the test suite.

The repository also contains an older JSON-spec verifier service. That service runs headless and is
not part of the Open WebUI deliverable. See [docs/json-spec.md](docs/json-spec.md).

## What "verified" means

A chart passes when all of these statements are true:

1. **Provenance.** The verifier recomputed every plotted number from the uploaded CSV file or from
   the function in the request. The model supplied no plotted number.
2. **Integrity.** The chart obeys a closed set of rules. For example, bars start at zero and the
   chart has one linear axis pair. Also, the program drops no data row silently.
3. **Observation.** The values that the browser runtime drew match the recomputed values. They
   match exactly for CSV data. For a function, each value lies inside a rounding range that the
   verifier computes from the formula.

After a pass, the chat also shows a sentence that states what the chart shows, for example the sum of
revenue for each region. If the request contains Japanese kana, that sentence is in Japanese. Read
that sentence. A pass does not mean that the chart answers the
question. The chart can show a different measure or grouping than the user wanted.

The verifier trusts the browser, the Pyodide runtime, matplotlib, the Japanese font that Open
WebUI contains and the pixels. It does not check them. Japanese text in a chart needs that font,
which the filter sends to the browser. The font does not cover Japanese text inside `$` signs (math
text). Such a chart failed in the recorded tests, and it can also show empty symbols. The verifier accepts a small subset of pandas, numpy and matplotlib:

- a bar, horizontal bar, line or scatter chart over two CSV columns;
- one sum, mean, minimum or maximum for each group;
- a line or scatter chart of a stated function.

It refuses everything else.

## Measured results

All model results come from one device and configuration: `Qwen2.5-Coder-0.5B-Instruct` in fp16 on
an NVIDIA MX150 with greedy decoding. A different model or device can give different results.

- **Held-out acceptance.** On 40 held-out prompts, measured once, 14 of 20 simple requests verified and the verifier
  blocked 20 of 20 complicated requests. The acceptance bar is 70% for each category, so the simple
  result meets it exactly. The simple result depends on line-chart support that the project added before
  the run and chose from the design prompts alone. Without it, the same replies score 12 of 20. Both public demo prompts behaved as intended. This measurement does not
  check whether a verified chart shows what the request asked for. At least 4 of the 14 verified
  charts use a different aggregation or chart type than the request.
- **Design set (tuning only).** On the 48 design prompts, 20 of 24 simple requests verified and the verifier
  blocked 24 of 24 complicated requests. 10 of the 24 simple charts showed what the request asked
  for. The other 10 verified charts showed real values of a different quantity.
- **Browser demo.** The test used the real model in Open WebUI with `data/sales.csv` attached. The
  simple banner prompt showed a bar chart and the pass message in 5 of 5 recorded runs. The
  elaborate dashboard prompt showed the failure message and no image in 5 of 5 runs. The records are in
  `.agent/measurements/m10u3/`.
- **Japanese browser demo.** The same setup recorded 5 runs of each Japanese banner prompt. Two
  prompts ask for one simple chart each: a bar chart over `data/sales.csv` and a line chart over
  `data/clinic_ja.csv`. Each showed a chart and the pass message in 5 of 5 runs. The clinic chart
  drew its Japanese title and labels. The text below each chart was in Japanese. The two Japanese
  dashboard prompts showed the failure message and no image in 5 of 5 runs each, with a Japanese
  status line. The records are in `.agent/measurements/m17u4/`. The project picked each prompt
  from faithful translations by one model reply each. `.agent/measurements/m17u3_phrasings.json`
  lists every phrasing that the project tried. This result is not a success rate for Japanese
  requests.
- **Stub model.** With `--stub`, the simple prompt showed a chart and the pass message. The
  elaborate prompt showed the failure message and no image. One recorded run of each. The four
  Japanese prompts behaved the same way in one recorded run of each.

## Install

You need Linux, [uv](https://docs.astral.sh/uv/) and git. The real model needs an NVIDIA GPU with
CUDA 12.6 support. The browser demo needs Chromium or Chrome.

1. Install the locked Python 3.13 environment.

   ```sh
   uv sync --locked
   ```

2. For the browser demo, set up the Open WebUI environment. [webui/README.md](webui/README.md)
   gives the one-time steps.
3. For the real model, set up the model runtime. [model_backend/runtime/README.md](model_backend/runtime/README.md)
   gives the steps and the model download.

## Run

- Run the full quality gate. The gate runs formatting, lint, type, test, dependency audit, secret,
  workflow and shell checks.

  ```sh
  bash tools/gate.sh
  ```

- Start the demo with the stub model. No GPU is necessary.

  ```sh
  webui/launch.sh --stub
  ```

- Start the demo with the real model.

  ```sh
  webui/launch.sh
  ```

  The launcher prints a banner with the address, the login and the prompts to try: two in English
  and four in Japanese. Attach the CSV file that the banner shows for the prompt to a new chat.
  Send the prompt. Press `Ctrl-C` to stop.

- Recompute the held-out score from the committed capture. The command writes nothing unless you add
  `--write`.

  ```sh
  uv run --locked python -m capture score corpus/python/captures/m10-heldout
  ```

## Configure

- **An existing Open WebUI instance.** Follow [docs/admin/README.md](docs/admin/README.md).
- **The paste-in files.** Do not edit them. Change the source under `src/verifier/pysrc/` or
  `webui/paste_in/`. Then regenerate both files:

  ```sh
  uv run --locked python tools/generate_paste_in.py
  ```

- **The demo launcher.** Use `--fresh` to delete the saved demo instance. [webui/README.md](webui/README.md)
  lists the environment variables, for example the ports and the admin login.

## Repository layout

```text
.
├── paste-in/              the two generated Open WebUI files (the deliverable)
├── docs/admin/            administrator guide (English, Japanese) and model system prompts
├── src/verifier/pysrc/    the verification core that the paste-in files embed
├── webui/                 paste-in sources, Open WebUI provisioning, launcher and stub model
│   └── demo-paste-in/     the demo's generated pair: production files with the demo's column rule
├── model_backend/         the local model server for the demo
├── capture/               model capture, statistics and the held-out scorer
├── corpus/python/         design, held-out and sentinel prompts, and committed captures
├── data/                  demo CSV files
├── tools/                 gate, positive controls, mutation driver and paste-in generator
├── tests/                 the test suite
├── src/verifier/          the JSON-spec verifier service (headless)
└── docs/json-spec.md      the JSON-spec service claim, trust spine and acceptance record
```

## License

This project uses the `Apache-2.0 WITH LLVM-exception` license. See [LICENSE](LICENSE).
