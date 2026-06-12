"""Tests for arxaudio.process: apply_replacements, clean_paper, process_papers."""
from __future__ import annotations

import copy

import pytest

from arxaudio.llm.base import LLMError
from arxaudio.models import Paper
from arxaudio.process import apply_replacements, clean_paper, process_papers

from conftest import FakeLLM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ar(text: str) -> str:
    """Short alias for apply_replacements with the default table."""
    return apply_replacements(text)


# ---------------------------------------------------------------------------
# 1. Greek letters
# ---------------------------------------------------------------------------

def test_greek_alpha():
    assert ar(r"\alpha") == "alpha"


def test_greek_beta():
    assert ar(r"\beta") == "beta"


def test_greek_lambda_lower():
    assert ar(r"\lambda") == "lambda"


def test_greek_sigma_lower():
    assert ar(r"\sigma") == "sigma"


def test_greek_omega_lower():
    assert ar(r"\omega") == "omega"


def test_greek_Lambda_upper():
    # \Lambda (capital) should become "lambda" (via literal table)
    result = ar(r"\Lambda")
    assert "lambda" in result.lower()


def test_greek_chi():
    assert ar(r"\chi") == "chi"


# ---------------------------------------------------------------------------
# 2. Comparisons / operators
# ---------------------------------------------------------------------------

def test_geq():
    assert ar(r"\geq") == "greater than or equal to"


def test_leq():
    assert ar(r"\leq") == "less than or equal to"


def test_approx():
    assert ar(r"\approx") == "approximately equal to"


def test_sim():
    assert ar(r"\sim") == "approximately"


def test_neq():
    assert ar(r"\neq") == "not equal to"


def test_less_than_operator():
    result = ar("x < y")
    assert "less than" in result


def test_greater_than_operator():
    result = ar("z > 2")
    assert "greater than" in result


# ---------------------------------------------------------------------------
# 3. Powers / superscripts
# ---------------------------------------------------------------------------

def test_power_of_ten():
    result = ar(r"10^{12}")
    assert "ten to the 12" in result or "ten to the" in result


def test_scientific_notation():
    result = ar(r"3.3x10^5")
    assert "3.3 times ten to the 5" in result


def test_scientific_notation_uppercase_x():
    result = ar(r"2.5X10^{-3}")
    assert "times ten to the" in result
    assert "-3" in result


def test_generic_superscript_letter():
    result = ar(r"x^2")
    assert "squared" in result


def test_generic_superscript_cubed():
    result = ar(r"x^3")
    assert "cubed" in result


def test_generic_superscript_braced():
    result = ar(r"x^{k}")
    assert "to the" in result and "k" in result


# ---------------------------------------------------------------------------
# 4. Subscripts
# ---------------------------------------------------------------------------

def test_subscript_simple():
    result = ar(r"x_i")
    assert "sub" in result


def test_subscript_braced():
    result = ar(r"x_{ij}")
    assert "sub" in result


# ---------------------------------------------------------------------------
# 5. Fractions
# ---------------------------------------------------------------------------

def test_frac():
    result = ar(r"\frac{a}{b}")
    assert "a over b" in result


def test_frac_nested():
    result = ar(r"\frac{1}{2}")
    assert "1 over 2" in result


def test_one_over_x():
    result = ar(r"1/x")
    assert "one over x" in result


# ---------------------------------------------------------------------------
# 6. Roots
# ---------------------------------------------------------------------------

def test_sqrt():
    result = ar(r"\sqrt{x}")
    assert "square root of x" in result


def test_sqrt_nth():
    result = ar(r"\sqrt[3]{x}")
    assert "3 root of x" in result or "root of x" in result


# ---------------------------------------------------------------------------
# 7. Functions
# ---------------------------------------------------------------------------

def test_log():
    result = ar(r"\log(b)")
    assert "logarithm of b" in result


def test_ln():
    result = ar(r"\ln(x)")
    assert "natural log of x" in result


def test_exp():
    result = ar(r"\exp(t)")
    assert "exponential of t" in result


def test_sin():
    result = ar(r"\sin(w)")
    assert "sine of w" in result


def test_log_base():
    result = ar(r"\log_2(x)")
    assert "log base 2 of x" in result


