"""Diagnostic material for an explicitly requested debug build.

The bundle carries the exact packet and the complete model response, because
a diagnostic that omitted them could not explain the build it describes. That
means it also carries the retained YouTube evidence inside the packet:
commenter display names, comment and reply text, the video description and
transcript text.

This module used to call that "privacy-safe" and "shareable". It is neither,
and the wording invited exactly the mistake it should have prevented, which is
attaching the file to a public bug report. tests/test_publishable.py states
the project's position on the same material plainly: those are real people's
names and words, and they are not ours to republish.

Redacting the evidence here was considered and rejected: it would leave a
diagnostic that cannot diagnose. The bundle stays complete and the labels now
say what it holds, so deciding to share it is a deliberate act rather than one
taken on a false assurance.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from ..domain.writing_options import (
    CHECK_OVERRIDES,
    DIALS,
    DIAL_FINAL_CHECK_ASSERTIONS,
    REGISTER_CONFLICTS,
    VARIATION_LIBRARY,
    ResolvedPromptSpec,
    analysis_waiver,
    dial_choice,
    dial_choice_classification,
    headings_by_key,
    register_conflicts,
    render_final_check,
    resolve_prompt_spec,
    resolved_dial_directives,
    variation_keys,
    variation_specs,
)


DEBUG_PACKET_FILENAME = "debug_packet.md"
DEBUG_RESPONSE_FILENAME = "debug_model_response.md"
DEBUG_REJECTED_RESPONSE_FILENAME = "debug_model_response_rejected.md"
DEBUG_BUNDLE_FILENAME = "debug_bundle.md"
TEMPLATE_LOGIC_AUDIT_FILENAME = "template_logic_audit.md"


EXTERNAL_AUDIT_CONTRACT = """Do not generate, rewrite, or repair the YouTube
comment. Audit the packet-generation logic and the produced model output.
Return coder-ready findings that identify which template/option interactions
should be changed.

### Primary goal

Treat the generated packet as a dynamically assembled program. Determine
whether its active instruction fragments are logically consistent and whether
they caused or enabled defects in the model output.

Do not merely critique prose quality. Do not merely rewrite the final comment.

### Step 1 - Extract hard invariants

Classify significant instructions as:

* HARD INVARIANT
* CONDITIONAL REQUIREMENT
* SOFT PREFERENCE
* PROCEDURAL RULE
* VALIDATION RULE
* EXCEPTION/WAIVER

For every hard invariant, determine whether any later active fragment:

* contradicts it;
* weakens it;
* waives it;
* changes its definition;
* validates a weaker substitute;
* creates an objective that rewards violating it.

### Step 2 - Trace the generation pipeline

Conceptually trace:

SOURCE ANALYSIS
-> CANDIDATE DISCOVERY
-> CANDIDATE VALIDATION
-> VARIATION GENERATION
-> RANKING
-> REPAIR/ASSEMBLY
-> FINAL VALIDATION
-> OUTPUT

At every transition ask:

* what validity property existed before this stage?
* is that property preserved?
* can this stage introduce an unvalidated central conclusion?
* can later ranking select an otherwise invalid candidate?
* does the final check enforce the original strong invariant?

### Step 3 - Explicitly search for these defect classes

1. TEMPLATE CONTRADICTION
2. TEMPLATE WAIVER
3. VALIDATOR WEAKENING
4. OBJECTIVE MISALIGNMENT
5. TONE/SUBSTANCE COLLISION
6. DIVERSITY PRESSURE
7. VALIDATED-CANDIDATE ESCAPE
8. DEFINITION DRIFT
9. LATE-STAGE PRIORITY INVERSION
10. UNSATISFIABLE CONSTRAINTS
11. REGISTER/DIAL INTERACTION
12. DEBUG-INSTRUCTION INTERFERENCE
13. MODEL EXECUTION ERROR
14. OTHER

### Step 4 - Central-conclusion originality audit

For workflows requiring original analytical comments, use this test:

"Could a viewer point to one passage, or a short contiguous explanation, where
the video speaker substantially states the same CENTRAL CONCLUSION?"

If YES, fail that candidate unless the workflow intentionally selected a mode
whose product is explicitly supposed to be non-analytical.

