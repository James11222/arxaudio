# math_replacements.md — LaTeX / math / unit → spoken-text reference

This file is the single source of truth for turning hard-to-pronounce math and
LaTeX notation into plain spoken English for a text-to-speech engine. It is
parsed by `src/arxaudio/process.py` (`apply_replacements`) and is also used to
prime the LLM with few-shot examples.

**You can extend the pipeline by editing this markdown only — no code changes.**

---

## File format (read before editing)

There are two kinds of replacement, in two sections:

1. **Literal replacements** — plain substring swaps. Applied case-sensitively as
   written, after the regex section. Use these for simple symbol names.
2. **Regex patterns** — Python regular expressions for structured notation
   (exponents, subscripts, fractions, units with word boundaries, etc.).

Both sections are markdown tables. The parser keys off the table **header row**:

- A table whose header contains the word `Regex` (case-insensitive) is parsed as
  the **regex** table.
- Any other table under the "Literal replacements" heading is parsed as the
  **literal** table.

### Column contract

**Literal table** — exactly two meaningful columns:

| Match | Spoken |
|-------|--------|
| `\alpha` | alpha |

- `Match` is the literal text to find (backticks around it are stripped).
- `Spoken` is the replacement text.

**Regex table** — exactly three meaningful columns:

| Regex | Replacement | Example |
|-------|-------------|---------|
| `(\d+)\^(\d+)` | \1 to the \2 | `10^4` -> ten to the four |

- `Regex` is a Python regex. Backreferences in `Replacement` use `\1`, `\2`, ...
- `Replacement` is the `re.sub` replacement string.
- `Example` is documentation only; the parser ignores it.
- Backticks around any cell are stripped. Write a literal pipe as `\|`.

### Ordering rule (IMPORTANT)

Within each table, rows are applied **top to bottom**, so put the
**longest / most specific** patterns first and the general fallbacks last.
`process.py` preserves table order; do not rely on it re-sorting for you.

### Things deliberately left alone

- `z` (redshift) — reads fine as "z".
- Bare numbers, ordinary words, and already-spoken text.

---

## 1. Literal replacements

These are simple symbol-name swaps. Most carry an optional leading backslash so
they match whether or not the LaTeX command survived earlier passes.

### Greek letters (lowercase)

| Match | Spoken |
|-------|--------|
| `\alpha` | alpha |
| `\beta` | beta |
| `\gamma` | gamma |
| `\delta` | delta |
| `\epsilon` | epsilon |
| `\varepsilon` | epsilon |
| `\zeta` | zeta |
| `\eta` | eta |
| `\theta` | theta |
| `\vartheta` | theta |
| `\iota` | iota |
| `\kappa` | kappa |
| `\lambda` | lambda |
| `\mu` | mu |
| `\nu` | nu |
| `\xi` | xi |
| `\omicron` | omicron |
| `\pi` | pi |
| `\varpi` | pi |
| `\rho` | rho |
| `\varrho` | rho |
| `\sigma` | sigma |
| `\varsigma` | sigma |
| `\tau` | tau |
| `\upsilon` | upsilon |
| `\phi` | phi |
| `\varphi` | phi |
| `\chi` | kai |
| `\psi` | psi |
| `\omega` | omega |

### Greek letters (uppercase)

| Match | Spoken |
|-------|--------|
| `\Gamma` | capital gamma |
| `\Delta` | delta |
| `\Theta` | capital theta |
| `\Lambda` | lambda |
| `\Xi` | capital xi |
| `\Pi` | capital pi |
| `\Sigma` | capital sigma |
| `\Upsilon` | capital upsilon |
| `\Phi` | capital phi |
| `\Psi` | capital psi |
| `\Omega` | omega |

### Unicode Greek letters (arXiv feed delivers these pre-converted)

