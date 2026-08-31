"""Document bodies, as parameterised templates.

**On LLM generation.** The design proposes generating the ~150 scenario-critical
documents once with a language model, reviewing them by hand, and committing them as
fixtures — never generating corpus text at demo time. The freezing half of that is
non-negotiable and is honoured: the corpus is generated deterministically from the
event ledger and committed, so no model call is ever on the critical path.

The generating half is done with parameterised templates rather than a model, because
this build runs with `LLM_PROVIDER=mock` and no API key. Templates carry a cost: less
linguistic variety than a model would produce. They also carry a benefit the design
wanted anyway — every document is reproducible from its event, so a corpus regenerated
after a ledger change stays consistent with the numbers by construction rather than by
review. Where variety matters for retrieval (a story rewritten across six outlets),
the templates vary the framing, the ordering and the vocabulary rather than only the
slots.
"""

from __future__ import annotations

OPS_INCIDENT = [
    (
        "{severity} incident at {warehouse}: {summary}",
        "Raised {publish_date} by {author}.\n\n"
        "{warehouse} reported {summary} beginning {start_date}. Outbound picking is "
        "running at approximately {capacity_pct}% of plan. Affected lines are being "
        "held rather than short-shipped where an alternate DC can cover.\n\n"
        "Mitigation: transfers from {alternate} authorised for the top lost-revenue "
        "SKUs. Engineering on site. Next update at shift change.\n\n"
        "Reported by {author} ({email}).",
    ),
    (
        "{warehouse} - {summary} (ticket {ticket})",
        "Ticket {ticket} opened {publish_date}.\n\n"
        "Since {start_date} the site has been unable to move more than about "
        "{capacity_pct}% of daily demand. Stock on hand is unaffected; this is a "
        "throughput constraint, not a shortage.\n\n"
        "Regions served from this site will see fill rate fall until the line is "
        "restored. {alternate} is picking up part of the shortfall at a transfer "
        "penalty.\n\nOwner: {author}, {email}.",
    ),
]

PRICING_MEMO = [
    (
        "{category} list price revision, effective {effective_date}",
        "Circulated {publish_date} by {author}.\n\n"
        "Following the input-cost review, list prices across {category} will move by "
        "{change_pct} with effect from {effective_date}. Trade terms are unchanged. "
        "Regions in scope: {regions}.\n\n"
        "Commercial teams should expect a volume response; the elasticity assumption "
        "used in the plan is unchanged from last cycle. No end date is set - this is "
        "a permanent revision to the list.\n\n"
        "Questions to {author} ({email}).",
    ),
    (
        "Promotion: {category}, {regions}",
        "Issued {publish_date}.\n\n"
        "A {change_pct} promotional adjustment runs on {category} in {regions} from "
        "{effective_date}. Funding is from the quarterly trade budget.\n\n"
        "Please note the end date has not been confirmed with the planning tool and "
        "may need to be entered retrospectively.\n\nPrepared by {author}.",
    ),
]

CAMPAIGN_BRIEF = [
    (
        "{channel} budget change - {change_pct}",
        "Circulated {publish_date} by {author}.\n\n"
        "{channel} spend will move by {change_pct} from {effective_date} as part of "
        "the {reason}. Other channels are unaffected in this change.\n\n"
        "Expect the demand effect to build over roughly two weeks rather than land "
        "immediately, in line with the channel's adstock profile. Weekly reporting "
        "will show the spend change before it shows the revenue change.\n\n"
        "Owner: {author} ({email}).",
    ),
    (
        "Media plan note: {channel}",
        "{publish_date}.\n\n"
        "Confirming the {change_pct} adjustment to {channel} effective "
        "{effective_date}. Rationale: {reason}.\n\n"
        "Attribution reporting will lag the change by at least one drop, and the "
        "first two weeks after the change sit inside the restatement window.\n\n"
        "{author}",
    ),
]

SUPPLIER_EMAIL = [
    (
        "Re: inbound schedule, {category}",
        "From: {author} <{email}>\nSent: {publish_date}\n\n"
        "Following up on the constraint we discussed. We are still working through "
        "the backlog and I would not want to commit to full volumes before "
        "{effective_date}. Partial allocation continues in the meantime.\n\n"
        "I appreciate this is not what your ops team was told earlier this week.\n\n"
        "Regards,\n{author}",
    ),
]

NEWS_ARTICLE = [
    (
        "{competitor} steps up in {category} with new range",
        "{outlet} | {publish_date}\n\n"
        "{competitor} has announced a expanded {category} range, with distribution "
        "beginning {effective_date}. The move follows a period of share gains for "
        "mid-priced entrants in the segment.\n\n"
        "Analysts expect the category's price architecture to come under pressure "
        "through the next two quarters, although the immediate volume impact is "
        "likely to be modest.\n\n"
        "Meridian Consumer Brands declined to comment.",
    ),
    (
        "{category} shake-up as {competitor} widens distribution",
        "{outlet} reports, {publish_date}\n\n"
        "A new {category} push from {competitor} reaches shelves from "
        "{effective_date}. The launch is the most significant in the segment this "
        "year and is backed by a heavy media commitment.\n\n"
        "Incumbents including Meridian Consumer Brands hold the majority of the "
        "segment, and the challenge to that position is not expected to register "
        "immediately.",
    ),
    (
        "Category watch: {competitor} targets {category}",
        "{outlet}, {publish_date}\n\n"
        "{competitor}'s {category} announcement lands {effective_date}. Trade sources "
        "describe the pricing as aggressive relative to established brands.\n\n"
        "Whether the move translates into share will depend on execution at the "
        "shelf, where Meridian Consumer Brands retains the stronger position.",
    ),
]

WEEKLY_REVIEW = [
    (
        "Weekly business review - w/c {publish_date}",
        "Prepared by {author}.\n\n"
        "{headline_claim}\n\n"
        "Actions carried forward from last week remain open. Regional teams to "
        "confirm their read by Wednesday.",
    ),
]

WEEKLY_REVIEW_CLAIMS = [
    "Revenue was softer than plan this week. The drop is clearly seasonal and should "
    "correct itself next week without intervention.",
    "The shortfall looks like a pricing issue to me - we went out too high on the "
    "category and the market has told us so.",
    "Nothing structural in this week's numbers. Weather in the north, most likely.",
    "Volume is where the problem is, not price. Supply has been unreliable and the "
    "commercial team is carrying the consequence.",
]
"""Human interpretations, some of them confidently wrong.

Good demo material: the engine's evidence disagrees with the human narrative, and it
says so rather than deferring to it.
"""

OUTLETS = (
    "Consumer Trade Weekly",
    "The Retail Ledger",
    "FMCG Briefing",
    "Shelf & Supply",
    "Market Notes Daily",
    "Category Review",
)
"""Fictional trade outlets. A syndicated story appears across three to six of them."""