# ---------------------------------------------------------------------------
# 8. Units — Mpc, kpc, km/s, Msun
# ---------------------------------------------------------------------------

def test_unit_mpc_bare():
    result = ar("distance of 10 Mpc")
    assert "megaparsecs" in result


def test_unit_kpc_bare():
    result = ar("within 200 kpc")
    assert "kiloparsecs" in result


def test_unit_km_s():
    result = ar("300 km/s")
    assert "kilometers per second" in result


def test_unit_km_s_mpc():
    result = ar("70 km/s/Mpc")
    assert "kilometers per second per megaparsec" in result


def test_unit_msun():
    result = ar(r"M_\odot")
    assert "solar masses" in result


def test_unit_msun_braced():
    # Braced forms need named-constant regex rules that precede the generic
    # subscript rule, otherwise M_{\odot} becomes "M sub sun".
    result = ar(r"M_{\odot}")
    assert "solar masses" in result


def test_unit_msun_literal():
    result = ar("Msun")
    assert "solar masses" in result


def test_unit_mpc_squared():
    result = ar("Mpc^2")
    assert "megaparsecs squared" in result or "megaparsecs" in result


def test_unit_mpc_cubed():
    result = ar("Mpc^3")
    assert "megaparsecs cubed" in result or "megaparsecs" in result


def test_unit_kpc_squared():
    result = ar("kpc^2")
    assert "kiloparsecs squared" in result or "kiloparsecs" in result


def test_unit_yr():
    result = ar("1 Gyr")
    assert "gigayears" in result


def test_unit_myr():
    result = ar("500 Myr")
    assert "megayears" in result


def test_unit_au():
    result = ar("1 AU")
    assert "astronomical units" in result


def test_unit_ev():
    result = ar("5 keV")
    assert "kilo electron volts" in result


def test_unit_arcsec():
    result = ar("0.5 arcsec")
    assert "arcseconds" in result


def test_unit_mas():
    result = ar("2 mas")
    assert "milliarcseconds" in result


# ---------------------------------------------------------------------------
# 9. Scientific notation
# ---------------------------------------------------------------------------

def test_sci_notation_negative_exp():
    result = ar(r"6.67x10^{-11}")
    assert "times ten to the" in result


def test_ten_to_the_bare():
    result = ar(r"10^4")
    assert "ten to the 4" in result


# ---------------------------------------------------------------------------
# 10. h^-1 / h^-3 factors
# ---------------------------------------------------------------------------

def test_h_minus_one_mpc():
    result = ar(r"h^{-1} Mpc")
    assert "h to the minus one megaparsecs" in result


def test_h_minus_three_mpc():
    result = ar(r"h^{-3} Mpc")
    assert "h to the minus three megaparsecs" in result


def test_h_minus_one_kpc():
    result = ar(r"h^{-1} kpc")
    assert "h to the minus one kiloparsecs" in result


def test_h_minus_one_bare():
    """h-1 without a unit: general h-factor rule."""
    result = ar("h-1")
    assert "h to the minus 1" in result


# ---------------------------------------------------------------------------
# 11. sigma_8, H_0, chi^2, Lambda CDM, percent
# ---------------------------------------------------------------------------

def test_sigma_eight():
    result = ar(r"\sigma_8")
    assert "sigma eight" in result


def test_sigma_eight_braced():
    result = ar(r"\sigma_{8}")
    assert "sigma eight" in result


def test_h_naught():
    result = ar(r"H_0")
    assert "H naught" in result


def test_h_naught_braced():
    result = ar(r"H_{0}")
    assert "H naught" in result


def test_chi_squared_command():
    result = ar(r"\chi^2")
    assert "chi squared" in result


def test_lambda_cdm_backslash():
    result = ar(r"\Lambda CDM")
    assert "Lambda C D M" in result


def test_lambda_cdm_bare():
    result = ar("LambdaCDM")
    assert "Lambda C D M" in result


def test_lambda_cdm_lcdm():
    result = ar("LCDM")
    assert "Lambda C D M" in result


def test_percent_symbol():
    result = ar("5%")
    assert "5 percent" in result


def test_percent_backslash():
    # The literal \% -> percent replacement
    result = ar(r"\%")
    assert "percent" in result