| Match | Spoken |
|-------|--------|
| `α` | alpha |
| `β` | beta |
| `γ` | gamma |
| `δ` | delta |
| `ε` | epsilon |
| `ζ` | zeta |
| `η` | eta |
| `θ` | theta |
| `ι` | iota |
| `κ` | kappa |
| `λ` | lambda |
| `μ` | mu |
| `ν` | nu |
| `ξ` | xi |
| `π` | pi |
| `ρ` | rho |
| `σ` | sigma |
| `τ` | tau |
| `υ` | upsilon |
| `φ` | phi |
| `χ` | kai |
| `ψ` | psi |
| `ω` | omega |
| `Γ` | capital gamma |
| `Δ` | delta |
| `Θ` | capital theta |
| `Λ` | lambda |
| `Ξ` | capital xi |
| `Π` | capital pi |
| `Σ` | capital sigma |
| `Υ` | capital upsilon |
| `Φ` | capital phi |
| `Ψ` | capital psi |
| `Ω` | omega |

### Comparison, set, and logic operators

| Match | Spoken |
|-------|--------|
| `\geq` | ` greater than or equal to ` |
| `\geqslant` | ` greater than or equal to ` |
| `\ge` | ` greater than or equal to ` |
| `\gtrsim` | ` greater than or approximately ` |
| `\leq` | ` less than or equal to ` |
| `\leqslant` | ` less than or equal to ` |
| `\le` | ` less than or equal to ` |
| `\lesssim` | ` less than or approximately ` |
| `\langle` | ` the average of ` |
| `\rangle` | ` ` |
| `\gg` | ` much greater than ` |
| `\ll` | ` much less than ` |
| `\neq` | ` not equal to ` |
| `\equiv` | ` is equivalent to ` |
| `\approx` | ` approximately equal to ` |
| `\simeq` | ` approximately equal to ` |
| `\sim` | ` approximately ` |
| `\propto` | ` proportional to ` |
| `\in` | is an element of |
| `\notin` | is not an element of |
| `\subset` | is a subset of |
| `\subseteq` | is a subset of or equal to |
| `\supset` | is a superset of |
| `\cup` | union |
| `\cap` | intersection |
| `\emptyset` | the empty set |
| `\forall` | for all |
| `\exists` | there exists |
| `\implies` | implies |
| `\rightarrow` | goes to |
| `\to` | to |
| `\leftarrow` | from |
| `\mapsto` | maps to |
| `\land` | and |
| `\lor` | or |
| `\neg` | not |

### Arithmetic and calculus

| Match | Spoken |
|-------|--------|
| `\pm` | ` plus or minus ` |
| `\mp` | ` minus or plus ` |
| `\times` | ` times ` |
| `\cdot` | ` times ` |
| `\div` | ` divided by ` |
| `\infty` | infinity |
| `\partial` | partial |
| `\nabla` | del |
| `\sum` | the sum of |
| `\prod` | the product of |
| `\int` | the integral of |
| `\oint` | the contour integral of |
| `\lim` | the limit of |
| `\%` | ` percent` |
| `\deg` | degrees |
| `\circ` | degrees |
| `\prime` | prime |
| `\dagger` | dagger |
| `\odot` | sun |
| `\oplus` | earth |

### Astrophysics constants and named quantities

