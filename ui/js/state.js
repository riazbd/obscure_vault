export const state = {
  currentJobId: null,
  eventSource: null,   // active EventSource for main job (SSE)
  pollInterval: null,  // fallback polling interval (used when SSE unavailable)
  lastLogLength: 0,
  currentResult: null,
  aiScriptPoll: null,
  harvestPoll: null,
  reviewPoll: null,
  thumbPoll: null,
  _schedState: null
};