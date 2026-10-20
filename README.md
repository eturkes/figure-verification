# figure-verification

figure-verification lets a language model draw charts in Open WebUI, and shows a chart only after a
separate verifier checks the finished figure. The model writes a Python program that draws the
chart. The user's browser runs that program unchanged, and the verifier reads the figure that
matplotlib drew. The chart appears only when every check passes. Otherwise the chat shows `Figure
verification failed, no image produced`, and a status line above that message states the reason.
Each chart reply also has a `Show checks` list of every check and its result. Click a check to open
it. It shows what the check does, its related program lines or a note, and why it failed. The failed
check also marks the program line that drew the failed part. Each check links to its section of the
[short guide to the checks](docs/checks.md), and the guide links to the full [verification
reference](docs/verification.md).

## What this repository delivers

- **Two files to paste into Open WebUI.** `paste-in/figure_verification_tool.py` and
  `paste-in/figure_verification_filter.py` contain the complete verifier. They need only the Python
  standard library and what Open WebUI 0.11.3 already contains. They run on the Python 3.11 of the
  official Open WebUI image. They make no network calls.
- **An administrator guide in English and Japanese.** Read
  [docs/admin/README.md](docs/admin/README.md) or [docs/admin/README.ja.md](docs/admin/README.ja.md)
  to install the two files.
- **A demo harness.** One command starts a local Open WebUI with a local model or a stub model. The
  harness also holds the measurement tools and the test suite.

## What "verified" means

A chart passes when all of these statements are true:

1. **Integrity.** Every part of the figure belongs to a closed set of chart parts that the verifier
   checks. These are lines, points, bars, histograms, pies, filled areas, reference lines and text.
   Every part obeys a closed set of rules. For example, bars start at zero, every axis runs in its
   normal direction and no value lies outside the axis limits.
2. **Provenance.** The user can attach a CSV file or type numbers in the request. Every drawn value
   then comes from that data: a value of one column, one summary per group of one column, or a typed
   number. It can also be one admitted computation of that data, such as a running total or a ratio
   of two columns. A chart without such data passes on integrity alone, and the reply says so. The
   request is every message that the user wrote in the current branch of the chat, so a follow-up
   such as `Make the bars red` keeps the columns and numbers of the earlier messages.
3. **Interpretation.** The reply states in plain words where each drawn value comes from. If the
   user's last message contains Japanese kana, that text is in Japanese.

Every decision follows a fixed rule. The verifier uses no model. A pass does not mean that the chart
answers the question. The chart can show a different measure or grouping than the user wanted.

The verifier trusts the browser, the Pyodide runtime, matplotlib, the Japanese font that Open WebUI
contains and the pixels. It does not check them. It also trusts the chart program to be honest: the
program runs before any check, in the same runtime as the verifier's reader. The reference lists
what the verifier does not check.

## Measured results

- **Rule corpus.** For every rule, at least one misleading program blocks with that rule's reason
  and at least one honest twin passes. The corpus runs in the test suite on matplotlib 3.10.8. The
  same 237 cases also ran through the production wrapper in the Pyodide 314.0.3 bundle of Open WebUI
  0.11.3, with matplotlib 3.10.8. All 237 verdicts matched the expected verdict and the host
  verdict.
- **Stub model.** With `--stub`, the launcher's three honest prompts showed a chart and the pass
  message. The three misleading prompts showed the failure message with the expected reason and no
  image. One recorded run of each on Open WebUI 0.10.2, in headless Chromium 151; the records are in
  `.agent/measurements/m19u5/`. On Open WebUI 0.11.3, the M15, M16 and M17 replays repeat these
  outcomes.
- **Real model.** The demo model ran each launcher prompt 5 times. The host was an NVIDIA MX150
  with fp16 Qwen2.5-Coder-0.5B-Instruct, greedy decoding, Open WebUI 0.11.3 and headless Chromium
  151. All 15 honest runs showed a chart and the pass message. All 15 misleading runs drew the
  requested limits or the inverted axis and showed the failure message with the expected code. The
  records are in `.agent/measurements/q70/`. The record on Open WebUI 0.10.2, before prompt 6 named
  `plt.plot`, is in `.agent/measurements/m19u9/`.

The earlier verifier read the program text instead of the finished figure. Its measurements are in
`.agent/archive/` and do not apply to this verifier.

## Install

You need Linux, [uv](https://docs.astral.sh/uv/) and git. The real model needs an NVIDIA GPU with
CUDA 12.6 support. The browser demo needs Chromium or Chrome.

1. Install the locked Python 3.14 environment.

   ```sh
   uv sync --locked
   ```

2. For the browser demo, set up the Open WebUI environment. [webui/README.md](webui/README.md) gives
   the one-time steps.
3. For the real model, set up the model runtime.
   [model_backend/runtime/README.md](model_backend/runtime/README.md) gives the steps and the model
   download.

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

  The launcher prints a banner with the address, the login and six prompts to try. They are honest
  and misleading requests in English and in Japanese. Attach the CSV file that the banner shows for
  the prompt to a new chat. Send the prompt. Press `Ctrl-C` to stop.

## Configure

- **An existing Open WebUI instance.** Follow [docs/admin/README.md](docs/admin/README.md).
- **The paste-in files.** Do not edit them. Change the source under `src/verifier/figure/` or
  `webui/paste_in/`. Then regenerate the files:

  ```sh
  uv run --locked python tools/generate_paste_in.py
  ```

- **The demo launcher.** Use `--fresh` to delete the saved demo instance.
  [webui/README.md](webui/README.md) lists the environment variables, for example the ports and the
  admin login.

## Repository layout

```text
.
├── paste-in/              the two generated Open WebUI files (the deliverable)
├── docs/admin/            administrator guide (English, Japanese)
├── src/verifier/figure/   the figure reader and judge that the paste-in files embed
├── webui/                 paste-in sources, Open WebUI provisioning, launcher and stub model
│   └── demo-paste-in/     the demo's generated pair: production files with the demo's column rule
├── model_backend/         the local model server for the demo
├── data/                  demo CSV files
├── tools/                 gate, positive controls, mutation driver and paste-in generator
└── tests/                 the test suite
```

## License

This project uses the `Apache-2.0 WITH LLVM-exception` license. See [LICENSE](LICENSE).
