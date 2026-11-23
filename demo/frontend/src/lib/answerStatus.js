// Use the explicit model/pipeline status, never infer correctness from prose.
export function answerStatus(result = {}) {
  return result.answerStatus || result.runDetails?.runStatus ||
    (result.insufficient ? 'INSUFFICIENT_SOURCES' : result.partial ? 'PARTIAL' : result.error ? 'ERROR' : null);
}
export const answerLabels = {
  ANSWERED: 'Answered', PARTIAL: 'Partial answer',
  INSUFFICIENT_SOURCES: 'Insufficient source information',
  PROMPT_ANSWER: 'Basic answer · not validated', ERROR: 'Answer failed',
};