| Match | Spoken |
|-------|--------|
| `\Lambda CDM` | Lambda C D M |
| `\LambdaCDM` | Lambda C D M |
| `LambdaCDM` | Lambda C D M |
| `Lambda CDM` | Lambda C D M |
| `lambdaCDM` | Lambda C D M |
| `LCDM` | Lambda C D M |
| `phiCDM` | phi C D M |
| `\chi^2` | kai squared |
| `\sigma_8` | sigma eight |
| `M_\odot` | solar masses |
| `M_{\odot}` | solar masses |
| `M_\sun` | solar masses |
| `M_{sun}` | solar masses |
| `Msun` | solar masses |
| `M_sun` | solar masses |
| `M_star` | stellar mass |
| `M_*` | stellar mass |
| `M_BH` | black hole mass |
| `M_{BH}` | black hole mass |
| `f_esc` | escape fraction |
| `f_{esc}` | escape fraction |
| `L_bol` | bolometric luminosity |
| `L_{bol}` | bolometric luminosity |
| `L_\odot` | solar luminosities |
| `L_{\odot}` | solar luminosities |
| `Lsun` | solar luminosities |
| `L_sun` | solar luminosities |
| `R_\odot` | solar radii |
| `R_sun` | solar radii |
| `H_0` | H naught |
| `H_{0}` | H naught |
| `\msun` | solar masses |
| `\lsun` | solar luminosities |
| `\kms` | kilometers per second |
| `Ly-alpha` | Lyman alpha |
| `Ly alpha` | Lyman alpha |
| `Lyα` | Lyman alpha |
| `Ly-beta` | Lyman beta |
| `Ly beta` | Lyman beta |
| `Lyβ` | Lyman beta |
| `chi squared` | kai squared |
| `kai to the power of 2` | kai squared |
| `deltakai to the power of 2` | delta kai squared |
| `muG` | microgauss |
| `muT` | microtesla |
| `muJy` | microjanskys |
| `fsigma_8` | f sigma eight |
| `deltaomega_m` | delta omega sub m |
| `deltaomega sub m` | delta omega sub m |
| `alphasub` | alpha sub |
| `deltasub` | delta sub |
| `tausub` | tau sub |
| `sigmasub` | sigma sub |
| `omegasub` | omega sub |
| `betasub` | beta sub |
| `zetasub` | zeta sub |
| `etasub` | eta sub |
| `gammasub` | gamma sub |
| `lambdasub` | lambda sub |
| `musub` | mu sub |
| `nusub` | nu sub |
| `xisub` | xi sub |
| `rhosub` | rho sub |
| `thetasub` | theta sub |
| `phisub` | phi sub |
| `chisub` | chi sub |
| `psisub` | psi sub |

---

## 2. Regex patterns

Applied **before** the literal table, top to bottom. Most-specific first.
The parser reads the `Regex` and `Replacement` columns; `Example` is docs only.

