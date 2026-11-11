// The landing page's worked example. SYNTHETIC: the publisher, the bulletin and every figure are invented for this page,
// and no analysis was run to produce it. It shows the shape of a result (quoted evidence, a labelled interpretation and
// what remains unknown, kept apart), never a measured or real outcome.

export const EXAMPLE_LABEL = "Synthetic example, written for this page. The publisher, the bulletin and every figure " +
  "are invented, and no analysis was run to produce it.";

export const EXAMPLE = {
  publisher: "Harbour Valley Statistics Office (fictional)",
  headline: "Monthly freight bulletin, September",
  text: "Container throughput at the Harbour Valley ports fell 4.2 percent from August. Two berths were closed for " +
    "maintenance for eleven days during the month. Throughput for the third quarter as a whole was 1.1 percent " +
    "above the second quarter. The Office expects the maintenance work to be complete by mid-October.",
  established: [
    { basis: "Data reported", statement: "Container throughput fell 4.2 percent from August.",
      quote: "Container throughput at the Harbour Valley ports fell 4.2 percent from August." },
    { basis: "Action reported", statement: "Two berths were closed for maintenance for eleven days.",
      quote: "Two berths were closed for maintenance for eleven days during the month." },
    { basis: "Data reported", statement: "Third-quarter throughput was above the second quarter's.",
      quote: "Throughput for the third quarter as a whole was 1.1 percent above the second quarter." },
    { basis: "Publisher's forecast", statement: "The Office expects the maintenance to end by mid-October.",
      quote: "The Office expects the maintenance work to be complete by mid-October." },
  ],
  interpretation: "The monthly fall may reflect the berth closures more than weaker demand, since the quarter as a " +
    "whole was still above the one before.",
  basedOn: "Relies on statements 1, 2 and 3.",
  assumptions: ["The two closed berths normally carry a meaningful share of the ports' containers."],
  competing: [{ explanation: "Demand for shipping weakened in September.",
                distinguish: "Throughput at nearby ports with no closures over the same weeks." }],
  missing: ["How much traffic the two berths usually handle."],
  tests: [{ check: "October's bulletin, once the berths reopen.",
            against: "Throughput stays low after the maintenance ends." }],
};
