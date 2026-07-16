Randy —

A few things that'll make the GPU run much faster. If you're not already using these:

**1. Use run_pipeline.sh, not individual scripts.** The order matters — quality assessment MUST run before OCR so the engine router sees real image_quality signals. Otherwise every page routes on "unknown" and you miss the faster engine.

```bash
./run_pipeline.sh /path/to/archive/ /path/to/work/ --heavy
```

**2. The `--heavy` flag.** This enables GPU batch mode — pages process back-to-back keeping the Blackwell saturated. Without it, OCR runs single-page. Set `TOWN_RECORDS_HEAVY=1` in your environment, or pass `--heavy` to run_pipeline.sh.

**3. Docling auto-detects CUDA now.** No device configuration needed — it uses AcceleratorDevice.AUTO.

**4. OCR is resumable.** If it crashes or you Ctrl-C, just re-run. Already-processed pages get skipped.

Nothing else to configure. If it's still slow after those, let us know what you're seeing.

— Vex (via Aldous)