IMPORTANT: separately determine whether such an exception is itself compatible
with the packet's global hard invariants. Do not assume an exception is valid
merely because code marks it as a waiver.

The following do not independently create a new analytical conclusion:

* paraphrasing;
* shortening;
* combining source statements;
* stronger wording;
* sarcasm;
* humor;
* rhetorical questions;
* changing tone;
* adding another example;
* reorganizing chronology;
* naming an inconsistency the video already names.

### Step 5 - Audit the actual output

For each generated variation and each hardened final identify:

CENTRAL CONCLUSION:
SOURCE SUBSTANTIALLY STATES IT: YES/NO
ORIGINALITY: PASS/FAIL/NOT APPLICABLE
OTHER FAILURE:
ACTIVE PACKET RULE THAT SHOULD HAVE CAUGHT IT:
WHY IT SURVIVED:

Do not reward polish as analysis.

### Step 6 - Trace failures to active template fragments

For every output defect identify the exact active source identifier where
possible, for example:

* `VARIATION_LIBRARY["deadpan"].spec`
* `VARIATION_LIBRARY["summary"].waives_analysis`
* a specific active dial choice;
* `analysis_waiver()`;
* `comment_workflow.md`;
* final-contract renderer;
* `render_final_check()`;
* register/dial conflict handling.

Distinguish PACKET LOGIC DEFECT from MODEL EXECUTION ERROR from BOTH. Do not
blame the model when the packet gave it a reasonable path to the bad output.

### Step 7 - Required external-auditor output

Return exactly these report sections:

## VERDICT

PACKET LOGIC / MODEL EXECUTION / BOTH

## HARD INVARIANTS

## ACTIVE OPTION INTERACTIONS

## CONFLICTS FOUND

For each conflict include:

* conflict name;
* severity;
* hard invariant affected;
* active source identifier;
* exact conflicting text/behavior;
* activation condition;
* why logically unsafe;
* observed output effect;
* minimal fix principle.

## OUTPUT FAILURES

Give the central-conclusion audit for every variation and final.

## SELECTION-PIPELINE AUDIT

Show where an invalid candidate entered and why it was not eliminated.

## TEMPLATE FIX MAP

For every recommended change include:

* source identifier;
* current behavior;
* proposed semantic behavior;
* why;
* other options likely affected.

Do not provide blind global rewrites unless necessary.

## GENERALIZATION RISK

State whether each defect affects this run only, one variation, one dial, one
interaction, all comment packets, or another shared workflow.

## REQUIRED REGRESSION TESTS

For every defect give the option combination, expected packet property,
forbidden packet property, and expected model behavior.

## RECOMMENDED FIX ORDER

Put the highest-leverage systemic fixes first.

## HARSH PACKET-DESIGN CRITIQUE

Answer specifically:

* which instruction is safe alone but dangerous in combination?
* which hard invariant is later weakened?
* which soft objective outranks correctness?
* which stage introduces unvalidated content?
* which waiver is dangerous?
* which diversity/format requirement can force bad output?
* what is the single highest-leverage structural repair?

