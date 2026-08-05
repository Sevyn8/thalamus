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