### Inline-math and macro cleanup (run very early)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `\\hat\{([^{}]*)\}` | \1 hat | `\hat{x}` -> x hat |
| `\\tilde\{([^{}]*)\}` | \1 tilde | `\tilde{x}` -> x tilde |
| `\\bar\{([^{}]*)\}` | \1 bar | `\bar{x}` -> x bar |
| `\\vec\{([^{}]*)\}` | \1 vector | `\vec{x}` -> x vector |
| `\\texttt\{([^{}]*)\}` | \1 | `\texttt{TUNER}` -> TUNER |
| `\\textsc\{([^{}]*)\}` | \1 | `\textsc{i}` -> i |
| `\\textrm\{([^{}]*)\}` | \1 | `\textrm{abc}` -> abc |
| `\\textit\{([^{}]*)\}` | \1 | `\textit{abc}` -> abc |
| `\\emph\{([^{}]*)\}` | \1 | `\emph{abc}` -> abc |
| `\\text\{([^{}]*)\}` | \1 | `\text{abc}` -> abc |
| `\\mathrm\{([^{}]*)\}` | \1 | `\mathrm{Mpc}` -> Mpc |
| `\\mathbf\{([^{}]*)\}` | \1 | `\mathbf{x}` -> x |
| `\\mathcal\{([^{}]*)\}` | \1 | `\mathcal{L}` -> L |
| `\\rm\s+` | ` ` | `\rm Mpc` -> ` Mpc` (keep the space, don't glue) |
| `\\_` | ` ` | `\_` (escaped underscore) -> space |
| `~` | ` ` | `~` (non-breaking space) -> space |
| `\\star\b` | star | `M_\star` -> M sub star (stellar) |
| `\\[,;:!]` | ` ` | `\,` (thin space) -> space |
| `\\\s` | ` ` | `\ ` (forced space) -> space |
| `\$([^$]*)\$` | \1 | `$x$` -> x (strip math delimiters early) |
| `\$` |  | leftover `$` -> removed |

### Lyman-alpha and hydrogen species (must precede generic subscript rules)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `Ly[\s-]*\\?alpha\b` | Lyman alpha | `Ly-alpha` -> Lyman alpha |
| `Ly[\s-]*α` | Lyman alpha | `Lyα` -> Lyman alpha |
| `\bHII\b` | H two | `HII region` -> H two region |
| `\bHI\b` | H one | `HI profile` -> H one profile |
| `H_\{?2\}?(?!\s*O)` | molecular hydrogen | `H_2 cloud` -> molecular hydrogen cloud |

### Chemical abundance ratios (bracket notation)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `\[Fe/H\]` | the iron-to-hydrogen ratio | `[Fe/H]` -> the iron-to-hydrogen ratio |
| `\[Mg/Fe\]` | the magnesium-to-iron ratio | `[Mg/Fe]` -> the magnesium-to-iron ratio |
| `\[Si/Fe\]` | the silicon-to-iron ratio | `[Si/Fe]` -> the silicon-to-iron ratio |
| `\[Si/Mg\]` | the silicon-to-magnesium ratio | `[Si/Mg]` -> the silicon-to-magnesium ratio |
| `\[O/Fe\]` | the oxygen-to-iron ratio | `[O/Fe]` -> the oxygen-to-iron ratio |
| `\[C/Fe\]` | the carbon-to-iron ratio | `[C/Fe]` -> the carbon-to-iron ratio |
| `\[N/Fe\]` | the nitrogen-to-iron ratio | `[N/Fe]` -> the nitrogen-to-iron ratio |
| `\[Ca/Fe\]` | the calcium-to-iron ratio | `[Ca/Fe]` -> the calcium-to-iron ratio |
| `\[Ti/Fe\]` | the titanium-to-iron ratio | `[Ti/Fe]` -> the titanium-to-iron ratio |
| `\[alpha/Fe\]` | the alpha-to-iron ratio | `[alpha/Fe]` -> the alpha-to-iron ratio |
| `\[α/Fe\]` | the alpha-to-iron ratio | `[α/Fe]` -> the alpha-to-iron ratio |
| `\[([A-Z][a-z]?)/([A-Z][a-z]?)\]` | the \1-to-\2 ratio | `[X/Y]` -> the X-to-Y ratio |

### Named astrophysics constants (must precede generic exponent/subscript rules)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `\\Lambda\s*\\?CDM` | Lambda C D M | `\Lambda CDM` -> Lambda C D M |
| `\bLambda\s*CDM\b` | Lambda C D M | `LambdaCDM` -> Lambda C D M |
| `\blambda\s*CDM\b` | Lambda C D M | `lambdaCDM` -> Lambda C D M |
| `\b[Pp]hi\s*CDM\b` | phi C D M | `phiCDM` -> phi C D M |
| `f\\?_?\{?\\?sigma_?\{?8\}?\}?` | f sigma eight | `f\sigma_8` or `fsigma_8` -> f sigma eight |
| `fσ_?\{?8\}?` | f sigma eight | Unicode `fσ_8` -> f sigma eight |
| `\\?[Dd]elta\\?chi\^\{?2\}?` | delta kai squared | `\Delta\chi^2` -> delta kai squared |
| `Δχ\^2` | delta kai squared | Unicode `Δχ^2` -> delta kai squared |
| `χ\^2` | kai squared | Unicode `χ^2` -> kai squared |
| `\\chi\^2` | kai squared | `\chi^2` -> kai squared |
| `\\chi\^\{2\}` | kai squared | `\chi^{2}` -> kai squared |
| `\bchi[\s-]*squared\b` | kai squared | `chi squared` -> kai squared (TTS fix) |
| `\\Delta\s*\\Omega_?\{?m\}?` | delta omega sub m | `\Delta\Omega_m` -> delta omega sub m |
| `ΔΩ_?\{?m\}?` | delta omega sub m | Unicode `ΔΩ_m` -> delta omega sub m |
| `\\cos\s*θ` | the cosine of theta | `\cosθ` -> the cosine of theta |
| `\\cos\s*\\theta` | the cosine of theta | `\cos\theta` -> the cosine of theta |
| `\\sigma_8\b` | sigma eight | `\sigma_8` -> sigma eight |
| `\\sigma_\{8\}` | sigma eight | `\sigma_{8}` -> sigma eight |
| `\bsigma_8\b` | sigma eight | bare `sigma_8` -> sigma eight |
| `\bomega_m\b` | omega sub m | bare `omega_m` -> omega sub m |
| `H_0\b` | H naught | `H_0` -> H naught |
| `H_\{0\}` | H naught | `H_{0}` -> H naught |
| `M_\{?\\?star\}?` | stellar mass | `M_\star` or `M_star` -> stellar mass |
| `M_\{?\*\}?` | stellar mass | `M_*` -> stellar mass |
| `M_\{?\s*BH\s*\}?` | black hole mass | `M_BH` or `M_{BH}` -> black hole mass |
| `f_\{?esc\}?` | escape fraction | `f_esc` or `f_{esc}` -> escape fraction |
| `L_\{?bol\}?` | bolometric luminosity | `L_bol` or `L_{bol}` -> bolometric luminosity |
| `M_\{\\odot\}` | solar masses | `M_{\odot}` -> solar masses |
| `M_\{\\sun\}` | solar masses | `M_{\sun}` -> solar masses |
| `L_\{\\odot\}` | solar luminosities | `L_{\odot}` -> solar luminosities |
| `R_\{\\odot\}` | solar radii | `R_{\odot}` -> solar radii |
| `f_\{?NL\}?\^\{?loc(?:al)?\}?` | f N L local | `f_{NL}^{loc}` -> f N L local |
| `f_\{?NL\}?` | f N L | `f_NL` or `f_{NL}` -> f N L |

### Fractions, ratios, and roots

| Regex | Replacement | Example |
|-------|-------------|---------|
| `\\frac\{([^{}]+)\}\{([^{}]+)\}` | \1 over \2 | `\frac{a}{b}` -> a over b |
| `\\sqrt\[([^\]]+)\]\{([^{}]+)\}` | the \1 root of \2 | `\sqrt[3]{x}` -> the 3 root of x |
| `\\sqrt\{([^{}]+)\}` | the square root of \1 | `\sqrt{x}` -> the square root of x |
| `(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)` | \1 over \2 | `6.2 / 7.7` -> 6.2 over 7.7 |
| `1\s*/\s*([A-Za-z])\b` | one over \1 | `1/x` -> one over x |

### Functions

| Regex | Replacement | Example |
|-------|-------------|---------|
| `\\log_\{?(\w+)\}?\s*\(([^()]+)\)` | the log base \1 of \2 | `\log_2(x)` -> the log base 2 of x |
| `\\log\s*\(([^()]+)\)` | the logarithm of \1 | `\log(b)` -> the logarithm of b |
| `\\ln\s*\(([^()]+)\)` | the natural log of \1 | `\ln(x)` -> the natural log of x |
| `\\exp\s*\(([^()]+)\)` | the exponential of \1 | `\exp(t)` -> the exponential of t |
| `\\sin\s*\(([^()]+)\)` | the sine of \1 | `\sin(w)` -> the sine of w |
| `\\cos\s*\(([^()]+)\)` | the cosine of \1 | `\cos(z)` -> the cosine of z |
| `\\tan\s*\(([^()]+)\)` | the tangent of \1 | `\tan(y)` -> the tangent of y |
| `\\cot\s*\(([^()]+)\)` | the cotangent of \1 | `\cot(x)` -> the cotangent of x |
| `\\log\b` | log | bare `\log` without parens |
| `\\ln\b` | log | bare `\ln` without parens |
| `\\exp\b` | exp | bare `\exp` without parens |
| `\\sin\b` | sin | bare `\sin` without parens |
| `\\cos\b` | cos | bare `\cos` without parens |
| `\\tan\b` | tan | bare `\tan` without parens |

### Separate a number glued to a unit (run before the unit rules below)

LaTeX often glues a value to its unit (`3pc`, `3.4Myr`, `2000km`) with no space,
which then defeats the `\b…\b` word-boundary unit rules further down. Insert a
single space between the trailing digit and a *known* unit token only — so survey
names and identifiers like `2MASS`, `6dF`, or `3D` are left untouched.

| Regex | Replacement | Example |
|-------|-------------|---------|
| `(\d)\s*(?=(?:Mpc\|kpc\|Gpc\|pc\|km\|Gyr\|Myr\|kyr\|yr\|AU\|TeV\|GeV\|MeV\|keV\|eV\|GHz\|MHz\|kHz\|Hz\|arcsec\|arcmin\|mas\|mag\|dex)\b)` | `\1 ` | `3.4Myr` -> 3.4 Myr |

### Units with exponents (cubed/squared first, then bare; word boundaries)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `\bkm\s+s\s*(?:to the\s*)?-1\s+(?:megaparsecs\|Mpc)\s*(?:to the\s*)?-1` | kilometers per second per megaparsec | `km s to the -1 Mpc to the -1` -> fix |
| `\bkm\s+s\^\{?-1\}?\s*Mpc\^\{?-1\}?` | kilometers per second per megaparsec | `km s^{-1} Mpc^{-1}` -> kilometers per second per megaparsec |
| `\brad\s+m\^\{?-2\}?` | radians per square meter | `rad m^{-2}` -> radians per square meter |
| `\brad\s+m\s*(?:to the\s*)?-2` | radians per square meter | `rad m to the -2` -> radians per square meter |
| `\bs\^\{?-1\}?\s*Mpc\^\{?-1\}?` | per second per megaparsec | `s^{-1} Mpc^{-1}` -> per second per megaparsec |
| `\bs\^\{?-1\}?` | per second | `s^{-1}` -> per second |
| `\bMpc\^?\{?3\}?\b` | megaparsecs cubed | `Mpc^3` -> megaparsecs cubed |
| `\bMpc\^?\{?2\}?\b` | megaparsecs squared | `Mpc^2` -> megaparsecs squared |
| `\bMpc\^\{?-1\}?` | per megaparsec | `Mpc^{-1}` -> per megaparsec |
| `\bkpc\^?\{?3\}?\b` | kiloparsecs cubed | `kpc^3` -> kiloparsecs cubed |
| `\bkpc\^?\{?2\}?\b` | kiloparsecs squared | `kpc^2` -> kiloparsecs squared |
| `\bpc\^?\{?3\}?\b` | parsecs cubed | `pc^3` -> parsecs cubed |
| `\bpc\^?\{?2\}?\b` | parsecs squared | `pc^2` -> parsecs squared |
| `\bcm\^?\{?-3\}?\b` | per cubic centimeter | `cm^-3` -> per cubic centimeter |
| `\bcm\^?\{?-2\}?\b` | per square centimeter | `cm^-2` -> per square centimeter |

### h-factor exponents (cosmology; e.g. h-1Mpc, h^-3 Mpc^3)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `\bh\^?\{?-3\}?\s*Mpc` | h to the minus three megaparsecs | `h^-3 Mpc` -> h to the minus three megaparsecs |
| `\bh\^?\{?-1\}?\s*Mpc` | h to the minus one megaparsecs | `h-1Mpc` -> h to the minus one megaparsecs |
| `\bh\^?\{?-3\}?\s*kpc` | h to the minus three kiloparsecs | `h^-3 kpc` -> h to the minus three kiloparsecs |
| `\bh\^?\{?-1\}?\s*kpc` | h to the minus one kiloparsecs | `h-1kpc` -> h to the minus one kiloparsecs |
| `\bh\^\{?-(\d+)\}?` | h to the minus \1 | `h^{-3}` -> h to the minus 3 |
| `\bh-(\d+)\b` | h to the minus \1 | `h-1` -> h to the minus 1 |

### Bare astrophysics units (word boundaries; longest first)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `\bkm\s*/\s*s\s*/\s*Mpc\b` | kilometers per second per megaparsec | `km/s/Mpc` -> kilometers per second per megaparsec |
| `\bMpc\b` | megaparsecs | `Mpc` -> megaparsecs |
| `\bkpc\b` | kiloparsecs | `kpc` -> kiloparsecs |
| `\bGpc\b` | gigaparsecs | `Gpc` -> gigaparsecs |
| `\bpc\b` | parsecs | `pc` -> parsecs |
| `\bkm\s*/\s*s\b` | kilometers per second | `km/s` -> kilometers per second |
| `\bm\s*/\s*s\b` | meters per second | `m/s` -> meters per second |
| `\berg\s*/\s*s\b` | ergs per second | `erg/s` -> ergs per second |
| `\bGyr\b` | gigayears | `Gyr` -> gigayears |
| `\bMyr\b` | megayears | `Myr` -> megayears |
| `\bkyr\b` | kiloyears | `kyr` -> kiloyears |
| `\byr\b` | years | `yr` -> years |
| `\bAU\b` | astronomical units | `AU` -> astronomical units |
| `\bTeV\b` | tera electron volts | `TeV` -> tera electron volts |
| `\bGeV\b` | giga electron volts | `GeV` -> giga electron volts |
| `\bMeV\b` | mega electron volts | `MeV` -> mega electron volts |
| `\bkeV\b` | kilo electron volts | `keV` -> kilo electron volts |
| `\beV\b` | electron volts | `eV` -> electron volts |
| `\bGHz\b` | gigahertz | `GHz` -> gigahertz |
| `\bMHz\b` | megahertz | `MHz` -> megahertz |
| `\bkHz\b` | kilohertz | `kHz` -> kilohertz |
| `\bHz\b` | hertz | `Hz` -> hertz |
| `\barcsec\b` | arcseconds | `arcsec` -> arcseconds |
| `\barcmin\b` | arcminutes | `arcmin` -> arcminutes |
| `\bmas\b` | milliarcseconds | `mas` -> milliarcseconds |
| `\bmag\b` | magnitudes | `mag` -> magnitudes |
| `\bdex\b` | dex | `dex` -> dex |

### Powers of ten and scientific notation (before generic exponent rule)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `(\d+(?:\.\d+)?)\s*[xX]\s*10\^\{?(-?\d+)\}?` | \1 times ten to the \2 | `3.3x10^5` -> 3.3 times ten to the 5 |
| `\b10\^\{?(-?\d+)\}?` | ten to the \1 | `10^4` -> ten to the 4 |

### Asymmetric error bars and ranges (before generic subscript/superscript)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `(\d+(?:\.\d+)?)\s*_\{?\s*-(\d+(?:\.\d+)?)\s*\}?\s*\^\{?\s*\+(\d+(?:\.\d+)?)\s*\}?` | \1 plus \3 minus \2 | `67.55_{-0.46}^{+0.53}` -> 67.55 plus 0.53 minus 0.46 |
| `(\d+(?:\.\d+)?)\s*\^\{?\s*\+(\d+(?:\.\d+)?)\s*\}?\s*_\{?\s*-(\d+(?:\.\d+)?)\s*\}?` | \1 plus \2 minus \3 | `0.80^{+0.01}_{-0.01}` -> 0.80 plus 0.01 minus 0.01 |

### Dashes and ranges (em-dash, en-dash, hyphen-as-range)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `(\d+(?:\.\d+)?)\s*--\s*(\d+(?:\.\d+)?)` | \1 to \2 | `10--20` -> 10 to 20 |
| `—` | to | em-dash → "to" |
| `–` | to | en-dash → "to" |

### Significance (number-sigma patterns)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `(\d+(?:\.\d+)?)\s*\\?sigma\b` | \1 sigma | `3.5\sigma` -> 3.5 sigma |
| `(\d+(?:\.\d+)?)sigma\b` | \1 sigma | `3.5sigma` -> 3.5 sigma |

### Generic subscripts and superscripts (most-nested first)

| Regex | Replacement | Example |
|-------|-------------|---------|
| `([A-Za-z])_\{([^{}]+)\}\^\{?(-?\w+)\}?` | \1 sub \2 to the \3 | `x_{i,j}^k` -> x sub i,j to the k |
| `([A-Za-z])_([A-Za-z0-9])\^\{?(-?\w+)\}?` | \1 sub \2 to the \3 | `x_i^2` -> x sub i to the 2 |
| `([A-Za-z])\^2\b` | \1 squared | `x^2` -> x squared |
| `([A-Za-z])\^3\b` | \1 cubed | `x^3` -> x cubed |
| `([A-Za-z])\^\{2\}` | \1 squared | `x^{2}` -> x squared |
| `([A-Za-z])\^\{3\}` | \1 cubed | `x^{3}` -> x cubed |
| `([A-Za-z])\^\{(-?\w+)\}` | \1 to the \2 | `x^{k}` -> x to the k |
| `([A-Za-z])\^(-?\w+)` | \1 to the \2 | `x^k` -> x to the k |
| `(\d+(?:\.\d+)?)\^\{([^{}]+)\}` | \1 to the \2 | `1.8^{+1.0}` -> 1.8 to the +1.0 |
| `(\d+(?:\.\d+)?)\^(-?\w+)` | \1 to the \2 | `1.8^2` -> 1.8 to the 2 |
| `([A-Za-z])_\{([^{}]+)\}` | \1 sub \2 | `x_{i,j}` -> x sub i,j |
| `([A-Za-z])_([A-Za-z0-9])` | \1 sub \2 | `x_i` -> x sub i |
| `\)_\{([^{}]+)\}` | ) sub \1 | `)_{C}` -> ) sub C |
| `\)_([A-Za-z0-9])` | ) sub \1 | `)_C` -> ) sub C |
| `_\{([^{}]+)\}` |  sub \1 | `_{i,j}` -> sub i,j (no leading letter; leading space prevents glue) |