The report must be suitable for handing directly to the programmer maintaining
the template generator."""


@dataclass(frozen=True)
class VariationAuditFragment:
    """Canonical metadata and text for one resolved active variation."""

    key: str
    heading: str
    dimension: str
    waives_analysis: bool
    requires_humor: bool
    spec: str


@dataclass(frozen=True)
class DialAuditFragment:
    """Canonical metadata and resolved behavior for one active dial."""

    name: str
    label: str
    choice: str
    is_default: bool
    classification: str
    choice_text: str
    emitted_text: str
    final_check_assertion: str
    check_override: str
    validation_behavior: str
    register_conflicts: tuple[str, ...]


@dataclass(frozen=True)
class TemplateLogicAuditContext:
    """Everything fixed at build time that a later response cannot change."""

    video_id: str
    video_title: str
    prompt_version: str
    requested_variation_keys: tuple[str, ...]
    resolved_variation_keys: tuple[str, ...]
    displayed_variation_headings: tuple[str, ...]
    variations: tuple[VariationAuditFragment, ...]
    dials: tuple[DialAuditFragment, ...]
    length_mode: str
    target_words: str
    explicit_length: tuple[int, int] | None
    packet_budget: int
    debug_prompt_settings: str
    analysis_waiver_text: str
    variation_specification_block: str
    output_directives: str
    grounding_contract: str
    critique_contract: str
    final_contract: str
    ending_contract: str
    final_output_check: str
    register_conflicts: tuple[str, ...]
    normal_packet: str
    debug_packet: str


def build_template_logic_audit_context(
    *,
    settings: Mapping[str, Any],
    run: Mapping[str, Any],
    normal_packet: str,
    debug_packet: str,
    selected_variations: tuple[str, ...],
    dials: Mapping[str, str],
    final_check_template: str,
    explicit_length: tuple[int, int] | None,
) -> TemplateLogicAuditContext:
    """Capture active prompt provenance from the generator's own objects."""

    selections = dict(dials)
    requested = variation_keys(selected_variations)
    spec = resolve_prompt_spec(selected_variations, selections)
    resolved = spec.variation_keys
    shown = headings_by_key(resolved)
    variations = tuple(
        VariationAuditFragment(
            key=key,
            heading=shown[key],
            dimension=VARIATION_LIBRARY[key].dimension.value,
            waives_analysis=VARIATION_LIBRARY[key].waives_analysis,
            requires_humor=VARIATION_LIBRARY[key].requires_humor,
            spec=VARIATION_LIBRARY[key].spec,
        )
        for key in resolved
    )
    emitted_directives = resolved_dial_directives(selections)
    dial_fragments = tuple(
        _dial_audit_fragment(
            name,
            selections=selections,
            requested=requested,
            spec=spec,
            emitted_directives=emitted_directives,
        )
        for name in DIALS
    )
    prompt_settings = {
        name: settings[name]
        for name in (
            "mode",
            "selected_approaches",
            "dials",
            "length",
            "target_words",
        )
        if name in settings
    }
    return TemplateLogicAuditContext(
        video_id=str(run.get("video_id") or ""),
        video_title=str(run.get("video_title") or ""),
        prompt_version=str(run.get("prompt_version") or ""),
        requested_variation_keys=requested,
        resolved_variation_keys=resolved,
        displayed_variation_headings=tuple(shown[key] for key in resolved),
        variations=variations,
        dials=dial_fragments,
        length_mode=str(settings.get("length") or (
            "explicit" if explicit_length else "automatic"
        )),
        target_words=str(settings.get("target_words") or ""),
        explicit_length=explicit_length,
        packet_budget=int(run.get("budget") or 0),
        debug_prompt_settings=json.dumps(
            prompt_settings,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ),
        analysis_waiver_text=analysis_waiver(resolved),
        variation_specification_block=variation_specs(resolved, selections),
        output_directives=spec.output_directives,
        grounding_contract=spec.grounding_contract,
        critique_contract=spec.critique_contract,
        final_contract=spec.final_contract,
        ending_contract=spec.ending_contract,
        final_output_check=render_final_check(
            final_check_template,
            resolved,
            selections=selections,
        ),
        register_conflicts=tuple(register_conflicts(requested, selections)),
        normal_packet=normal_packet,
        debug_packet=debug_packet,
    )


def _dial_audit_fragment(
    name: str,
    *,
    selections: dict[str, str],
    requested: tuple[str, ...],
    spec: ResolvedPromptSpec,
    emitted_directives: Mapping[str, str],
) -> DialAuditFragment:
    """Describe one dial without independently interpreting packet prose."""

    definition = DIALS[name]
    choice = dial_choice(name, selections)
    structural_text = {
        "grounding": spec.grounding_contract,
        "critique": spec.critique_contract,
        "final": spec.final_contract,
        "ending": spec.ending_contract,
    }
    emitted = structural_text.get(name, emitted_directives.get(name, ""))
    active_conflicts = tuple(
        text
        for key, text in REGISTER_CONFLICTS.get((name, choice), {}).items()
        if key in requested
    )
    validation = {
        "grounding": f"ResolvedPromptSpec.structure_check: {spec.structure_check}",
        "critique": f"ResolvedPromptSpec.critique_check: {spec.critique_check}",
        "final": f"ResolvedPromptSpec.final_check: {spec.final_check}",
        "ending": (
            "ResolvedPromptSpec.ending_contract is embedded in the final "
            "contract."
        ),
    }.get(name, "Classification and any assertion below apply to final output.")
    return DialAuditFragment(
        name=name,
        label=definition.label,
        choice=choice,
        is_default=choice == definition.default,
        classification=dial_choice_classification(name, choice).value,
        choice_text=definition.choices[choice],
        emitted_text=emitted,
        final_check_assertion=DIAL_FINAL_CHECK_ASSERTIONS.get(
            (name, choice), ""
        ),
        check_override=CHECK_OVERRIDES.get((name, choice), ""),
        validation_behavior=validation,
        register_conflicts=active_conflicts,
    )


