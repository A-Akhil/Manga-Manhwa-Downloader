const BASE = '/api';

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function searchManga(query, limit = 10) {
  return request(`/search?q=${encodeURIComponent(query)}&limit=${limit}`);
}

export async function getChapters(mangaUrl) {
  return request(`/chapters?manga_url=${encodeURIComponent(mangaUrl)}`);
}

export async function getChapterImages(chapterUrl) {
  return request(`/images?chapter_url=${encodeURIComponent(chapterUrl)}`);
}

export async function startDownload(mangaUrl, mangaTitle, chapterUrls, format) {
  return request('/download', {
    method: 'POST',
    body: JSON.stringify({
      manga_url: mangaUrl,
      manga_title: mangaTitle,
      chapter_urls: chapterUrls,
      format,
    }),
  });
}

export async function getJobs() {
  return request('/jobs');
}

export async function getJob(jobId) {
  return request(`/jobs/${jobId}`);
}

export async function cancelJob(jobId) {
  return request(`/jobs/${jobId}`, { method: 'DELETE' });
}

export async function convertManga(mangaTitle, format) {
  return request('/convert', {
    method: 'POST',
    body: JSON.stringify({ manga_title: mangaTitle, format }),
  });
}

export async function getDownloads() {
  return request('/downloads');
}
