import React, { useState, useRef } from 'react'
import { searchManga } from '../api'
import './SearchPanel.css'

export default function SearchPanel({ onSelect }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const debounceRef = useRef(null)

  const handleSearch = async (searchQuery) => {
    if (!searchQuery.trim()) {
      setResults([])
      return
    }
    setLoading(true)
    setError('')
    try {
      const data = await searchManga(searchQuery, 5)
      setResults(data.results || [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleInputChange = (e) => {
    const val = e.target.value
    setQuery(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => handleSearch(val), 600)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    clearTimeout(debounceRef.current)
    handleSearch(query)
  }

  return (
    <div className="search-panel">
      <form onSubmit={handleSubmit} className="search-form">
        <input
          type="text"
          value={query}
          onChange={handleInputChange}
          placeholder='Search manga... (e.g., "attack on titan", "one piece")'
          className="search-input"
          autoFocus
        />
        <button type="submit" className="search-btn" disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {loading && (
        <p className="searching-hint">Searching MangaFreak...</p>
      )}

      {error && <div className="error-msg">{error}</div>}

      <div className="results">
        {results.map((manga) => (
          <div
            key={manga.url}
            className="manga-card"
            onClick={() => onSelect(manga)}
          >
            <div className="manga-info">
              <h3 className="manga-title">{manga.title}</h3>
              <div className="manga-meta">
                <span className="tag">MangaFreak</span>
              </div>
              <p className="manga-desc">{manga.url}</p>
            </div>
          </div>
        ))}
      </div>

      {!loading && results.length === 0 && query && (
        <p className="no-results">No results found. Try a different search term.</p>
      )}
    </div>
  )
}