def render_template_logic_audit(
    context: TemplateLogicAuditContext,
    *,
    response_text: str = "",
    response_status: str = "not submitted",
    rejection_reason: str = "",
    draft: str = "",
) -> str:
    """Render one self-contained case for an independent auditing model."""

    configuration = {
        "video_id": context.video_id,
        "video_title": context.video_title,
        "prompt_version": context.prompt_version,
        "selected_variation_keys": list(context.requested_variation_keys),
        "resolved_variation_keys": list(context.resolved_variation_keys),
        "displayed_variation_headings": list(
            context.displayed_variation_headings
        ),
        "resolved_dials_including_defaults": {
            dial.name: dial.choice for dial in context.dials
        },
        "length": {
            "mode": context.length_mode,
            "target_words": context.target_words,
            "explicit_range": list(context.explicit_length)
            if context.explicit_length else None,
        },
        "packet_character_budget": context.packet_budget,
        "response_state": response_status,
    }
    parts = [
        "# Template Logic Audit Case",
        (
            "> **Review before sharing.** This file is unredacted diagnostic "
            "material. It contains the generated packet, model-facing packet, "
            "model response when available, and therefore retained YouTube "
            "evidence such as names, comments, replies, description, and "
            "transcript. Review before sharing. It contains no credentials or "
            "local filesystem paths."
        ),
        _audit_section("Instructions for the auditing LLM", EXTERNAL_AUDIT_CONTRACT),
        _audit_section(
            "Run configuration",
            "```json\n"
            + json.dumps(configuration, indent=2, ensure_ascii=False, sort_keys=True)
            + "\n```\n\n### Debug settings relevant to prompt construction\n\n"
            + "```json\n"
            + context.debug_prompt_settings
            + "\n```",
        ),
        _audit_section(
            "Active variation fragments",
            "\n\n".join(_render_variation(fragment)
                          for fragment in context.variations),
        ),
        _audit_section(
            "Active dial fragments",
            "\n\n".join(_render_dial(fragment) for fragment in context.dials),
        ),
        _audit_section(
            "Generated/derived instruction fragments",
            _render_derived_fragments(context),
        ),
        _audit_section("Prompt provenance map", _prompt_provenance_map()),
        _audit_section("Response status", _response_status(
            response_status, rejection_reason, draft
        )),
        _audit_section("Exact normal generated packet", context.normal_packet),
        _audit_section("Exact model-facing debug packet", context.debug_packet),
        _audit_section(
            "Complete model response",
            response_text
            if response_status != "not submitted"
            else "_No model response has been submitted yet._",
        ),
    ]
    return "\n\n".join(parts) + "\n"


def _audit_section(heading: str, content: str) -> str:
    return f"## {heading}\n\n{content or '[emits no text]'}"


def _render_variation(fragment: VariationAuditFragment) -> str:
    return "\n".join((
        f"### Variation: {fragment.key}",
        "",
        f"* source: `domain/writing_options.py::VARIATION_LIBRARY[\"{fragment.key}\"]`",
        f"* heading: {fragment.heading}",
        f"* dimension: {fragment.dimension}",
        f"* waives_analysis: {str(fragment.waives_analysis).lower()}",
        f"* requires_humor: {str(fragment.requires_humor).lower()}",
        "* active text:",
        "",
        fragment.spec,
    ))


