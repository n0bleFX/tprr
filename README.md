# TPRR Index — MVP

Noble Argon's Token Price Reference Rate (TPRR) methodology validation MVP.
An institutional-grade benchmark for AI inference token prices, validated on ~480 days
of synthetic contributor data plus OpenRouter reference data.

The only question this repo exists to answer: does the dual-weighted formula
(exponential median-distance weighting at λ=3 × three-tier volume hierarchy, over a
TWAP daily fixing) produce a stable, manipulation-resistant index on realistic data?

## Quickstart

```bash
uv sync
uv run pytest
```

Canonical methodology: [docs/tprr_methodology.md](docs/tprr_methodology.md).
