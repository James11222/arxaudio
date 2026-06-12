# arxaudio preferences
#
# Describe your research interests in plain English.
# The filter LLM reads this whole file when deciding whether to keep or
# discard each paper, so be as specific or as broad as you like.
# You can add extra sections, URLs, or notes — the LLM reads free text.
#
# Tips:
#   - Be concrete about methods, surveys, and datasets you care about.
#   - The "Not interested in:" section helps the model focus the filter.
#   - Changes here take effect on the next pipeline run (no code changes needed).
# =============================================================================

## Research interests

I am a cosmologist and observational astrophysicist interested in the
large-scale structure of the Universe and the tools used to map it.

**Core topics I want to follow closely:**
- Cosmological large-scale structure: power spectra, correlation functions,
  baryon acoustic oscillations (BAO), redshift-space distortions (RSD)
- Weak gravitational lensing: cosmic shear, shear calibration, shape
  measurement, intrinsic alignments
- Cosmic voids: void statistics, void lensing, void profiles, voids as
  cosmological probes
- Galaxy clustering and halo occupation distributions (HOD)
- Photometric and spectroscopic survey science, especially:
    - LSST / Rubin Observatory (DESC science, DESC pipelines, image
      simulations, photo-z)
    - DESI (spectroscopic clustering, ELG/LRG/QSO target selection, full-shape
      fits)
    - Euclid, DES, HSC (where results connect to the above)
- Photo-z estimation methods: machine learning photo-z, template fitting,
  redshift calibration with cross-correlations
- Field-level inference, simulation-based inference (SBI / likelihood-free),
  and neural posterior estimation applied to cosmological data
- Emulators and surrogate models for large-scale structure (e.g., EuclidEmulator,
  CosmicEmu, neural emulators for Pk)
- Blinding strategies and unblinding procedures for cosmological analyses
- Covariance matrix estimation: analytic, jackknife, simulations

**Methods and tools I care about:**
- Fisher forecasting and MCMC posterior analysis
- N-body and hydrodynamical simulations used as cosmological benchmarks
  (IllustrisTNG, FLAMINGO, AbacusSummit, etc.)
- Machine learning applied to cosmology: CNNs/ViTs on maps, graph networks
  on halo catalogues, transformers for field summaries

## Not interested in

Please discard papers primarily focused on:
- Pure high-energy particle theory or quantum field theory with no
  observational/cosmological connection
- Exoplanet atmospheres, habitability, and astrobiology
- Solar physics, heliosphere, space weather
- Stellar evolution, asteroseismology, or stellar populations (unless
  directly relevant to photometric calibration of a survey I listed above)
- Gravitational wave astrophysics (mergers, ringdown) unless the paper is
  specifically about using GW standard sirens for H0 cosmology
- Radio transients, fast radio bursts (FRBs) unless used as cosmological
  probes of the intergalactic medium
- Instrumentation and telescope design papers with no science results