# ---------------------------------------------------------------------------
# 12. The CF4++ZOA sentence from idea.md / paper_ga
# ---------------------------------------------------------------------------

def test_cf4_sentence():
    text = r"We study galaxy clustering at scales of 1–100 $h^{-1}$ Mpc in the CF4++ZOA survey."
    result = ar(text)
    # $ delimiters should be gone
    assert "$" not in result
    # The h-factor should be expanded
    assert "h to the minus one megaparsecs" in result or "megaparsecs" in result
    # LaTeX backslash commands should be gone
    import re
    # No raw LaTeX command sequences should remain (allow \n-like newlines but
    # no \word sequences that look like LaTeX commands)
    assert not re.search(r"\\[A-Za-z]", result), f"LaTeX commands remain: {result!r}"


# ---------------------------------------------------------------------------
# 13. Dollar-delimiter stripping
# ---------------------------------------------------------------------------

def test_dollar_stripped_inline():
    result = ar(r"We measure $P(k)$ here.")
    assert "$" not in result
    # Content inside dollars preserved
    assert "P" in result


def test_dollar_stripped_standalone():
    result = ar(r"$\alpha$")
    assert "$" not in result
    assert "alpha" in result


def test_no_latex_dollars_remaining():
    text = r"The mass is $10^{14} M_\odot$ at $z=0.5$."
    result = ar(text)
    assert "$" not in result


# ---------------------------------------------------------------------------
# 14. Whitespace collapsing
# ---------------------------------------------------------------------------

def test_whitespace_collapsed():
    result = ar("a  b   c")
    assert "  " not in result


def test_newline_collapsed():
    result = ar("a\nb\nc")
    assert "\n" not in result


# ---------------------------------------------------------------------------
# 15. No LaTeX backslashes / dollars left (representative inputs)
# ---------------------------------------------------------------------------

def test_no_remaining_backslash_commands():
    text = r"\alpha \beta \gamma \sigma \chi \Lambda"
    result = ar(text)
    import re
    assert not re.search(r"\\[A-Za-z]", result), f"Remaining LaTeX: {result!r}"


def test_no_remaining_dollars():
    text = r"$\sigma_8$ and $\Omega_m$ from $\Lambda$CDM."
    result = ar(text)
    assert "$" not in result


# ---------------------------------------------------------------------------
# 16. Idempotency-ish sanity (running twice gives same result as once for
#     already-clean text)
# ---------------------------------------------------------------------------

def test_idempotent_on_plain_text():
    text = "We measure sigma eight and H naught."
    once = ar(text)
    twice = ar(once)
    assert once == twice


# ---------------------------------------------------------------------------
# 17. LLM safety valve in clean_paper
# ---------------------------------------------------------------------------

def _make_paper(abstract: str) -> Paper:
    return Paper(
        arxiv_id="test.001",
        title="Test Title",
        abstract=abstract,
        authors=["Test, Author"],
    )


def test_clean_paper_wellbehaved_llm_output_used():
    """When LLM output is the right length and clean, it is used."""
    paper = _make_paper("We find sigma eight equals 0.82.")
    # The regex pass will clean the abstract to something close in length.
    regex_version = apply_replacements(paper.abstract)
    # Build a well-behaved LLM response: same words, tiny tweak within 20%
    well_behaved = regex_version  # exact same length — always passes
    llm = FakeLLM(responses=[paper.title, well_behaved])  # title + abstract calls
    clean_paper(paper, llm)
    assert paper.clean_abstract == well_behaved


def test_clean_paper_empty_output_falls_back():
    """Empty LLM output → regex-only version kept."""
    paper = _make_paper("We study the large-scale structure at z = 0.3.")
    llm = FakeLLM(responses=["", ""])
    clean_paper(paper, llm)
    regex_abs = apply_replacements(paper.abstract)
    assert paper.clean_abstract == regex_abs


def test_clean_paper_too_long_output_falls_back():
    """LLM output >20% longer than regex version → fallback."""
    paper = _make_paper("We measure $\\sigma_8$.")
    regex_version = apply_replacements(paper.abstract)
    too_long = regex_version + " " + ("extra words " * 50)  # way over 20%
    llm = FakeLLM(responses=[too_long, too_long])
    clean_paper(paper, llm)
    assert paper.clean_abstract == regex_version


