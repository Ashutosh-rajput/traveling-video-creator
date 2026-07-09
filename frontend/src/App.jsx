import React, { useState, useEffect } from 'react';
import { 
  Search, 
  Image as ImageIcon, 
  Video as VideoIcon, 
  MapPin, 
  Compass, 
  X, 
  ExternalLink,
  ChevronRight,
  Loader2,
  AlertCircle
} from 'lucide-react';
import './App.css';
import ReactMarkdown from 'react-markdown';

function App() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState(0);
  const [error, setError] = useState(null);
  
  // Response states
  const [message, setMessage] = useState('');
  const [pics, setPics] = useState([]);
  const [videos, setVideos] = useState([]);
  const [toolData, setToolData] = useState([]);
  const [videoScript, setVideoScript] = useState('');
  
  // UI states
  const [debugMode, setDebugMode] = useState(false);
  
  // UI states
  const [activeTab, setActiveTab] = useState('photos');
  const [lightboxItem, setLightboxItem] = useState(null);

  const stages = [
    "Consulting Gemma Travel Assistant...",
    "Searching media providers...",
    "Extracting photos and videos...",
    "Formatting final results..."
  ];

  // Stage timer simulation during loading
  useEffect(() => {
    let interval;
    if (loading) {
      setLoadingStage(0);
      interval = setInterval(() => {
        setLoadingStage((prev) => {
          if (prev < stages.length - 1) return prev + 1;
          return prev;
        });
      }, 3000);
    } else {
      setLoadingStage(0);
    }
    return () => clearInterval(interval);
  }, [loading]);

  const handleSearch = async (e, searchQuery = query) => {
    if (e) e.preventDefault();
    if (!searchQuery.trim()) return;

    setLoading(true);
    setError(null);
    setMessage('');
    setPics([]);
    setVideos([]);
    setToolData([]);
    setVideoScript('');

    try {
      const response = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ message: searchQuery, debug: debugMode }),
      });

      if (!response.ok) {
        throw new Error('Failed to connect to the backend agent service.');
      }

      const data = await response.json();
      setMessage(data.message || '');
      setPics(data.pics || []);
      setVideos(data.videos || []);
      setToolData(data.tool_data || []);
      setVideoScript(data.video_script || '');
      
      // Auto switch tab to photos if videos are empty or vice-versa
      if (data.pics && data.pics.length > 0) {
        setActiveTab('photos');
      } else if (data.videos && data.videos.length > 0) {
        setActiveTab('videos');
      }
    } catch (err) {
      console.error(err);
      setError(err.message || 'An error occurred while fetching search results.');
    } finally {
      setLoading(false);
    }
  };

  const handleQuickSearch = (term) => {
    setQuery(term);
    handleSearch(null, term);
  };

  return (
    <div className="dashboard-container font-outfit">
      <div className="glow-spot-1"></div>
      
      {/* Header */}
      <header className="app-header animate-fade-in">
        <div className="app-title-wrapper">
          <div className="app-logo">
            <Compass size={32} />
          </div>
          <h1 className="app-title">Travel Media Scout</h1>
        </div>
        <p className="app-subtitle">Powered by Google Gemma & LangChain Agent layer</p>
      </header>

      {/* Search Input Card */}
      <div className="search-card-wrapper animate-fade-in" style={{ animationDelay: '0.1s' }}>
        <form onSubmit={handleSearch} className="search-form">
          <div className="search-input-wrapper">
            <Search size={22} className="search-input-icon" />
            <input
              type="text"
              placeholder="e.g. Find photos of Goa beaches or Plan a 3-day Paris trip..."
              className="search-input"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              disabled={loading}
            />
          </div>
          <button type="submit" className="search-btn" disabled={loading}>
            {loading ? (
              <Loader2 size={18} className="stage-spinner" />
            ) : (
              <>
                <span>Search</span>
                <ChevronRight size={18} />
              </>
            )}
          </button>
        </form>

        {/* Suggested Searches */}
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'center', marginTop: '16px', flexWrap: 'wrap' }}>
          {['Goa Beaches', 'Paris Eiffel Tower', 'Bali Highlights', 'New York City Skyline'].map((term) => (
            <button
              key={term}
              onClick={() => handleQuickSearch(term)}
              className="tab-btn"
              style={{ fontSize: '0.85rem', padding: '6px 14px' }}
              disabled={loading}
            >
              <MapPin size={12} />
              <span>{term}</span>
            </button>
          ))}
        </div>

        {/* Debug Toggle */}
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '20px' }}>
          <button
            type="button"
            onClick={() => setDebugMode(!debugMode)}
            className={`tab-btn ${debugMode ? 'active' : ''}`}
            style={{ 
              fontSize: '0.85rem', 
              padding: '6px 16px', 
              borderRadius: '8px', 
              border: debugMode ? '1px solid rgba(168, 85, 247, 0.4)' : '1px solid var(--border-glass)', 
              background: debugMode ? 'rgba(168, 85, 247, 0.1)' : 'rgba(15, 23, 42, 0.3)' 
            }}
          >
            <span style={{ 
              display: 'inline-block', 
              width: '8px', 
              height: '8px', 
              borderRadius: '50%', 
              background: debugMode ? '#c084fc' : '#64748b', 
              marginRight: '8px',
              boxShadow: debugMode ? '0 0 8px #c084fc' : 'none'
            }}></span>
            <span style={{ color: debugMode ? '#c084fc' : 'var(--text-secondary)' }}>Debug Mode: {debugMode ? 'ON' : 'OFF'}</span>
          </button>
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="glass-card animate-fade-in" style={{ padding: '20px', display: 'flex', alignItems: 'center', gap: '12px', borderLeft: '4px solid #ef4444', maxWidth: '750px', margin: '0 auto 40px auto' }}>
          <AlertCircle size={24} style={{ color: '#ef4444' }} />
          <div>
            <p style={{ fontWeight: '600', color: '#f8fafc' }}>Search Failed</p>
            <p style={{ color: '#94a3b8', fontSize: '0.9rem' }}>{error}</p>
          </div>
        </div>
      )}

      {/* Results Section */}
      {(loading || message || pics.length > 0 || videos.length > 0) && (
        <div className="results-wrapper">
          
          {/* Agent Loading Skeletal */}
          {loading && (
            <div className="glass-card agent-loading-card animate-glow">
              <div className="loading-line header"></div>
              <div className="loading-line body-1"></div>
              <div className="loading-line body-2"></div>
              <div className="loading-line body-3"></div>
              <div className="loading-stages">
                {stages.map((stage, idx) => (
                  <div key={idx} className="stage-item" style={{ opacity: idx <= loadingStage ? 1 : 0.4 }}>
                    {idx < loadingStage ? (
                      <span className="stage-check">✓</span>
                    ) : idx === loadingStage ? (
                      <span className="stage-spinner"></span>
                    ) : (
                      <span style={{ width: '16px', display: 'inline-block', textAlign: 'center' }}>○</span>
                    )}
                    <span>{stage}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Agent Chat Response Block */}
          {!loading && message && (
            <div className="glass-card agent-response-card animate-fade-in">
              <div className="agent-header">
                <div className="agent-avatar">
                  <Compass size={20} />
                </div>
                <div className="agent-name">Gemma Scout Agent</div>
              </div>
              <div className="agent-message">
                <ReactMarkdown>{message}</ReactMarkdown>
              </div>
            </div>
          )}

          {/* Suggested Video Narration Script */}
          {!loading && videoScript && (
            <div className="glass-card animate-fade-in" style={{ padding: '24px', marginTop: '20px', borderLeft: '4px solid var(--accent-indigo)', background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.05) 0%, rgba(3, 7, 18, 0.4) 100%)' }}>
              <div className="agent-header" style={{ marginBottom: '12px' }}>
                <div className="agent-avatar" style={{ background: 'rgba(99, 102, 241, 0.15)', color: 'var(--accent-indigo)' }}>
                  <VideoIcon size={20} />
                </div>
                <div className="agent-name" style={{ fontWeight: '700', letterSpacing: '0.025em', textTransform: 'uppercase', fontSize: '0.8rem', color: '#a5b4fc' }}>
                  🎥 Suggested Video Script Narration
                </div>
              </div>
              <div style={{ fontFamily: 'var(--font-outfit)', fontSize: '1.05rem', color: '#e2e8f0', lineHeight: '1.7', fontStyle: 'italic', paddingLeft: '8px', whiteSpace: 'pre-line' }}>
                {videoScript}
              </div>
            </div>
          )}

          {/* Media Galleries */}
          {!loading && (pics.length > 0 || videos.length > 0) && (
            <div className="media-gallery-section animate-fade-in" style={{ animationDelay: '0.1s' }}>
              
              {/* Tab Selector */}
              <div className="gallery-tabs">
                <button 
                  className={`tab-btn ${activeTab === 'photos' ? 'active' : ''}`}
                  onClick={() => setActiveTab('photos')}
                >
                  <ImageIcon size={18} />
                  <span>Photos ({pics.length})</span>
                </button>
                <button 
                  className={`tab-btn ${activeTab === 'videos' ? 'active' : ''}`}
                  onClick={() => setActiveTab('videos')}
                >
                  <VideoIcon size={18} />
                  <span>Videos ({videos.length})</span>
                </button>
              </div>

              {/* Photos Gallery */}
              {activeTab === 'photos' && (
                pics.length > 0 ? (
                  <div className="media-grid">
                    {pics.map((item, index) => (
                      <div 
                        key={index} 
                        className="media-card"
                        onClick={() => setLightboxItem({ type: 'photo', url: item.url })}
                      >
                        <img src={item.url} alt={item.label || `Scout Photo ${index + 1}`} className="media-image" loading="lazy" />
                        <div className="media-overlay" style={{ transform: 'none', background: 'linear-gradient(to top, rgba(3, 7, 18, 0.95) 0%, rgba(3, 7, 18, 0.3) 100%)' }}>
                          <div className="creator-info">
                            <span className="creator-name">{item.label}</span>
                            <span className="creator-attribution">High Resolution Photo</span>
                          </div>
                          <a 
                            href={item.url} 
                            target="_blank" 
                            rel="noreferrer" 
                            className="download-link"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ExternalLink size={16} />
                          </a>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-gallery glass-card">
                    <ImageIcon size={48} className="empty-icon" />
                    <p className="empty-text">No pictures found for this location.</p>
                  </div>
                )
              )}

              {/* Videos Gallery */}
              {activeTab === 'videos' && (
                videos.length > 0 ? (
                  <div className="media-grid">
                    {videos.map((item, index) => (
                      <div 
                        key={index} 
                        className="media-card"
                        onClick={() => setLightboxItem({ type: 'video', url: item.url })}
                      >
                        <div className="video-card-preview">
                          <video 
                            src={item.url} 
                            className="media-image" 
                            muted 
                            playsInline 
                            onMouseOver={(e) => e.target.play()}
                            onMouseOut={(e) => { e.target.pause(); e.target.currentTime = 0; }}
                          />
                          <div className="video-play-overlay">
                            <VideoIcon size={24} />
                          </div>
                        </div>
                        <div className="media-overlay" style={{ transform: 'none', background: 'linear-gradient(to top, rgba(3, 7, 18, 0.95) 0%, rgba(3, 7, 18, 0.3) 100%)' }}>
                          <div className="creator-info">
                            <span className="creator-name">{item.label}</span>
                            <span className="creator-attribution">Hover to Preview</span>
                          </div>
                          <a 
                            href={item.url} 
                            target="_blank" 
                            rel="noreferrer" 
                            className="download-link"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ExternalLink size={16} />
                          </a>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-gallery glass-card">
                    <VideoIcon size={48} className="empty-icon" />
                    <p className="empty-text">No video footage found for this location.</p>
                  </div>
                )
              )}

            </div>
          )}

          {/* Skeletal Media Gallery Loading */}
          {loading && (
            <div className="media-gallery-section">
              <div className="gallery-tabs" style={{ opacity: 0.5 }}>
                <div className="tab-btn active"><ImageIcon size={18} /><span>Loading Media...</span></div>
              </div>
              <div className="media-grid">
                {[1, 2, 3, 4, 5, 6].map((i) => (
                  <div key={i} className="loading-card"></div>
                ))}
              </div>
            </div>
          )}

          {/* Tool Logs Inspector */}
          {!loading && debugMode && toolData.length > 0 && (
            <div className="glass-card animate-fade-in" style={{ padding: '24px', marginTop: '20px' }}>
              <div className="agent-header" style={{ marginBottom: '16px', borderBottom: '1px solid rgba(255, 255, 255, 0.05)' }}>
                <div className="agent-avatar" style={{ background: 'rgba(99, 102, 241, 0.15)', color: 'var(--accent-indigo)' }}>
                  <Compass size={20} />
                </div>
                <div className="agent-name" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
                  <span>Agent Execution Logs (Tools Called)</span>
                  <span style={{ fontSize: '0.8rem', background: 'rgba(99, 102, 241, 0.1)', color: '#818cf8', padding: '4px 10px', borderRadius: '9999px', fontWeight: '500' }}>
                    {toolData.length} Call{toolData.length > 1 ? 's' : ''}
                  </span>
                </div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {toolData.map((call, idx) => (
                  <details key={idx} style={{ background: 'rgba(15, 23, 42, 0.4)', borderRadius: '12px', border: '1px solid var(--border-glass)', overflow: 'hidden' }}>
                    <summary style={{ padding: '14px 20px', cursor: 'pointer', fontWeight: '600', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', userSelect: 'none' }}>
                      <span style={{ fontFamily: 'monospace', color: '#a855f7' }}>{call.tool_name}</span>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Click to view IO</span>
                    </summary>
                    <div style={{ padding: '20px', borderTop: '1px solid var(--border-glass)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: '600', marginBottom: '6px' }}>Tool Input Arguments</div>
                        <pre style={{ background: 'rgba(3, 7, 18, 0.5)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.03)', overflowX: 'auto', fontFamily: 'monospace', fontSize: '0.85rem', color: '#38bdf8' }}>
                          {JSON.stringify(call.tool_input, null, 2)}
                        </pre>
                      </div>
                      <div>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: '600', marginBottom: '6px' }}>Tool Executed Result</div>
                        <pre style={{ background: 'rgba(3, 7, 18, 0.5)', padding: '12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.03)', overflowX: 'auto', maxHeight: '250px', overflowY: 'auto', fontFamily: 'monospace', fontSize: '0.85rem', color: '#e2e8f0' }}>
                          {JSON.stringify(call.tool_output, null, 2)}
                        </pre>
                      </div>
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )}

        </div>
      )}

      {/* Lightbox / Modal */}
      {lightboxItem && (
        <div className="lightbox-modal" onClick={() => setLightboxItem(null)}>
          <button className="lightbox-close" onClick={() => setLightboxItem(null)}>
            <X size={24} />
          </button>
          <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
            {lightboxItem.type === 'photo' ? (
              <img src={lightboxItem.url} alt="Enlarged view" className="lightbox-media" />
            ) : (
              <video src={lightboxItem.url} controls autoPlay className="lightbox-media" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
