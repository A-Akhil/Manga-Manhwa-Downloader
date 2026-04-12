import React, { useState, useEffect, useRef } from 'react'
import { getJobs, cancelJob } from '../api'
import './DownloadQueue.css'

export default function DownloadQueue() {
  const [jobs, setJobs] = useState([])
  const intervalRef = useRef(null)

  useEffect(() => {
    fetchJobs()
    intervalRef.current = setInterval(fetchJobs, 2000)
    return () => clearInterval(intervalRef.current)
  }, [])

  const fetchJobs = async () => {
    try {
      const data = await getJobs()
      setJobs(data.jobs || [])
    } catch (e) {
      // Silently retry
    }
  }

  const handleCancel = async (jobId) => {
    try {
      await cancelJob(jobId)
      fetchJobs()
    } catch (e) {
      // Ignore
    }
  }

  const statusColor = (status) => {
    switch (status) {
      case 'completed': return 'var(--success)'
      case 'failed': return 'var(--danger)'
      case 'running': return 'var(--accent)'
      case 'cancelled': return 'var(--text-dim)'
      default: return 'var(--warning)'
    }
  }

  if (jobs.length === 0) {
    return (
      <div className="queue-empty">
        <div className="empty-icon">&#128230;</div>
        <h3>No downloads yet</h3>
        <p>Search for a manga and start downloading!</p>
      </div>
    )
  }

  return (
    <div className="download-queue">
      <h2 className="dq-title">Downloads</h2>
      <div className="job-list">
        {jobs.map((job) => (
          <div key={job.id} className={`job-card job-${job.status}`}>
            <div className="job-header">
              <h3 className="job-title">{job.manga_title}</h3>
              <span
                className="job-status"
                style={{ color: statusColor(job.status) }}
              >
                {job.status}
              </span>
            </div>

            <div className="job-details">
              <span>{job.chapter_count} chapter{job.chapter_count !== 1 ? 's' : ''}</span>
              <span className="job-format">{job.format.toUpperCase()}</span>
              <span className="job-id">#{job.id}</span>
            </div>

            {job.status === 'running' && (
              <div className="progress-container">
                <div className="progress-bar">
                  <div
                    className="progress-fill"
                    style={{ width: `${Math.min(job.progress, 100)}%` }}
                  />
                </div>
                <span className="progress-text">
                  {job.downloaded_pages}/{job.total_pages} pages ({Math.round(job.progress)}%)
                </span>
              </div>
            )}

            {job.status === 'completed' && (
              <div className="job-complete">
                Download complete! {job.downloaded_pages} pages saved.
                {job.failed_chapters > 0 && (
                  <span className="partial-warning">
                    {' '}({job.failed_chapters} chapter{job.failed_chapters > 1 ? 's' : ''} failed)
                  </span>
                )}
              </div>
            )}

            {job.status === 'failed' && (
              <div className="job-failed-detail">
                <div className="job-failed-icon">&#10007;</div>
                <div>
                  <strong>Download failed</strong>
                  {job.downloaded_pages > 0 && (
                    <p>{job.downloaded_pages} pages saved before failure</p>
                  )}
                  {job.failed_pages > 0 && (
                    <p>{job.failed_pages} pages could not be downloaded</p>
                  )}
                  {job.failed_chapters > 0 && (
                    <p>{job.failed_chapters} chapter{job.failed_chapters > 1 ? 's' : ''} failed to download</p>
                  )}
                </div>
              </div>
            )}

            {job.error && (
              <div className="job-error">{job.error}</div>
            )}

            {(job.status === 'queued' || job.status === 'running') && (
              <button
                className="cancel-btn"
                onClick={() => handleCancel(job.id)}
              >
                Cancel
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
