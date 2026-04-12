import React, { useState, useEffect } from 'react'
import { getChapters, startDownload } from '../api'
import './ChapterSelector.css'

export default function ChapterSelector({ manga, onBack, onDownloadStarted }) {
  const [chapters, setChapters] = useState([])
  const [totalPagesEstimate, setTotalPagesEstimate] = useState(0)
  const [selected, setSelected] = useState(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [format, setFormat] = useState('images')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    loadChapters()
  }, [manga.url])

  const loadChapters = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await getChapters(manga.url)
      setChapters(data.chapters || [])
      setTotalPagesEstimate(data.total_pages_estimate || 0)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const toggleChapter = (chapterUrl) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(chapterUrl)) next.delete(chapterUrl)
      else next.add(chapterUrl)
      return next
    })
  }

  const selectAll = () => {
    if (selected.size === chapters.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(chapters.map((c) => c.url)))
    }
  }

  const selectRange = () => {
    const range = prompt('Enter chapter range (e.g., 1-10):')
    if (!range) return
    const [startStr, endStr] = range.split('-')
    const start = parseFloat(startStr)
    const end = parseFloat(endStr)
    if (isNaN(start) || isNaN(end)) return
    const ids = chapters
      .filter((c) => {
        const num = parseFloat(c.chapter)
        return !isNaN(num) && num >= start && num <= end
      })
      .map((c) => c.url)
    setSelected(new Set(ids))
  }

  const selectedPagesEstimate = chapters
    .filter((c) => selected.has(c.url))
    .reduce((sum, c) => sum + (c.pages || 0), 0)

  const handleDownload = async () => {
    if (selected.size === 0) return
    setSubmitting(true)
    setError('')
    try {
      await startDownload(manga.url, manga.title, [...selected], format)
      onDownloadStarted()
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <div className="loading">Loading chapters...</div>

  return (
    <div className="chapter-selector">
      <div className="cs-header">
        <button className="back-btn" onClick={onBack}>&larr; Back to search</button>
        <div className="cs-title-row">
          <div>
            <h2>{manga.title}</h2>
            <p className="cs-meta">
              {chapters.length} chapters &middot; ~{totalPagesEstimate.toLocaleString()} pages
            </p>
            <p className="cs-verified">{manga.url}</p>
          </div>
        </div>
      </div>

      {error && <div className="error-msg">{error}</div>}

      {chapters.length === 0 && !error && (
        <div className="no-chapters-warning">
          No chapters found for this manga.
        </div>
      )}

      {chapters.length > 0 && (
        <>
          <div className="cs-controls">
            <div className="cs-actions">
              <button className="ctrl-btn" onClick={selectAll}>
                {selected.size === chapters.length ? 'Deselect All' : 'Select All'}
              </button>
              <button className="ctrl-btn" onClick={selectRange}>Select Range</button>
              <span className="selected-count">
                {selected.size} selected
                {selectedPagesEstimate > 0 && ` (~${selectedPagesEstimate} pages)`}
              </span>
            </div>

            <div className="cs-format">
              <label>Format:</label>
              <select value={format} onChange={(e) => setFormat(e.target.value)}>
                <option value="images">Images Only</option>
                <option value="pdf">PDF</option>
                <option value="cbz">CBZ</option>
                <option value="both">PDF + CBZ</option>
              </select>
            </div>
          </div>

          <div className="chapter-list">
            {chapters.map((ch) => (
              <div
                key={ch.url}
                className={`chapter-item ${selected.has(ch.url) ? 'selected' : ''} ${ch.pages === 0 ? 'zero-pages' : ''}`}
                onClick={() => toggleChapter(ch.url)}
              >
                <div className="ch-checkbox">
                  {selected.has(ch.url) ? '\u2611' : '\u2610'}
                </div>
                <div className="ch-info">
                  <span className="ch-num">Ch. {ch.chapter}</span>
                  <span className="ch-title">{ch.title}</span>
                </div>
                <div className="ch-meta">
                  {ch.pages > 0
                    ? <span>{ch.pages} pg</span>
                    : <span className="ch-warning" title="Page count unknown">? pg</span>
                  }
                  <span className="ch-group">MangaFreak</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {selected.size > 0 && (
        <div className="download-bar">
          <button
            className="download-btn"
            onClick={handleDownload}
            disabled={submitting}
          >
            {submitting
              ? 'Starting...'
              : `Download ${selected.size} Chapter${selected.size > 1 ? 's' : ''} as ${format.toUpperCase()}`}
          </button>
        </div>
      )}
    </div>
  )
}
