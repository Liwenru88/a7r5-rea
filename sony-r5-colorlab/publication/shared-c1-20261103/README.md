# No-expert shared C1 publication

Both workbenches now default to the chosen shared C1 standard. The color-training browser reads the default response identity from server bootstrap, avoiding a stale expert model for manual jobs. The fixed response model is included and SHA256 checked. Grid inference retains optional historical expert experiments, disabled by default.

Regression: 142 color-workbench tests (4 optional GPU/environment skips), 74 grid-calibrator tests, data integrity and both JavaScript syntax checks passed. CPU tensor prediction and gradients, calibration-inference parity and zero-grid identity are covered. No camera tests or new training were performed for publication. See verification.json.
