// Plain-English wording for the codes the API uses, so the screen never shows internal names like "plan_steps" or
// "DRINKS". Keeping all the wording in one place makes it easy to change or translate later.

// What to show while Navi is using each tool.
export const TOOL_ACTIVITY: Record<string, string> = {
  vector_search: "Searching the official documents",
  get_requirements: "Looking up the requirements",
  get_dependencies: "Checking what must come first",
  plan_steps: "Building your checklist",
  explain_path: "Working out why the order matters",
  query_graph: "Searching the knowledge graph",
  save_checklist: "Saving your checklist",
  update_progress: "Recording your progress",
  set_reminder: "Setting a reminder",
  handoff_to_human: "Passing you to a human adviser",
  remember_profile: "Noting your business details",
  add_business: "Adding your business",
};

export const BUSINESS_TYPES: Record<string, string> = {
  DRINKS: "Packaged fruit drinks",
  PHARM: "Retail pharmacy",
  COSM: "Online cosmetics store",
  FURN: "Furniture business",
};

// The names of the facts Navi can remember about a business.
export const FACT_NAMES: Record<string, string> = {
  business_type: "Kind of business",
  state: "State",
  legal_structure: "Legal structure",
  cac_registered: "Registered with CAC",
  sells_online: "Sells online",
  collects_personal_data: "Collects customers' personal data",
  product_variant: "Products",
  business_name: "Business name",
};

const VALUE_NAMES: Record<string, string> = {
  sole_proprietorship: "Sole proprietorship",
  partnership: "Partnership",
  private_company: "Private limited company",
  public_company: "Public limited company",
  undecided: "Not decided yet",
  resell: "Resells other brands",
  import: "Imports its own brand",
  make_locally: "Makes products locally",
};

// Where Navi learned a fact.
export const SOURCE_NAMES: Record<string, string> = {
  user_stated: "You told Navi",
  progress_update: "From your recorded progress",
  migrated: "Carried over from an earlier version",
  seeded: "Test data",
};

export function factValue(field: string, value: string | boolean): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (field === "business_type") return BUSINESS_TYPES[value] ?? value;
  return VALUE_NAMES[value] ?? value;
}

// Which heading a chat goes under in the sidebar, like a chat app: Today, Yesterday, and so on.
export function dateGroup(iso: string): string {
  const day = new Date(iso);
  if (Number.isNaN(day.getTime())) return "Older";
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const daysAgo = Math.floor((startOfToday.getTime() - new Date(day).setHours(0, 0, 0, 0)) / 86_400_000);
  if (daysAgo <= 0) return "Today";
  if (daysAgo === 1) return "Yesterday";
  if (daysAgo < 7) return "Previous 7 days";
  if (daysAgo < 30) return "Previous 30 days";
  return "Older";
}

export function shortDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