def _render_dial(fragment: DialAuditFragment) -> str:
    conflicts = "\n".join(f"  * {item}" for item in fragment.register_conflicts)
    return "\n".join((
        f"### Dial: {fragment.name}",
        "",
        f"* source: `domain/writing_options.py::DIALS[\"{fragment.name}\"]`",
        f"* label: {fragment.label}",
        f"* resolved choice: {fragment.choice}",
        f"* is default: {str(fragment.is_default).lower()}",
        f"* classification: {fragment.classification}",
        "* canonical stored choice text:",
        "",
        fragment.choice_text or "[emits no text]",
        "",
        "* exact text emitted into the active prompt:",
        "",
        fragment.emitted_text or "[emits no text]",
        "",
        "* final-check assertion:",
        "",
        fragment.final_check_assertion or "[no separate assertion]",
        "",
        "* check override declaration:",
        "",
        fragment.check_override or "[no declared override]",
        "",
        f"* validation behavior: {fragment.validation_behavior}",
        "* active register conflicts:",
        conflicts or "  * [none]",
    ))


def _render_derived_fragments(context: TemplateLogicAuditContext) -> str:
    replacement = (
        "The canonical `resolved_variation_keys()` changed the requested "
        f"sequence {list(context.requested_variation_keys)!r} to "
        f"{list(context.resolved_variation_keys)!r}."
        if context.requested_variation_keys != context.resolved_variation_keys
        else "[no active register replacements]"
    )
    conflicts = (
        "\n".join(f"* {item}" for item in context.register_conflicts)
        if context.register_conflicts else "[no active register conflicts]"
    )
    fragments = (
        ("Analysis waiver", "`domain/writing_options.py::analysis_waiver`",
         context.analysis_waiver_text),
        ("Variation specification block",
         "`domain/writing_options.py::variation_specs`",
         context.variation_specification_block),
        ("Output directives/dial block",
         "`domain/writing_options.py::resolve_prompt_spec().output_directives`",
         context.output_directives),
        ("Grounding contract",
         "`domain/writing_options.py::ResolvedPromptSpec.grounding_contract`",
         context.grounding_contract),
        ("Critique contract",
         "`domain/writing_options.py::ResolvedPromptSpec.critique_contract`",
         context.critique_contract),
        ("Final contract",
         "`domain/writing_options.py::ResolvedPromptSpec.final_contract`",
         context.final_contract),
        ("Ending contract",
         "`domain/writing_options.py::ResolvedPromptSpec.ending_contract`",
         context.ending_contract),
        ("Final output check",
         "`domain/writing_options.py::render_final_check`",
         context.final_output_check),
        ("Register/dial conflict instructions",
         "`domain/writing_options.py::register_conflicts`", conflicts),
        ("Conflict replacements",
         "`domain/writing_options.py::resolved_variation_keys`", replacement),
    )
    return "\n\n".join(
        f"### {heading}\n\n* source: {source}\n\n{text or '[emits no text]'}"
        for heading, source, text in fragments
    )


def _prompt_provenance_map() -> str:
    return "\n".join((
        "* Workflow template: `resources/prompts/comment_workflow.md`",
        "* Final-check template: `resources/prompts/comment_final_check.md`",
        "* Variation definitions: `domain/writing_options.py::VARIATION_LIBRARY`",
        "* Dial definitions: `domain/writing_options.py::DIALS`",
        "* Analysis waiver: `domain/writing_options.py::analysis_waiver`",
        "* Resolved contracts: `domain/writing_options.py::resolve_prompt_spec`",
        "* Variation renderer: `domain/writing_options.py::variation_specs`",
        "* Dial directive renderer: "
        "`domain/writing_options.py::resolved_dial_directives`",
        "* Final-check renderer: `domain/writing_options.py::render_final_check`",
        "* Register conflict resolver: `domain/writing_options.py::register_conflicts`",
        "* Packet instruction renderer: "
        "`domain/packet_builder.py::render_instructions`",
        "* Debug suffix renderer: `application/debug_build.py::render_debug_packet`",
    ))


def _response_status(status: str, rejection_reason: str, draft: str) -> str:
    return "\n".join((
        f"* status: {status}",
        "* exact rejection reason:",
        "",
        rejection_reason or "[not rejected]",
        "",
        "* saved/extracted Hardened final:",
        "",
        draft or "[not available]",
    ))


