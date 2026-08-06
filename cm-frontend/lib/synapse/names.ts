// Plain-language names, mirroring the BFF's own maps (D4: plain name in the UI,
// internal id alongside).
//
// DUPLICATED HERE ON PURPOSE, and the duplication is bounded: the BFF names
// things for its JSON consumers and the console names them for a person, and a
// product wording change should not require a Python deploy. The internal id is
// always rendered beside the name, so a mismatch is visible on the screen rather
// than hidden — and the id, not the name, is what appears in logs.
export const ANALYSIS_NAMES: Record<string, string> = {
  dead_stock: "Stock that isn't selling",
  stockout_risk: "Running out before the next delivery",
};

export const CAPABILITY_NAMES: Record<string, string> = {
  current_state: "Current stock and prices",
  daily_series: "Daily sales",
  last_sale_at: "When each product last sold",
  lead_time_distribution: "Supplier lead times",
};

// What each monitor flags, in one line, for an operator who has not read the
// declaration. NOT AN API FIELD: /analyses returns analysis_id, name, version,
// requires, max_rung, thresholds and holdout_percent — there is no description.
// This is UI copy about two known monitors, kept beside ANALYSIS_NAMES for the
// same reason and with the same bounded-duplication argument: a wording change
// should not need a Python deploy.
export const MONITOR_DESCRIPTIONS: Record<string, string> = {
  dead_stock: "Flags products with stock on hand but no recent sales.",
  stockout_risk: "Flags products selling faster than replenishment will cover.",
};
