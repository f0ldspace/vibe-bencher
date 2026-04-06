# vibe-bencher

personal llm benchmarking tool. compare models head-to-head and track scores over time.

## getting started

if you use nix:

```bash
nix-shell
vb --help
```

otherwise install deps:

```bash
pip install rich click questionary matplotlib
```

then run:

```bash
python -m vibebencher --help
```

## usage

```bash
vb run                    # start a benchmark session
vb run --loop             # keep running sessions in a loop
vb stats                  # show elo rankings
vb history                # view past sessions
vb history --last 10      # last 10 sessions
vb history --model qwen   # filter by model
```

## setup

for openrouter you need an api key:

```bash
vb config openrouter-key YOUR_KEY
```

pick which models to benchmark:

```bash
vb defaults --provider ollama
vb defaults --provider openrouter
```

## export

```bash
vb export --format md --output rankings.md
vb export --format csv --output data.csv
vb export --format json --output data.json
vb export --format svg --output plot.svg
```

## how it works

runs benchmarks comparing multiple models, calculates elo scores, tracks wins and losses. data gets stored in sqlite.

works with ollama (local) and openrouter (api). pick whatever models you want, run sessions, see how they stack up.