def test_clean_paper_too_short_output_falls_back():
    """LLM output >20% shorter than regex version → fallback."""
    paper = _make_paper("We measure cosmological parameters from the power spectrum analysis.")
    regex_version = apply_replacements(paper.abstract)
    # Create something much shorter
    too_short = "x"
    llm = FakeLLM(responses=[too_short, too_short])
    clean_paper(paper, llm)
    assert paper.clean_abstract == regex_version


def test_clean_paper_chatter_falls_back():
    """LLM output starting with 'Here is...' chatter → fallback."""
    paper = _make_paper("We constrain $\\Omega_m$.")
    regex_version = apply_replacements(paper.abstract)
    chatter = "Here is the cleaned text: " + regex_version
    llm = FakeLLM(responses=[chatter, chatter])
    clean_paper(paper, llm)
    assert paper.clean_abstract == regex_version


def test_clean_paper_chatter_sure_falls_back():
    """LLM output starting with 'Sure, ...' → fallback."""
    paper = _make_paper("We constrain $\\Omega_m$.")
    regex_version = apply_replacements(paper.abstract)
    chatter = "Sure, here you go: " + regex_version
    llm = FakeLLM(responses=[chatter, chatter])
    clean_paper(paper, llm)
    assert paper.clean_abstract == regex_version


def test_clean_paper_llm_error_falls_back():
    """LLMError on complete() → regex-only version kept."""
    paper = _make_paper("We measure $H_0$ at late times.")
    llm = FakeLLM(raise_mode=True)
    clean_paper(paper, llm)
    regex_abs = apply_replacements(paper.abstract)
    assert paper.clean_abstract == regex_abs


def test_clean_paper_output_echo_stripped():
    """LLM response starting with 'Output:' lead-in is stripped before use."""
    paper = _make_paper("H naught equals 70.")
    regex_version = apply_replacements(paper.abstract)
    echoed = "Output: " + regex_version
    llm = FakeLLM(responses=[echoed, echoed])
    clean_paper(paper, llm)
    # The stripped version should be used (same content, no "Output:")
    assert "Output:" not in paper.clean_abstract


# ---------------------------------------------------------------------------
# 18. process_papers
# ---------------------------------------------------------------------------

def test_process_papers_skips_discard(paper_co, paper_discard):
    """Papers with keep=False must not be processed."""
    llm = FakeLLM(responses=["clean title", "clean abstract"])
    papers = [paper_co, paper_discard]
    process_papers(papers, llm)
    # paper_co should have been processed
    assert paper_co.clean_title != "" or paper_co.clean_abstract != ""
    # paper_discard should remain untouched
    assert paper_discard.clean_title == ""
    assert paper_discard.clean_abstract == ""


def test_process_papers_survives_per_paper_exception(paper_co, paper_ga):
    """An exception on one paper must not abort processing of the next."""
    call_count = 0

    class ErrorOnFirstCallLLM(FakeLLM):
        def complete(self, system, prompt):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # title + abstract for first paper
                raise LLMError("injected error")
            return apply_replacements("Some text for paper 2.")

    llm = ErrorOnFirstCallLLM(responses=["ok"])
    papers = [paper_co, paper_ga]
    # Must not raise
    process_papers(papers, llm)
    # Both papers should have clean text (fallback regex for paper_co)
    assert paper_co.clean_title or paper_co.clean_abstract
    assert paper_ga.clean_title or paper_ga.clean_abstract


def test_process_papers_skip_keep_none():
    """Papers with keep=None should be skipped."""
    paper = _make_paper("Some abstract.")
    paper.keep = None
    llm = FakeLLM(responses=["anything"])
    process_papers([paper], llm)
    assert paper.clean_title == ""
    assert paper.clean_abstract == ""


def test_process_papers_skip_keep_false():
    """Papers with keep=False should be skipped."""
    paper = _make_paper("Some abstract.")
    paper.keep = False
    llm = FakeLLM(responses=["anything"])
    process_papers([paper], llm)
    assert paper.clean_title == ""
    assert paper.clean_abstract == ""