def debug_report_problem(text: str) -> str:
    """Return a precise failure when a diagnostic response omits its report."""

    body = str(text or "").replace("\r\n", "\n")
    report = list(re.finditer(r"(?im)^###\s+debug\s+report\s*$", body))
    final = list(re.finditer(r"(?im)^###\s+hardened\s+final\s*$", body))
    if len(report) != 1:
        return (
            "A Debug build requires exactly one '### Debug report' section "
            "before '### Hardened final'."
        )
    if not final or report[0].start() > final[-1].start():
        return (
            "The Debug report must appear before '### Hardened final', which "
            "must remain the final section."
        )
    return ""


def render_debug_packet(
    packet_text: str,
    *,
    settings: Mapping[str, Any],
    run: Mapping[str, Any],
) -> str:
    """Add a diagnostic instruction without changing the normal final contract."""

    return "\n".join((
        packet_text.rstrip(),
        "",
        "---",
        "",
        "## Debug-build instructions",
        "",
        "This is a diagnostic build. Complete every normal instruction in this "
        "packet. In addition, place one `### Debug report` section immediately "
        "before `### Hardened final`. The Hardened final must remain the last "
        "section and must still be a ready-to-post comment.",
        "",
        "In the Debug report, state briefly:",
        "- whether the required Video line is exact and contains one plain URL;",
        "- any evidence, attribution, or uncertainty concerns;",
        "- whether the proposed variations are genuinely distinct;",
        "- any packet truncation, missing-evidence, or instruction conflict you see;",
        "- the specific change that would most improve the next build.",
        "",
        "The Debug report is for the developer, not for posting. Do not put it "
        "inside the Hardened final. It is mandatory: an answer without exactly "
        "one `### Debug report` before `### Hardened final` will be rejected.",
        "",
        "## Safe debug context",
        "",
        "```json",
        json.dumps({
            "settings": dict(settings),
            "run": {
                "video_id": run.get("video_id", ""),
                "video_title": run.get("video_title", ""),
                "variations": run.get("variations", []),
                "dials": run.get("dials", {}),
                "packet_characters": run.get("packet_characters", 0),
                "budget": run.get("budget", 0),
                "retrieval": run.get("retrieval", {}),
                "transcript": run.get("transcript", {}),
                "warnings": run.get("warnings", []),
            },
        }, indent=2, ensure_ascii=False, sort_keys=True),
        "```",
        "",
    ))


def render_debug_bundle(
    *,
    settings: Mapping[str, Any],
    run: Mapping[str, Any],
    packet_text: str,
    response_text: str,
    draft: str,
    rejection_reason: str = "",
) -> str:
    """Render one diagnostic record, complete enough to explain the build.

    It holds no credentials, no local paths and no settings beyond the safe
    set. It does hold the exact packet and the complete model response, so it
    also holds the retained YouTube evidence those contain. Review it before
    sending it anywhere.
    """

    sections = (
        ("Safe build settings", json.dumps(dict(settings), indent=2,
                                             ensure_ascii=False, sort_keys=True)),
        ("Run record", json.dumps(dict(run), indent=2, ensure_ascii=False,
                                    sort_keys=True)),
        ("Exact debug packet", packet_text.rstrip()),
        ("Complete model response", response_text.rstrip()),
        ("Response status", rejection_reason or "Accepted."),
        ("Saved Hardened final", draft.rstrip()),
    )
    # Stated in the file itself, not only in the interface that produced it.
    # The bundle is what gets attached to a bug report, and by then whatever
    # the window said is long out of view.
    lines = [
        "# Debug build bundle",
        "",
        "> **Review before sharing.** This bundle is unredacted. It contains "
        "the exact packet and the complete model response, and therefore the "
        "retained YouTube evidence inside them: commenter display names, "
        "comment and reply text, the video description and transcript text. "
        "It contains no credentials and no local paths.",
        "",
    ]
    for heading, content in sections:
        lines.extend((f"## {heading}", "", content or "_Not available._", ""))
    return "\n".join(lines)
