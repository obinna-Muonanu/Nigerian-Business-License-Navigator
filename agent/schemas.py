"""
It describes the shape of the information the project works with, like a set of blank forms.

The most important ones are:
    the user's business profile: what they sell, which state they're in, whether they're registered, and so on;
    the form the AI fills in when it reads an official document and lists its requirements;
    the fixed lists of allowed values, such as the four business types and the six states we cover.

WHY IT MATTERS
Every other part of the project uses these same forms and lists, so they always agree with each other.
If the AI writes something that isn't on an allowed list (say, a state we don't cover), it's caught right
away instead of causing a wrong answer later.
"""

from typing import Literal

from pydantic import BaseModel, Field

# This pattern recognises the requirement IDs used in the knowledge base, such as R01, R01-SP,
# R02-ST-FCT, D05 or S-OY-01. Both the ingestion step (to find each requirement's section) and the
# reply filter (to keep IDs out of what the user sees) use this one pattern, so they always agree on
# what an ID looks like.
REQUIREMENT_ID_PATTERN = r"(?:R\d{2}(?:-[A-Z]{2,3}){0,2}|[CDNPST]\d{2}|S-[A-Z]{2,3}-\d{2})"

# The fixed lists below use Literal types, which make Pydantic reject anything that isn't on the list.
# That matters most for text a model writes, such as the graph extraction or a remembered profile
# fact: a made-up code gets caught right at the door instead of turning up later in a database query.

# The four kinds of business the knowledge base covers. The codes match the documents' headers.
BusinessType = Literal["DRINKS", "PHARM", "COSM", "FURN"]
# Friendly names for the same codes, used in the prompt and in plans shown to the user.
BUSINESS_TYPE_NAMES: dict[str, str] = {
    "DRINKS": "Packaged fruit drinks (e.g. zobo, juice)",
    "PHARM": "Retail (community) pharmacy",
    "COSM": "Online cosmetics store",
    "FURN": "Furniture business",
}

# The six states that have state-level requirements in the knowledge base. The Literal checks input,
# and the plain list is there for when we need to loop over them, like linking federal requirements
# to every state.
State = Literal["Oyo", "Lagos", "FCT", "Rivers", "Ogun", "Edo"]
STATES: list[str] = ["Oyo", "Lagos", "FCT", "Rivers", "Ogun", "Edo"]

# The conditions that decide when a requirement applies to a business type. Each one is stored on the
# link between a business type and a requirement, not on the requirement itself. That lets the same
# requirement apply "always" to one kind of business but only "sells_online" to another, which is
# exactly how the NDPC privacy notice works.
Condition = Literal[
    "always",                  # every business of this type
    "optional",                # recommended but not mandatory, like a trademark for a pharmacy
    "structure_sole",          # only for a sole proprietorship
    "structure_partnership",   # only for a partnership
    "structure_private",       # only for a private limited company
    "structure_public",        # only for a public limited company
    "company",                 # for a private or a public limited company
    "collects_personal_data",  # only if the business collects customers' personal data
    "sells_online",            # only if the business sells online
    "major_importance",        # only if the NDPC "major importance" check says yes
    "variant_resell",          # only if the business resells registered products (cosmetics)
    "variant_import",          # only if it imports its own brand
    "variant_make_locally",    # only if it makes its products locally
    "not_small_business",      # only once the business grows past the small-business threshold
]

# The allowed values for each part of the user's profile.
LegalStructure = Literal[
    "sole_proprietorship", "partnership", "private_company", "public_company", "undecided"
]
ProductVariant = Literal["resell", "import", "make_locally"]
Language = Literal["english", "pidgin"]

# These are the only facts the agent may remember about a user, and what each one may hold. The
# remember_profile tool rejects anything else, which keeps the personal data we store to a minimum
# (as the NDPA asks). A list means "one of these codes", bool means a yes or no answer, and str means
# a short piece of free text.
PROFILE_FIELDS: dict[str, list[str] | type] = {
    "business_type": list(BUSINESS_TYPE_NAMES),
    "state": STATES,
    "legal_structure": ["sole_proprietorship", "partnership", "private_company", "public_company", "undecided"],
    "cac_registered": bool,
    "sells_online": bool,
    "collects_personal_data": bool,
    "product_variant": ["resell", "import", "make_locally"],
    "business_name": str,
}


