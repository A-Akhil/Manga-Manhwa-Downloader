import React, { useState } from 'react'
import SearchPanel from './components/SearchPanel'
import ChapterSelector from './components/ChapterSelector'
import DownloadQueue from './components/DownloadQueue'
import './App.css'

const TABS = ['Search', 'Downloads']

export default function App() {
  const [tab, setTab] = useState('Search')
  const [selectedManga, setSelectedManga] = useState(null)

  const handleMangaSelect = (manga) => {
    setSelectedManga(manga)
  }

  const handleBack = () => {
    setSelectedManga(null)
  }

  const handleDownloadStarted = () => {
    setTab('Downloads')
    setSelectedManga(null)
  }

  return (
    <div className="app">
      <header className="header">
        <h1 className="logo">Manga Downloader</h1>
        <span className="version">v2.0</span>
        <nav className="tabs">
          {TABS.map((t) => (
            <button
              key={t}
              className={`tab ${tab === t ? 'active' : ''}`}
              onClick={() => { setTab(t); setSelectedManga(null) }}
            >
              {t}
            </button>
          ))}
        </nav>
      </header>

      <main className="main">
        {tab === 'Search' && !selectedManga && (
          <SearchPanel onSelect={handleMangaSelect} />
        )}
        {tab === 'Search' && selectedManga && (
          <ChapterSelector
            manga={selectedManga}
            onBack={handleBack}
            onDownloadStarted={handleDownloadStarted}
          />
        )}
        {tab === 'Downloads' && <DownloadQueue />}
      </main>
    </div>
  )
}
