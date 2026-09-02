// SCRUM-80 entrypoint for the current-feature EKS monolith boundary campaign.
// The shared adaptive implementation keeps one request/summary contract while
// this stable filename lets the Runner lineage prove which campaign was run.
export { options, mix, handleSummary } from './eks-scale-capacity.js';