class UserProfile(BaseModel):
    """What we know about the user's business. Every fact stays empty until the user tells us.

    An empty value (None) means "we haven't asked yet", which is not the same as False ("we asked,
    and the answer is no"). The planner relies on that difference: when something hasn't been asked,
    it marks the related steps as "depends on your answer" instead of guessing.
    """

    business_type: BusinessType | None = None
    state: State | None = None
    legal_structure: LegalStructure | None = None
    cac_registered: bool | None = None
    sells_online: bool | None = None
    collects_personal_data: bool | None = None
    product_variant: ProductVariant | None = None
    business_name: str | None = None

    def missing_for_planning(self) -> list[str]:
        """List the facts the planner still needs before it can build a reliable checklist.

        The agent uses this to pick the one clarifying question to ask next. The memory block shows
        it too, so a returning user is only asked for what is genuinely still missing.
        """
        needed = ["business_type", "state", "cac_registered", "collects_personal_data"]
        # Cosmetics and furniture plans also depend on whether the business resells, imports or makes
        # its own products, so we need to know that as well.
        if self.business_type in ("COSM", "FURN"):
            needed.append("product_variant")
        return [name for name in needed if getattr(self, name) is None]


# The classes below are the form Claude fills in when it reads a knowledge-base document and pulls out
# the graph (see ingestion/extract_graph.py). They double as the instructions: Strands sends them to
# Claude as a tool definition, so Claude actually reads the field descriptions. The clearer those
# descriptions are, the better the extraction.

class Applicability(BaseModel):
    """One business type a requirement applies to, and the condition under which it applies."""

    business_type: BusinessType
    condition: Condition = Field(description="When this requirement applies to this business type")


class Dependency(BaseModel):
    """A prerequisite: this requirement has to be done after the one named in `requirement_id`.

    The reason is stored on the link in the graph, so the agent can later explain why one step comes
    first, not just that it does.
    """

    requirement_id: str = Field(description="ID of the prerequisite requirement, e.g. R01")
    reason: str = Field(description="One short sentence: why the prerequisite comes first")


class ExtractedRequirement(BaseModel):
    """One registration, licence or permit, as described in a section of a knowledge-base document."""

    id: str = Field(description="Requirement ID exactly as written, e.g. R01, D05, S-OY-01")
    name: str = Field(description="Short human name, e.g. 'NAFDAC product registration'")
    regulator: str = Field(description="Short regulator name, e.g. 'NAFDAC', 'CAC', 'Oyo State Ministry of Trade'")
    applies_to: list[Applicability]
    applies_in: list[Literal["ALL", "Oyo", "Lagos", "FCT", "Rivers", "Ogun", "Edo"]] = Field(
        description="['ALL'] for federal requirements, otherwise the specific states"
    )
    depends_on: list[Dependency] = Field(default_factory=list)
    satisfies: str | None = Field(
        default=None, description="If this is one route that satisfies a parent requirement (e.g. R01-SP satisfies R01), the parent ID"
    )
    documents: list[str] = Field(
        default_factory=list, description="Short names of documents the applicant must provide, e.g. 'Valid ID (NIN)'"
    )
    applicant_information: list[str] = Field(
    default_factory=list,
    description=(
        "All information the applicant must provide, including form fields, "
        "business details, proprietor details, addresses, contact information, "
        "and proposed business names. Do not put physical documents here."
    ))
    recurring: bool = Field(default=False, description="True for renewals, annual returns and other repeating obligations")


class ExtractedDocumentGraph(BaseModel):
    """Everything pulled out of one knowledge-base document. Claude is called once per document."""

    doc_id: str
    requirements: list[ExtractedRequirement]


class CypherQuery(BaseModel):
    """One read-only database query written by the fast model for the text-to-Cypher tool.

    Asking for this fixed shape, rather than free text, means we get back just the query, with no
    markdown fences or chatty explanation to strip off before we check it.
    """

    cypher: str = Field(description="One read-only Cypher query with no semicolons")
    explanation: str = Field(description="One sentence on what the query returns")