### Symbol cleanup

| Regex | Replacement | Example |
|-------|-------------|---------|
| `(\d)\s*%` | \1 percent | `5%` -> 5 percent |
| `(\d)percent` | \1 percent | `80percent` -> 80 percent (glued) |
| `(alpha\|beta\|gamma\|delta\|epsilon\|zeta\|eta\|theta\|kappa\|lambda\|mu\|nu\|xi\|pi\|rho\|sigma\|tau\|phi\|chi\|psi\|omega)sub\b` | \1 sub | `alphasub CO` -> alpha sub CO (space recovery after Unicode Greek subscript) |
| `([A-Za-z0-9])\s*/\s*([A-Za-z])` | \1 per \2 | `solar masses/h` -> solar masses per h |
| `([A-Za-z0-9])\s*<\s*([A-Za-z0-9])` | \1 less than \2 | `chi squared < 1` -> chi squared less than 1 |
| `([A-Za-z0-9])\s*>\s*([A-Za-z0-9])` | \1 greater than \2 | `z > 2` -> z greater than 2 |
| `([A-Za-z0-9])\s*=\s*([A-Za-z0-9])` | \1 equals \2 | `n = 3` -> n equals 3 |
| `\\,` |  | `\,` (thin space) -> removed |
| `\\;` |  | `\;` -> removed |
| `\^\*` | ` star` | `A^*` -> A star (e.g. Sgr A*) |
| `\^` | ` to the power of ` | leftover `^` -> to the power of |
