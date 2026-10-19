# Local scientific-QPU comparison

The active simulator keeps its original `/thermal_lab/` route. This revision is local and confined to this page and its own model, styles, tests and documentation. The main website structure, navigation, comparison and task/layout demonstrations are retained.

The slide catalog anchors 2035, and the forecast covers 2035–2045. The five-year scenario budget is 2035–2039, not a window ending before quantum deployment. The deck supplies a duration, not calendar dates. A separately labelled conservative $30B cumulative guardrail also covers later forecast years.

Both fleets retain the same physical AI and scientific GPUs, source bandwidth/memory, CPU router and fixed task volume. QPUs add scientific execution capacity without retiring GPUs or earning resale credits. Installed peak power includes both fleets and is checked against 500 MW; it is not annual energy.

Annual GPU energy separates an idle floor from dynamic activity. The editable default 3%/year dynamic-energy reduction is a software/serving-efficiency what-if, not a prediction from the slides, a Moore’s-law extrapolation or a free hardware upgrade. It applies equally to GPU-only and hybrid, compounds from 2035, and does not increase memory, bandwidth or validated task capacity. Set 0% for fixed efficiency. No automatic demand growth or QPU performance growth is assumed.

The energy bridge is: fixed-efficiency GPU-only energy − shared GPU efficiency improvement − avoided scientific GPU activity + whole-wing QPU and external host energy = hybrid energy. Retained GPUs keep their idle floor. CPU/storage and all installed QPUs remain powered, even if unsuitable or unused. Energy per task uses the same fixed task mix and denominator on both sides; scientific jobs are not treated as equivalent to chat prompts when interpreting that average.

A classical CPU routes only supported, assumed-matched-quality scientific kernels within accepted QPU capacity. It compares avoided GPU energy at the selected year’s efficiency with whole-wing energy. Unavoidable installed maintenance is included in the annual cost verdict, not used to leave energy-saving installed hardware idle. Every deployed year must have both lower energy and lower full electricity-plus-maintenance running costs; cost, energy, grid, facility cooling density and budget failures remain visible.

QPU complete-system prices already contain internal coolers and controls. Editable cost shares split the system subtotal once. Commissioning, networking and site infrastructure are extra allowances; external site PUE is applied once to system and host power. Inflation is optional, off by default, and affects operating bills from 2035 without changing joules, purchases or nominal budget.

The main-page equipment comparison is explicitly a new-build GPU-or-QPU alternative and excludes broader capital and operating costs. The forecast is an additive wing and uses full allowances, retained idle draw and the optional speculative-decoding assumption. Task-flow and layout-comparison animations illustrate scheduling only; they do not contribute energy savings to the annual forecast.

Task 2 chiplet-layout, HotSpot and chip-temperature controls are removed from the website. Only facility cooling and quantum refrigeration remain. Archived research code is unchanged.

Scientific GPU-hours/job, QPU power/throughput/price and matched-quality eligibility are team scenario inputs, not independently validated measurements. Queue tails, full end-to-end SLOs, failure reserves, physical floor space and official scoring remain unverified.
