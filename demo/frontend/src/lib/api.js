export async function api(path, body) {
  const response = await fetch(`/api${path}`, body === undefined ? {cache: 'no-store'} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({error: {message: 'The backend returned an invalid response.'}}));
  if (!response.ok) throw new Error(data.error?.message || `Request failed (${response.status}).`);
  return data;
}
export const seconds = value => value == null ? 'Unknown' : `${(value / 1000).toFixed(2)} s`;
export const count = value => value == null ? 'Unknown' : Number(value).toLocaleString('en');
export const activeTask = task => Boolean(task && !['completed', 'failed', 'cancelled'].includes(task.status));
export function downloadUrl(id, format) { return `/api/tasks/${id}/export?format=${format}`; }
