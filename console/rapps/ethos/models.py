"""Pydantic models for the ETHOS responses the console actually consumes.

Every field is optional and every model ignores what it does not know. Two
reasons: ``GET /compatibility`` is served with ``response_model_exclude_none``,
so absent keys vanish rather than arriving as null; and a run manifest grows
new blocks as ETHOS gains build steps, which must never break a page that does
not use them.

A missing value is ``None`` and is rendered ",". It is never coerced to 0
(GL-09), a stack that has no such counter and a counter that was not measured
are both absences, and neither is a zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from console.rapps.ethos.metrics import NOT_MEASURED


class Loose(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class Option(Loose):
    """One selectable item in a catalogue category."""

    category: str | None = None
    id: str | None = None
    slug: str | None = None
    label: str | None = None
    status: str | None = None
    aliases: list[str] = Field(default_factory=list)
    note: str | None = None

    # Filled in by profiles.py, not by ETHOS. Until GET /catalogue (B4) exists
    # the console joins compatibility with the deploy profiles itself.
    deployable: bool | None = None
    reason: str | None = None

    @property
    def display(self) -> str:
        """Always the label. Never the slug (GL-05), the split slugs
        ``mixocuoai`` / ``mixoaiocu`` no longer match any config_id head."""
        return self.label or self.id or self.slug or "?"


class Coupling(Loose):
    """A rule the form must honour, e.g. RULE-1: a TM500 UE runs only against
    the TM500 RU emulation, and vice versa."""

    name: str | None = None
    rule: str | None = None
    bidirectional: bool | None = None
    requires: dict[str, Any] = Field(default_factory=dict)
    implies: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class Catalogue(Loose):
    version: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    required_categories: list[str] = Field(default_factory=list)
    options: dict[str, list[Option]] = Field(default_factory=dict)
    couplings: list[Coupling] = Field(default_factory=list)

    def category(self, name: str) -> list[Option]:
        return self.options.get(name, [])

    def option(self, category: str, ident: str) -> Option | None:
        for option in self.category(category):
            if ident in (option.id, option.slug, option.label):
                return option
        return None


class ValidationReason(Loose):
    code: str | None = None
    severity: str | None = None
    message: str | None = None
    rule: str | None = None
    fields: list[str] = Field(default_factory=list)


class ValidationResult(Loose):
    valid: bool = False
    experimental: bool = False
    resolved_selection: dict[str, str] = Field(default_factory=dict)
    reasons: list[ValidationReason] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationReason]:
        return [r for r in self.reasons if (r.severity or "").lower() == "error"]

    @property
    def first_error(self) -> str | None:
        return self.errors[0].message if self.errors else None


class TestDefinition(Loose):
    config_id: str | None = None
    display_name: str | None = None
    selection: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    test_plan: dict[str, Any] = Field(default_factory=dict)


class TestDefGenerated(Loose):
    test_definition: TestDefinition = Field(default_factory=TestDefinition)
    sample_run_id: str | None = None
    validation: ValidationResult = Field(default_factory=ValidationResult)


class CellConfig(Loose):
    band: str | None = None
    bandwidth_mhz: float | None = None
    n_prb: int | None = None
    scs_khz: float | None = None
    centre_freq_mhz: float | None = None
    dl_arfcn: float | None = None
    ssb_arfcn: float | None = None
    pci: int | None = None
    antennas_dl: int | None = None
    antennas_ul: int | None = None
    antenna_config: str | None = None
    max_mimo_layers_dl: int | None = None
    max_mimo_layers_ul: int | None = None
    tdd_period_ms: float | None = None
    tdd_dl_slots: int | None = None
    tdd_ul_slots: int | None = None
    tdd_dl_symbols: int | None = None
    tdd_ul_symbols: int | None = None
    tdd_pattern: str | None = None
    tdd_slots: str | None = None
    mcs_table_dl: str | None = None
    mcs_table_ul: str | None = None
    max_ue_mcs_dl: int | None = None
    max_ue_mcs_ul: int | None = None
    vendor: str | None = None
    source: str | None = None
    read_at: str | None = None
    confirmed_by_log: bool | None = None

    @property
    def chips(self) -> list[str]:
        """The chips shown beside every result (OV-02, RS-15). The TDD pattern
        is always one of them: OCUDU runs 7D2U over 5 ms and OAI DDDSU over
        2.5 ms, so any comparison between them is partly a comparison of two
        TDD configurations."""
        out: list[str] = []
        if self.band:
            out.append(self.band)
        if self.bandwidth_mhz:
            out.append(f"{self.bandwidth_mhz:g} MHz")
        if self.antenna_config:
            out.append(self.antenna_config)
        if self.scs_khz:
            out.append(f"{self.scs_khz:g} kHz")
        if self.tdd_pattern:
            out.append(self.tdd_pattern)
        return out


class RadioSummary(Loose):
    window_kind: str | None = None
    du_vendor: str | None = None
    radio_sample_count: int | None = None
    # comparable across stacks
    cqi_mean: float | None = None
    cqi_min: float | None = None
    cqi_max: float | None = None
    cqi_p95: float | None = None
    pusch_snr_db_mean: float | None = None
    pusch_snr_db_min: float | None = None
    pusch_snr_db_max: float | None = None
    pusch_snr_db_p95: float | None = None
    bler_dl_residual_mean: float | None = None
    bler_dl_residual_max: float | None = None
    bler_ul_residual_mean: float | None = None
    bler_ul_residual_max: float | None = None
    ri_dl_mean: float | None = None
    ri_ul_mean: float | None = None
    mcs_dl_mean: float | None = None
    mcs_ul_mean: float | None = None
    mcs_table_dl: str | None = None
    mcs_table_ul: str | None = None
    phr_db_mean: float | None = None
    # OAI only
    bler_dl_first_tx_mean: float | None = None
    bler_dl_first_tx_max: float | None = None
    bler_ul_first_tx_mean: float | None = None
    bler_ul_first_tx_max: float | None = None
    pucch_snr_db_mean: float | None = None
    ue_l1_rsrp_dbm_mean: float | None = None
    rrc_ss_rsrp_dbm: float | None = None
    rrc_ss_rsrq_db: float | None = None
    rrc_ss_sinr_db: float | None = None
    # OCUDU only
    gnb_ul_rsrp_db_mean: float | None = None
    ta_ns_mean: float | None = None
    dl_buffer_bytes_mean: float | None = None
    ul_bsr_bytes_mean: float | None = None
    # from the handset, either stack
    ue_ss_rsrp_dbm: float | None = None
    ue_ss_rsrq_db: float | None = None
    ue_ss_sinr_db: float | None = None
    ue_ss_rsrp_dbm_end: float | None = None
    ue_ss_rsrq_db_end: float | None = None
    ue_ss_sinr_db_end: float | None = None
    rnti: str | None = None
    pci: int | None = None
    source: str | None = None
    reason: str | None = None


class Latency(Loose):
    rtt_ms_min: float | None = None
    rtt_ms_mean: float | None = None
    rtt_ms_max: float | None = None
    rtt_ms_p95: float | None = None
    rtt_ms_mdev: float | None = None
    rtt_loss_pct: float | None = None
    rtt_count: int | None = None
    window_kind: str | None = None
    source: str | None = None
    reason: str | None = None


class Run(Loose):
    """A run manifest. The console reads it; only ETHOS writes it."""

    manifest_version: int | None = None
    run_id: str = ""
    config_id: str | None = None
    config_hash: str | None = None
    campaign_id: str | None = None
    direction: str | None = None
    offered_mbps: float | None = None
    offered_actual_mbps: float | None = None
    achieved_mbps: float | None = None
    achieved_over_tx_mbps: float | None = None
    loss_pct: float | None = None
    loss_pct_vs_offered: float | None = None
    delivered_bytes: int | None = None
    duration_requested_s: float | None = None
    duration_s: float | None = None
    tx_duration_s: float | None = None
    rx_duration_s: float | None = None
    rx_tx_ratio: float | None = None
    server_owner: str | None = None
    #: `core-switch status` as read on the host before this run, verbatim
    #: (ETHOS B18). None means it was never read, and the run then carries the
    #: `core_unknown` quality flag: it is NOT taken for Open5GS.
    core_switch: dict[str, Any] | None = None
    server_version: str | None = None
    client_version: str | None = None
    traffic_mode: str | None = None
    traffic_receiver_role: str | None = None
    condition: str | None = None
    state_verified: bool | None = None
    state_reason: str | None = None
    config_ref: str | None = None
    t_created: str | None = None
    t_started: str | None = None
    t_ended: str | None = None
    t_traffic_start: str | None = None
    t_traffic_end: str | None = None
    pkg1_w: float | None = None
    pkg0_w: float | None = None
    ee_kpi_total_mbit_per_w: float | None = None
    ee_kpi: dict[str, Any] | None = None
    o1_pm: dict[str, Any] | None = None
    traffic: dict[str, Any] | None = None
    cross_check: dict[str, Any] | None = None
    cm_context: dict[str, Any] | None = None
    cm_writes: list[dict[str, Any]] | None = None
    deployment: dict[str, Any] | None = None
    ue: dict[str, Any] | None = None
    o2_capture: dict[str, Any] | None = None
    cell_config: CellConfig | None = None
    radio_summary: RadioSummary | None = None
    latency: Latency | None = None
    radio_ref: str | None = None
    quality_flags: list[Any] = Field(default_factory=list)
    status: str | None = None

    @property
    def head(self) -> str:
        """The config_id head, matched exactly. Never prefix-matched: the legacy
        head ``oai-mixoaiocu`` starts with "oai" and was once filed as a pure-OAI
        run because of it."""
        return (self.config_id or "").split("_", 1)[0]

    #: config_id field 5, in the core profiles' spelling.
    CORE_BY_SLUG: ClassVar[dict[str, str]] = {"o5gs": "open5gs", "f5gc": "free5gc"}

    @property
    def core(self) -> str | None:
        """Which 5G core served this run, or None if nothing says.

        The archived `core_switch` wins: it was read on the host moments
        before the run. The config_id is the fallback, one step weaker since
        it records what was ASKED for. Neither present means None, and None is
        shown as unknown, never as Open5GS: two cores take turns on one host,
        and assuming the default is how a free5GC number ends up in an Open5GS
        series.
        """
        archived = (self.core_switch or {}).get("core")
        if archived:
            return str(archived)
        fields = (self.config_id or "").split("_")
        return self.CORE_BY_SLUG.get(fields[4]) if len(fields) > 4 else None

    @property
    def core_confirmed(self) -> bool:
        """Was the core read on the host for THIS run, rather than inferred?"""
        return bool((self.core_switch or {}).get("core"))

    @property
    def core_label(self) -> str:
        return {"open5gs": "Open5GS", "free5gc": "free5GC"}.get(self.core or "", "")

    @property
    def core_peers(self) -> list[str]:
        """The gNBs attached to the core when this run was created."""
        peers = ((self.core_switch or {}).get("ngap_peers_established") or "").split()
        return peers

    @property
    def has_delivered(self) -> bool:
        return bool(self.delivered_bytes)

    @property
    def usable(self) -> bool:
        """Usable for analysis: traffic was delivered and the iperf server was
        one we recognise (RS-05)."""
        return self.has_delivered and self.server_owner in ("ethos", "app_binary")

    @property
    def flag_names(self) -> list[str]:
        out: list[str] = []
        for flag in self.quality_flags:
            if isinstance(flag, str):
                out.append(flag)
            elif isinstance(flag, dict):
                name = flag.get("flag") or flag.get("name") or flag.get("code")
                if name:
                    out.append(str(name))
        return out


class RunList(Loose):
    count: int = 0
    filters: dict[str, Any] = Field(default_factory=dict)
    runs: list[Run] = Field(default_factory=list)


class DeployStatus(Loose):
    profile: str | None = None
    profile_status: str | None = None
    config_id: str | None = None
    stack: str | None = None
    namespace: str | None = None
    releases: list[Any] = Field(default_factory=list)
    pods: list[Any] = Field(default_factory=list)
    running_pods: list[Any] = Field(default_factory=list)
    node_free: bool | None = None
    node_reason: str | None = None
    node_check: Any | None = None
    deployer: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @property
    def anything_deployed(self) -> bool:
        return bool(self.releases or self.running_pods)

    @property
    def node_observed(self) -> bool:
        """Whether ETHOS actually looked at the node for this request.

        ``node_free`` is null both when the probe failed and when it was never
        attempted, and the two are different facts. ETHOS attempts it only when
        the request names a stack, and records what it found in ``node_check``.
        """
        return self.node_check is not None or self.node_free is not None

    @property
    def node_detail(self) -> str:
        """The real reason, for the hover text.

        A failed probe puts its error in ``warnings`` ("node state unavailable:
        …"); an unattempted one leaves the initialiser behind. Neither should be
        shown as if the node had been looked at and found wanting.
        """
        problems = [w for w in self.warnings if "node" in w.lower()]
        if problems:
            return "; ".join(problems)
        if self.node_observed:
            return self.node_reason or "the node was observed"
        return (
            "ETHOS probes the node only when the request names a stack, and this "
            "one did not, so the node was never looked at. Select a topology to "
            "have it checked."
        )

    @property
    def namespace_summary(self) -> str:
        """What was observed in the namespace, which is answered either way."""
        if self.anything_deployed:
            return (
                f"{len(self.releases)} release(s) and "
                f"{len(self.running_pods)} running pod(s) in {self.namespace}"
            )
        return f"no Helm release and no pod in {self.namespace}"


class EthosHealth(Loose):
    status: str | None = None
    service: str | None = None
    version: str | None = None


# --- the lock, readiness, jobs, the summary and the UEs (B1, B2, B5, B6, B11) --


class Holder(Loose):
    """Who holds the testbed. ETHOS names the holder; the console never guesses.

    The holder string carries its own kind: `cli:<pid>` is a campaign run from a
    shell, `job:<job_id>` is one this console or another client started, and
    `action:<name>` is a standalone act such as an attach. Rendering is
    `console.holders.describe`, so one wording is used everywhere a holder
    appears.
    """

    held: bool = False
    holder: str | None = None
    what: str | None = None
    since: str | None = None

    @property
    def is_cli(self) -> bool:
        return bool(self.holder and self.holder.startswith("cli:"))

    @property
    def is_job(self) -> bool:
        return bool(self.holder and self.holder.startswith("job:"))

    @property
    def job_id(self) -> str | None:
        return self.holder.split(":", 1)[1] if self.is_job and self.holder else None


class ReadinessCheck(Loose):
    """One of ETHOS's seven checks, as ETHOS judged it.

    `status` is `pass`, `fail` or `unknown`, and the console renders whichever
    came back. It never upgrades an `unknown` to a pass, and never downgrades one
    to a failure: those are different answers and only ETHOS is entitled to give
    them.
    """

    id: str = ""
    status: str = "unknown"
    reason: str = ""
    checked_at: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    @property
    def failed(self) -> bool:
        return self.status == "fail"


class Readiness(Loose):
    ready: bool = False
    first_blocker: str = ""
    checks: list[ReadinessCheck] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)

    def get(self, check_id: str) -> ReadinessCheck | None:
        return next((c for c in self.checks if c.id == check_id), None)

    @property
    def failures(self) -> list[ReadinessCheck]:
        return [c for c in self.checks if c.failed]


class Preview(Loose):
    """ETHOS's own description of what an action would do, plus its token."""

    action: str = ""
    summary: list[str] = Field(default_factory=list)
    preview_token: str = ""
    expires_in_s: int | None = None
    state: dict[str, Any] = Field(default_factory=dict)


class JobStep(Loose):
    """One stage of a campaign, as ETHOS recorded it.

    The state words are ETHOS's; the label and the duration string are this
    page's, because how long a stage took is a thing to read rather than a
    measurement (GL-05, GL-09).
    """

    name: str = ""
    state: str = ""
    started: str | None = None
    ended: str | None = None
    detail: str = ""
    elapsed_s: float | None = None

    @property
    def label(self) -> str:
        """The stage in words. Switching names the core it is switching TO.

        A job that sits in one stage for 20 seconds looks stuck unless the
        page says what it is waiting for, and "switching_core" is not that.
        """
        if self.name == "switching_core":
            target = self.detail.split("->")[-1].split(";")[0].strip() if "->" in self.detail else ""
            pretty = CORE_LABELS.get(target, target)
            return f"switching core to {pretty}" if pretty else "switching core"
        if self.name == "restoring_core":
            return f"restoring {CORE_LABELS['open5gs']}"
        return self.name.replace("_", " ")

    @property
    def took(self) -> str:
        """How long the stage took, or n/a while it is still running.

        `elapsed_s` is ETHOS's when it sends one; an older build does not, and
        the two stamps are still there to subtract.
        """
        if self.elapsed_s is not None:
            return f"{self.elapsed_s:.1f} s"
        if not self.started or not self.ended:
            return NOT_MEASURED
        try:
            start = datetime.fromisoformat(self.started.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self.ended.replace("Z", "+00:00"))
        except ValueError:
            return NOT_MEASURED
        return f"{(end - start).total_seconds():.1f} s"


class JobPoint(Loose):
    direction: str | None = None
    offered_mbps: float | None = None
    run_id: str | None = None
    achieved_mbps: float | None = None
    loss_pct: float | None = None
    jitter_ms: float | None = None
    status: str | None = None
    reason: str = ""


TERMINAL_JOB_STATES = ("completed", "failed", "aborted", "interrupted")


class Job(Loose):
    job_id: str = ""
    state: str = ""
    source: str = "api"
    plan: dict[str, Any] = Field(default_factory=dict)
    config_id: str | None = None
    created: str | None = None
    started: str | None = None
    ended: str | None = None
    steps: list[JobStep] = Field(default_factory=list)
    points: list[JobPoint] = Field(default_factory=list)
    run_ids: list[str] = Field(default_factory=list)
    cell_config: CellConfig | None = None
    outcome: str = ""
    error: str = ""
    stop_requested: bool = False
    deployed_at_interrupt: dict[str, Any] | None = None

    @property
    def finished(self) -> bool:
        return self.state in TERMINAL_JOB_STATES

    @property
    def graph_run_ids(self) -> list[str]:
        """The runs a figure drawn from this job would be built from.

        These are the runs that produced a point, which is exactly what ETHOS
        resolves `job_ids` to. `run_ids` is a longer list: a sweep also creates
        a run it abandons before any traffic, and that run has no measurement to
        contribute, so counting it would overstate what the job offers a figure.
        """
        seen: list[str] = []
        for point in self.points:
            if point.run_id and point.run_id not in seen:
                seen.append(point.run_id)
        return seen

    @property
    def measured_run_ids(self) -> list[str]:
        """The graph-eligible runs that actually carry a measurement.

        Usually every one of them, and then a picker reads `10/10`. It is not
        always: a sweep can finish with points that recorded no throughput, and
        one job in this lab's archive has ten points of which one measured. The
        two numbers are kept apart so that job reads `1/10` rather than a tidy
        `10/10` that would hide it.
        """
        return [p.run_id for p in self.points
                if p.run_id and p.achieved_mbps is not None]

    @property
    def label(self) -> str:
        return str(self.plan.get("label") or "")

    @property
    def expected_points(self) -> int:
        """How many points the plan asked for, from the plan itself.

        Parsed the same way `console.rapps.ethos.plan` parses the form, so a
        progress bar cannot disagree with what the plan said.
        """
        from console.rapps.ethos.plan import TrafficPlan

        parsed = TrafficPlan(
            rates_text=str(self.plan.get("rates") or ""),
            direction=str(self.plan.get("direction") or "DL"),
            duration_text=str(self.plan.get("duration") or "0"),
            repeats=int(self.plan.get("repeats") or 1),
        ).parse()
        return parsed.points if parsed.valid else 0

    @property
    def can_stop(self) -> bool:
        return not self.finished and not self.stop_requested


class JobList(Loose):
    count: int = 0
    jobs: list[Job] = Field(default_factory=list)

    @property
    def running(self) -> list[Job]:
        return [job for job in self.jobs if not job.finished]


class SummaryPart(Loose):
    """One part of the status summary, with its own timestamp and error.

    ETHOS gathers each part separately so one failing probe never fails the
    response, and the console renders that same way: a part with an error shows
    the error against that item and nothing else changes.
    """

    error: str = ""
    checked_at: str | None = None

    @property
    def ok(self) -> bool:
        return not self.error


class LockPart(SummaryPart, Holder):
    pass


class DeployedPart(SummaryPart):
    profile: str | None = None
    stack: str | None = None
    namespace: str | None = None
    releases: list[Any] = Field(default_factory=list)
    pods: list[Any] = Field(default_factory=list)
    running_pods: list[Any] = Field(default_factory=list)
    node_free: bool | None = None
    node_reason: str = ""

    @property
    def anything_deployed(self) -> bool:
        return bool(self.releases or self.running_pods)


class JobPart(SummaryPart):
    job_id: str | None = None
    state: str | None = None
    label: str | None = None
    config_id: str | None = None
    points: int = 0
    expected_points: int = 0
    started: str | None = None
    ended: str | None = None

    @property
    def finished(self) -> bool:
        return (self.state or "") in TERMINAL_JOB_STATES

    @property
    def progress(self) -> str:
        return f"{self.points} of {self.expected_points}" if self.expected_points else ""


class UePart(SummaryPart):
    ue: str | None = None
    reachable: bool | None = None
    attached: bool | None = None
    ip: str | None = None
    mechanism: str | None = None


class IperfPart(SummaryPart):
    default_mode: str | None = None
    holder: dict[str, Any] | None = None

    @property
    def held(self) -> bool:
        return self.holder is not None

    @property
    def owner(self) -> str:
        return str((self.holder or {}).get("owner") or "unknown")


class FreshnessSource(Loose):
    last_point: str | None = None
    bucket: str | None = None
    measurement: str | None = None
    cell_fdn: str | None = None
    error: str = ""


class FreshnessPart(SummaryPart):
    results: FreshnessSource = Field(default_factory=FreshnessSource)
    o1_pm: FreshnessSource = Field(default_factory=FreshnessSource)
    o2_power: FreshnessSource = Field(default_factory=FreshnessSource)


class ApiPart(SummaryPart):
    version: str | None = None
    started: str | None = None
    uptime_s: float | None = None


#: How each core is spelled on screen. The console shows the label, never the
#: slug the config_id carries (GL-05).
CORE_LABELS: dict[str, str] = {"open5gs": "Open5GS", "free5gc": "free5GC"}


class CoreHealth(Loose):
    """Whether the core host is serving, and what says otherwise.

    `ok` is three-valued. None means the host did not answer, which is not the
    same as a host answering that it is broken, and the two must not render
    the same way (GL-09).
    """

    ok: bool | None = None
    failing: list[str] = Field(default_factory=list)
    ngap_peers: list[str] = Field(default_factory=list)
    summary: str = ""

    @property
    def peer_text(self) -> str:
        return ", ".join(self.ngap_peers) if self.ngap_peers else "no gNB attached"


class CoreProfile(Loose):
    """What one core differs in: its pool, its data address, its tunnel."""

    name: str = ""
    display: str = ""
    status: str = ""
    host: str | None = None
    ue_pool: str | None = None
    core_data_ip: str | None = None
    tunnel_iface: str | None = None
    amf_n2: str | None = None
    subscriber_db: str | None = None


class CoreActivity(Loose):
    """Signs somebody other than ETHOS has been on the core host.

    `checked` False is the important state: it means nobody looked, which the
    page must show as unknown rather than as all clear.
    """

    checked: bool = False
    findings: list[str] = Field(default_factory=list)
    reason: str = ""


class CoreStale(Loose):
    """A core a dead campaign left on the wrong side, as ETHOS reports it.

    `remedy` is a command for a person to run. The console shows it and does
    nothing with it: switching a core back from a web page would stop whatever
    somebody is in the middle of, and the console does not act on the testbed
    at all (SE-06).
    """

    is_stale: bool = False
    reason: str = ""
    remedy: str = ""


class CoreState(Loose):
    """`GET /core` (B18): which core is running, and what that implies.

    The console never runs core-switch and never reaches the core host. This
    is the whole of what it knows, and the page shows nothing the endpoint did
    not say.
    """

    enabled: bool = False
    core: str | None = None
    selected: str | None = None
    agrees: bool | None = None
    disagreement: str | None = None
    health: CoreHealth = Field(default_factory=CoreHealth)
    health_source: str | None = None
    status: dict[str, Any] | None = None
    profile: CoreProfile | None = None
    profiles: dict[str, CoreProfile] = Field(default_factory=dict)
    activity: CoreActivity = Field(default_factory=CoreActivity)
    stale: CoreStale = Field(default_factory=CoreStale)
    error: str | None = None
    checked_at: str | None = None

    @property
    def known(self) -> bool:
        """Did the host answer at all? A core of None is not Open5GS."""
        return self.core is not None and self.error is None

    @property
    def settled(self) -> bool:
        """Green and not mid-switch: the only state a run may start in.

        `disagreement` is checked as well as `agrees`, so a host that reports
        a split is never settled even if `agrees` somehow says otherwise. The
        conservative reading is the right one: the cost of holding a run back
        for a minute is nothing beside a run attributed to the wrong core.
        """
        return bool(
            self.known and self.agrees and not self.disagreement and self.health.ok
        )

    @property
    def blocker(self) -> str:
        """Why a run must not start, or "" when it may.

        Only the host's own condition, never which core the plan wants: a plan
        for free5GC started while the host runs Open5GS is the ordinary case,
        and ETHOS switches it as part of the job.
        """
        if not self.enabled:
            return ""
        if self.error:
            return f"the core host could not be read: {self.error}"
        if not self.known:
            return "the core host did not say which core it is running"
        if self.disagreement:
            return self.disagreement
        if self.health.ok is False:
            return self.health.summary or "the core is not serving"
        if self.health.ok is None:
            return "the core host did not report its health"
        return ""

    def profile_for(self, name: str | None) -> CoreProfile | None:
        """The profile of a core by name, for a plan that names one."""
        return self.profiles.get(str(name or "").strip().lower())


class StatusSummary(Loose):
    lock: LockPart = Field(default_factory=LockPart)
    deployed: DeployedPart = Field(default_factory=DeployedPart)
    latest_job: JobPart = Field(default_factory=JobPart)
    ue: UePart = Field(default_factory=UePart)
    iperf_server: IperfPart = Field(default_factory=IperfPart)
    freshness: FreshnessPart = Field(default_factory=FreshnessPart)
    api: ApiPart = Field(default_factory=ApiPart)
    core: CoreState = Field(default_factory=CoreState)


class UeEntry(Loose):
    ue: str = ""
    driver: str | None = None
    control_path: str | None = None
    driven: bool = True
    reason: str = ""
    reachable: bool | None = None
    attached: bool | None = None
    ip: str | None = None
    checked_at: str | None = None

    @property
    def state_word(self) -> str:
        """What the row says. `unknown` is a state, never rendered as detached.

        An unreachable handset must not read as "not attached": one is a device
        that did not answer, the other is a device that answered and is idle.
        """
        if self.reachable is None:
            return "unknown"
        if self.attached:
            return "attached"
        if self.attached is None:
            return "unknown"
        return "detached"


class UeList(Loose):
    count: int = 0
    ues: list[UeEntry] = Field(default_factory=list)

    @property
    def driven(self) -> list[UeEntry]:
        return [entry for entry in self.ues if entry.driven]

    @property
    def not_driven(self) -> list[UeEntry]:
        return [entry for entry in self.ues if not entry.driven]


class UeIperf(Loose):
    ue: str = ""
    port: int = 5201
    held: bool = False
    holder: dict[str, Any] | None = None
    default_mode: str | None = None
    checked_at: str | None = None

    @property
    def owner(self) -> str:
        return str((self.holder or {}).get("owner") or "unknown")

    @property
    def describe(self) -> str:
        if not self.held:
            return f"port {self.port} is free"
        holder = self.holder or {}
        return (
            f"{self.owner} iperf3 (pid {holder.get('pid') or '?'}, "
            f"uid {holder.get('uid') or '?'})"
        )


# --- figures on request (B9) --------------------------------------------------


class PlotMetric(Loose):
    """One thing a figure can put on its y axis, as ETHOS describes it.

    Every field comes from `GET /plots/options`. The console keeps no metric
    list of its own: one that drifted would offer a metric ETHOS has dropped, or
    hide one it has gained.
    """

    id: str = ""
    label: str = ""
    unit: str = ""
    axis_label: str = ""
    y_scale: str = "linear"
    field: str = ""
    cross_vendor: bool = True
    has_cap: bool = False
    note: str = ""

    @property
    def display(self) -> str:
        return f"{self.label} ({self.unit})" if self.unit else self.label


class PlotNotOffered(Loose):
    """A metric ETHOS deliberately does not offer, and why.

    Shown rather than hidden: "why can't I plot first-transmission BLER" is
    answered where somebody looks for it, and the answer is that it is OAI-only
    and so not comparable across stacks.
    """

    id: str = ""
    reason: str = ""


class PlotOptions(Loose):
    metrics: list[PlotMetric] = Field(default_factory=list)
    default_metric: str = "throughput"
    kinds: list[str] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    widths: list[str] = Field(default_factory=list)
    y_scales: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    not_offered: list[PlotNotOffered] = Field(default_factory=list)

    def metric(self, metric_id: str | None) -> PlotMetric | None:
        return next((m for m in self.metrics if m.id == metric_id), None)


class PlotSeries(Loose):
    """How one stack is drawn, from ETHOS's own palette."""

    head: str = ""
    label: str = ""
    legend_label: str = ""
    marker: str = ""
    colour: str = "#666666"
    linestyle: str = "-"
    hatch: str = ""
    note: str = ""
    order: int = 99


class PlotSeriesList(Loose):
    ideal_label: str = ""
    order: list[str] = Field(default_factory=list)
    series: list[PlotSeries] = Field(default_factory=list)


class FigureSummary(Loose):
    """One figure in the gallery, as `GET /plots` lists it."""

    figure_id: str = ""
    label: str = ""
    kind: str | None = None
    metric: str | None = None
    width: str | None = None
    created: str | None = None
    made_by: str = "cli"
    n_points: int = 0
    warnings: list[str] = Field(default_factory=list)
    folder: str | None = None

    @property
    def by_console(self) -> bool:
        return self.made_by == "api"

    @property
    def maker(self) -> str:
        """What the chip says. ETHOS calls the console's own requests `api`;
        to somebody reading the gallery the distinction is CLI or Console."""
        return "Console" if self.by_console else "CLI"


class FigureResult(Loose):
    """What `POST /plots` returns: where it landed and what it warns about."""

    figure_id: str = ""
    folder: str | None = None
    warnings: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    regenerated_from: str | None = None

    @property
    def points(self) -> list[dict[str, Any]]:
        return list(self.manifest.get("points") or [])

    @property
    def dropped(self) -> list[dict[str, Any]]:
        """The runs ETHOS left out, with its reason for each.

        Shown beside the figure rather than buried: a point missing because a
        run had no radio summary is a fact about the figure, and a reader who
        cannot see it will read the gap as a measurement.
        """
        selection = self.manifest.get("selection") or {}
        return list(selection.get("dropped") or [])

    @property
    def n_summary(self) -> dict[str, Any]:
        return dict(self.manifest.get("n_summary") or {})

    @property
    def metric(self) -> str:
        return str(self.manifest.get("metric") or "")

    @property
    def caps(self) -> dict[str, Any]:
        return dict(self.manifest.get("mcs_caps") or {})


class QuarantineEntry(Loose):
    """One job held out of normal graph generation, and why.

    `run_ids` is the whole sweep, including any run it created but never
    measured, so the record still describes the job if ETHOS's local `job.json`
    is pruned by retention later.
    """

    job_id: str = ""
    reason: str = ""
    excluded_at: str = ""
    excluded_by: str = ""
    run_ids: list[str] = Field(default_factory=list)
    campaign_id: str | None = None
    config_id: str | None = None
    state: str = ""
    rates: str = ""


class QuarantineList(Loose):
    count: int = 0
    jobs: list[QuarantineEntry] = Field(default_factory=list)
    excluded_run_ids: list[str] = Field(default_factory=list)

    def by_job(self) -> dict[str, QuarantineEntry]:
        """Keyed for the job picker, which asks about one job at a time."""
        return {entry.job_id: entry for entry in self.jobs}


# --- publication -------------------------------------------------------------


class PublishLock(Loose):
    """Whether a publication is running, and who is running it."""

    busy: bool = False
    holder: str | None = None
    what: str | None = None
    since: str | None = None
    pid: int | None = None
    message: str | None = None


class PublishRemote(Loose):
    """What the remote said, when it was asked at all.

    `checked` false is the ordinary case: the status endpoint does not touch
    GitHub unless asked, so that reading this page cannot fail because GitHub
    is down.
    """

    checked: bool = False
    established: bool = False
    remote: str | None = None
    branch: str | None = None
    head: str | None = None
    reason: str | None = None
    message: str | None = None


class PublishRetention(Loose):
    """What retention would offer, counted LOCALLY.

    An upper bound on what a prune would remove: prune additionally requires
    the remote to hold every commit an artifact sits in, and that is not
    computed here.
    """

    considered: int = 0
    eligible: int = 0
    kept: int = 0
    reclaimable_bytes: int = 0


class IncompleteArtifact(Loose):
    artifact_id: str | None = None
    reason: str | None = None


class PublishStatus(Loose):
    """Everything the Publication page reads in one call."""

    configured: bool = False
    reason: str | None = None
    repository: str | None = None
    exists: bool = False
    head: str | None = None
    retention_days: float = 0.0
    artifacts: int = 0
    durable: int = 0
    to_publish: int = 0
    new: int = 0
    changed: int = 0
    incomplete: list[IncompleteArtifact] = Field(default_factory=list)
    retention: PublishRetention = Field(default_factory=PublishRetention)
    lock: PublishLock = Field(default_factory=PublishLock)
    remote: PublishRemote = Field(default_factory=PublishRemote)


class PublishPreview(Loose):
    """What publishing would make durable, and the token that allows it."""

    configured: bool = True
    surveyed: int = 0
    already_durable: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    would_publish: list[dict[str, Any]] = Field(default_factory=list)
    preview_token: str | None = None
    published: bool = False
    detail: str | None = None


class PublishResult(Loose):
    """What a publish actually did, including whether it got upstream.

    `published`, `verified` and `pushed` are separate on purpose. A publication
    can be committed and not verified, or verified and not pushed, and a page
    that collapsed them would be able to report a success nobody got.
    """

    published: bool = False
    verified: bool = False
    pushed: bool = False
    commit: str | None = None
    files_written: int = 0
    push_detail: str | None = None
    detail: str | None = None
    verification: dict[str, Any] = Field(default_factory=dict)
    preview_token: str | None = None


class PublishVerification(Loose):
    """The read-only verification of the durable copy."""

    configured: bool = True
    head: str | None = None
    artifacts: int = 0
    durable: int = 0
    not_durable: int = 0
    verified: bool = False
    missing_files: int = 0
    artifacts_detail: list[dict[str, Any]] = Field(default_factory=list)


class PublishPushResult(Loose):
    """What a push did, or why it did not."""

    pushed: bool = False
    head: str | None = None
    surveyed: int = 0
    detail: str | None = None
    push_detail: str | None = None
    preview_token: str | None = None
    missing_files: list[dict[str, Any]] = Field(default_factory=list)
