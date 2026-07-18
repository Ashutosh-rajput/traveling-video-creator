import React, { useState, useEffect, useRef } from 'react';
import {
  Search,
  MapPin,
  Compass,
  X,
  ExternalLink,
  Loader2,
  AlertCircle,
  Square,
  Volume2,
  Film,
  Download,
  Sparkles,
  Settings,
  Tv,
  FileText,
  Layers,
  Cloud
} from 'lucide-react';
import './App.css';

// API base comes from the Vite env var `VITE_API_URL`. If unset, fall back to
// same-origin relative paths (empty base) rather than a hardcoded deployment,
// so a build without VITE_API_URL talks to the host it's served from.
const API_BASE = (typeof import.meta !== 'undefined' && import.meta.env.VITE_API_URL)
  ? import.meta.env.VITE_API_URL
  : '';
const buildUrl = (path) => {
  if (!path) return path;
  if (!API_BASE) return path;
  if (API_BASE.endsWith('/') && path.startsWith('/')) return API_BASE.slice(0, -1) + path;
  return API_BASE + path;
};

function MediaHoverDetails({ asset, type }) {
  const provider = asset.provider && asset.provider !== 'combined'
    ? asset.provider.charAt(0).toUpperCase() + asset.provider.slice(1)
    : null;

  return (
    <div className="media-hover-details">
      <strong>{asset.title || asset.label}</strong>
      <span>{type === 'video' ? 'Video clip' : 'Photo'} · {asset.label}</span>
      {provider && <span>Source: {provider}</span>}
      {asset.creator && <span>Creator: {asset.creator}</span>}
      {type === 'video' && asset.duration_seconds && <span>Duration: {asset.duration_seconds}s</span>}
      {asset.page_url && (
        <a href={asset.page_url} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()}>
          View source ↗
        </a>
      )}
    </div>
  );
}

function App() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingStage, setLoadingStage] = useState(0);
  const [error, setError] = useState(null);
  
  // Response states
  const [pics, setPics] = useState([]);
  const [videos, setVideos] = useState([]);
  const [toolData, setToolData] = useState([]);
  const [videoScript, setVideoScript] = useState('');
  const [editInstruction, setEditInstruction] = useState('');
  const [editingScript, setEditingScript] = useState(false);
  const [ttsLoading, setTtsLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [audioUrl, setAudioUrl] = useState(null);
  const [audioElement, setAudioElement] = useState(null);

  // Video generation states
  const [videoGenerating, setVideoGenerating] = useState(false);
  const [videoUrl, setVideoUrl] = useState(null);
  const [videoError, setVideoError] = useState(null);

  // Busy flag for media library CRUD (music / transition uploads & deletes),
  // kept separate from the chat `loading` flag so those don't trigger the
  // "Consulting Gemma..." chat loading UI.
  const [mediaBusy, setMediaBusy] = useState(false);

  // Custom video options & settings panel
  const [debugMode, setDebugMode] = useState(false);
  const [selectedLanguage, setSelectedLanguage] = useState('en-IN');
  const [selectedSpeaker, setSelectedSpeaker] = useState('Shubh');
  const [musicMood, setMusicMood] = useState('none');
  const [musicVolume, setMusicVolume] = useState(0.5);
  const [previewingMusic, setPreviewingMusic] = useState(false);
  const [previewAudio, setPreviewAudio] = useState(null);
  const [musicTracks, setMusicTracks] = useState([]);
  const [transitionStyle, setTransitionStyle] = useState('none');
  const [transitionSound, setTransitionSound] = useState('none');
  const [transitionSounds, setTransitionSounds] = useState([]);
  const [previewingTransition, setPreviewingTransition] = useState(false);
  const [previewTransitionAudio, setPreviewTransitionAudio] = useState(null);
  const [numPlaces, setNumPlaces] = useState(5);
  const [videoLength, setVideoLength] = useState('medium');
  const [scriptStyle, setScriptStyle] = useState('reel');
  const [aspectRatio, setAspectRatio] = useState('horizontal');
  const [captionTheme, setCaptionTheme] = useState('Neon Yellow (Default)');
  
  // Settings sub-tab selection state: 'layout', 'voice', 'audio'
  const [settingsTab, setSettingsTab] = useState('layout');
  
  // Canvas Active Workspace tab: 'video', 'script', 'gallery', 'logs'
  const [canvasTab, setCanvasTab] = useState('video');
  const [lightboxItem, setLightboxItem] = useState(null);
  const [selectedMedia, setSelectedMedia] = useState({}); // { attractionLabel: [asset1, asset2] }
  
  // Google Drive upload states
  const [gdriveUploading, setGdriveUploading] = useState(false);
  const [gdriveLink, setGdriveLink] = useState(null);
  const [gdriveError, setGdriveError] = useState(null);
  const [gdriveConnected, setGdriveConnected] = useState(false);

  // Real-time progress monitoring states
  const [realProgress, setRealProgress] = useState({ percent: 0, stage: 'idle', message: '' });
  const [uploadProgress, setUploadProgress] = useState({ percent: 0, stage: 'idle', message: '' });

  // API timers
  const [chatElapsed, setChatElapsed] = useState(0);      // seconds for chat API
  const [videoElapsed, setVideoElapsed] = useState(0);    // seconds for video API
  const chatTimerRef = useRef(null);
  const videoTimerRef = useRef(null);

  const stages = [
    "Consulting Gemma Travel Assistant...",
    "Searching media providers...",
    "Extracting photos and videos...",
    "Formatting final results..."
  ];

  const languagesList = [
    { code: 'en-IN', name: 'English (India)' },
    { code: 'hi-Latn', name: 'Hinglish (Hindi in English letters)' },
    { code: 'hi-IN', name: 'Hindi (हिन्दी)' },
    { code: 'bn-IN', name: 'Bengali (বাংলা)' },
    { code: 'ta-IN', name: 'Tamil (தமிழ்)' },
    { code: 'te-IN', name: 'Telugu (తెలుగు)' },
    { code: 'kn-IN', name: 'Kannada (ಕನ್ನಡ)' },
    { code: 'ml-IN', name: 'Malayalam (മലയാളം)' },
    { code: 'mr-IN', name: 'Marathi (मराठी)' },
    { code: 'gu-IN', name: 'Gujarati (ગુજરાતી)' },
    { code: 'pa-IN', name: 'Punjabi (ਪੰਜਾਬੀ)' },
    { code: 'od-IN', name: 'Odia (ଓଡ଼ିଆ)' }
  ];

  const speakersList = [
    'Shubh', 'Aditya', 'Ritu', 'Priya', 'Neha', 'Rahul', 'Pooja', 'Rohan', 'Simran', 'Kavya', 'Amit', 'Dev', 'Ishita'
  ];

  const captionThemesList = [
    'Neon Yellow (Default)', 'Cyberpunk Pink', 'Emerald Green', 'Simple White', 'Royal Gold', 'Retro Orange'
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

    if (audioElement) {
      audioElement.pause();
    }
    setAudioElement(null);
    setAudioUrl(null);
    setIsPlaying(false);
    setTtsLoading(false);

    setLoading(true);
    setError(null);
    setPics([]);
    setVideos([]);
    setToolData([]);
    setVideoScript('');
    setVideoUrl(null);
    setVideoError(null);
    setVideoGenerating(false);

    // Start chat timer
    setChatElapsed(0);
    chatTimerRef.current = setInterval(() => setChatElapsed(s => s + 1), 1000);

    try {
      const response = await fetch(buildUrl('/api/v1/chat'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          message: searchQuery,
          debug: debugMode,
          language: selectedLanguage,
          num_places: numPlaces,
          video_length: videoLength,
          speaker: selectedSpeaker,
          script_style: scriptStyle
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to connect to the backend agent service.');
      }

      const data = await response.json();
      setPics(data.pics || []);
      setVideos(data.videos || []);
      setToolData(data.tool_data || []);
      setVideoScript(data.video_script || '');

      // Initialize selected media mapping per attraction label
      const initialSelected = {};
      const uniqueLabels = Array.from(new Set([
        ...(data.videos || []).map(v => v.label),
        ...(data.pics || []).map(p => p.label)
      ])).filter(Boolean);

      uniqueLabels.forEach(label => {
        const placeVideos = (data.videos || []).filter(v => v.label === label);
        const placePhotos = (data.pics || []).filter(p => p.label === label);
        const videoAssets = placeVideos.map(asset => ({ ...asset, type: 'video' }));
        const photoAssets = placePhotos.map(asset => ({ ...asset, type: 'photo' }));
        
        let selected = [];
        if (videoAssets.length >= 2) {
          selected = videoAssets.slice(0, 2);
        } else if (videoAssets.length === 1) {
          selected = [videoAssets[0], ...photoAssets.slice(0, 1)];
        } else {
          // No video for this attraction — allow up to 3 photos.
          selected = photoAssets.slice(0, 3);
        }
        initialSelected[label] = selected;
      });
      setSelectedMedia(initialSelected);
      
      // Auto switch tabs on success
      setCanvasTab('script');
    } catch (err) {
      console.error(err);
      setError(err.message || 'An error occurred while fetching search results.');
    } finally {
      setLoading(false);
      clearInterval(chatTimerRef.current);
    }
  };

  // Max selectable assets per attraction: 2 normally, but 3 photos when the
  // attraction has no video option available.
  const getMaxSelect = (label) => (videos.some(v => v.label === label) ? 2 : 3);

  const handleToggleMedia = (label, asset) => {
    const maxSelect = getMaxSelect(label);
    setSelectedMedia(prev => {
      const current = prev[label] || [];
      const assetUrl = asset.url || asset.video_url || asset.image_url;
      const assetType = asset.type || (asset.video_url ? 'video' : 'photo');
      if (!assetUrl) return prev;

      const normalizedAsset = { ...asset, url: assetUrl, type: assetType };
      const exists = current.some(item => item.url === assetUrl && item.type === assetType);

      let next = [];
      if (exists) {
        // Remove it
        next = current.filter(item => !(item.url === assetUrl && item.type === assetType));
      } else if (current.length >= maxSelect) {
        // FIFO: drop the oldest, keep the rest, add the new one.
        next = [...current.slice(current.length - maxSelect + 1), normalizedAsset];
      } else {
        // Add it
        next = [...current, normalizedAsset];
      }
      return {
        ...prev,
        [label]: next
      };
    });
  };

  const handleGDriveUpload = async () => {
    setGdriveUploading(true);
    setGdriveError(null);
    setGdriveLink(null);
    setUploadProgress({ percent: 0, stage: 'uploading', message: 'Initiating upload...' });

    // Start status polling
    const pollInterval = setInterval(async () => {
      try {
        const statusRes = await fetch(buildUrl('/api/v1/chat/upload-gdrive-status'));
        if (statusRes.ok) {
          const progressData = await statusRes.json();
          setUploadProgress(progressData);
        }
      } catch (err) {
        console.error("Failed to poll upload status", err);
      }
    }, 2000);

    try {
      const res = await fetch(buildUrl('/api/v1/chat/upload-gdrive'), {
        method: 'POST',
      });

      clearInterval(pollInterval);

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Google Drive upload failed.');
      }

      const data = await res.json();
      setGdriveLink(data.view_link);
      setUploadProgress({ percent: 100, stage: 'completed', message: 'Upload completed!' });
    } catch (err) {
      clearInterval(pollInterval);
      console.error(err);
      setGdriveError(err.message || 'An unexpected error occurred during Google Drive upload.');
      setUploadProgress({ percent: 0, stage: 'error', message: err.message || 'Upload failed.' });
    } finally {
      setGdriveUploading(false);
    }
  };

  const connectGoogleDrive = () => {
    window.open(buildUrl('/api/v1/login/google'), 'google-drive-oauth', 'popup,width=600,height=720');
  };

  const handleQuickSearch = (term) => {
    setQuery(term);
    handleSearch(null, term);
  };

  const handleTtsPlay = async () => {
    if (isPlaying) {
      if (audioElement) {
        audioElement.pause();
      }
      setIsPlaying(false);
      return;
    }

    if (audioUrl && audioElement) {
      audioElement.play();
      setIsPlaying(true);
      return;
    }

    setTtsLoading(true);
    try {
      const res = await fetch(buildUrl('/api/v1/tts'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          text: videoScript,
          speaker: selectedSpeaker,
          language_code: selectedLanguage
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to generate narration audio.');
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      
      audio.onended = () => {
        setIsPlaying(false);
      };
      
      audio.onerror = () => {
        setIsPlaying(false);
        setTtsLoading(false);
        alert('Failed to play voiceover audio.');
      };

      setAudioUrl(url);
      setAudioElement(audio);
      audio.play();
      setIsPlaying(true);
    } catch (err) {
      console.error(err);
      alert(err.message || 'Failed to generate voiceover. Make sure SARVAM_API_KEY is configured in .env.');
    } finally {
      setTtsLoading(false);
    }
  };

  // Ask the agent to revise the current script per a natural-language instruction.
  const handleAgentEditScript = async () => {
    const instruction = editInstruction.trim();
    if (!instruction || !videoScript.trim() || editingScript) return;

    setEditingScript(true);
    try {
      const res = await fetch(buildUrl('/api/v1/chat/edit-script'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_script: videoScript,
          instruction,
          language: selectedLanguage,
          script_style: scriptStyle,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to edit the script.');
      }

      const data = await res.json();
      if (data.video_script) {
        setVideoScript(data.video_script);
        setEditInstruction('');
        // Any previously synthesized voiceover no longer matches the new script.
        if (audioElement) audioElement.pause();
        setAudioElement(null);
        setAudioUrl(null);
        setIsPlaying(false);
      }
    } catch (err) {
      console.error(err);
      alert(err.message || 'Failed to edit the script.');
    } finally {
      setEditingScript(false);
    }
  };

  // Handle stopping preview when mood changes
  useEffect(() => {
    if (previewAudio) {
      previewAudio.pause();
      previewAudio.src = '';
      setPreviewingMusic(false);
      setPreviewAudio(null);
    }
  }, [musicMood]);

  // Handle stopping preview when transition sound changes
  useEffect(() => {
    if (previewTransitionAudio) {
      previewTransitionAudio.pause();
      previewTransitionAudio.src = '';
      setPreviewingTransition(false);
      setPreviewTransitionAudio(null);
    }
  }, [transitionSound]);

  // Clean up preview audio on unmount
  useEffect(() => {
    return () => {
      if (previewAudio) {
        previewAudio.pause();
        previewAudio.src = '';
      }
      if (previewTransitionAudio) {
        previewTransitionAudio.pause();
        previewTransitionAudio.src = '';
      }
    };
  }, [previewAudio, previewTransitionAudio]);

  // Revoke the previous narration blob URL when it changes or on unmount so
  // TTS audio blobs don't accumulate in memory across plays.
  useEffect(() => {
    return () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [audioUrl]);

  // Revoke the previous rendered-video blob URL when it changes or on unmount.
  // Guarded so the cached last-video server URL (not a blob) is left alone.
  useEffect(() => {
    return () => {
      if (videoUrl && videoUrl.startsWith('blob:')) URL.revokeObjectURL(videoUrl);
    };
  }, [videoUrl]);

  // Invalidate cached narration when the voice or language changes, so the next
  // Play regenerates audio with the new selection instead of replaying stale audio.
  useEffect(() => {
    if (audioElement) audioElement.pause();
    setIsPlaying(false);
    setAudioElement(null);
    setAudioUrl(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSpeaker, selectedLanguage]);

  // Poll render status for a city until it completes or errors. Shared by the
  // Generate button and by reattachment on load (below), so a render that is
  // still running server-side is tracked either way.
  const startStatusPolling = (cityName) => {
    const pollInterval = setInterval(async () => {
      try {
        const statusRes = await fetch(buildUrl(`/api/v1/chat/generate-status?city_name=${encodeURIComponent(cityName)}`));
        if (!statusRes.ok) return;
        const progressData = await statusRes.json();
        setRealProgress(progressData);

        if (progressData.stage === 'completed') {
          clearInterval(pollInterval);
          clearInterval(videoTimerRef.current);
          setVideoGenerating(false);
          setVideoUrl(buildUrl(`/api/v1/chat/last-video?t=${Date.now()}`));
        } else if (progressData.stage === 'error') {
          clearInterval(pollInterval);
          clearInterval(videoTimerRef.current);
          setVideoGenerating(false);
          setVideoError(progressData.message || 'Video generation failed.');
        } else if (progressData.stage === 'idle') {
          // No active render on the server (e.g. the backend was restarted
          // mid-render). Stop tracking instead of spinning forever.
          clearInterval(pollInterval);
          clearInterval(videoTimerRef.current);
          setVideoGenerating(false);
          setVideoError('Video generation was interrupted. Please try again.');
        }
      } catch (err) {
        console.error("Failed to poll video generation status", err);
      }
    }, 3000);
    return pollInterval;
  };

  // Load background music and transition sound options dynamically on mount and check for cached last video
  useEffect(() => {
    fetch(buildUrl('/api/v1/chat/background-music'))
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setMusicTracks(data);
        }
      })
      .catch(err => console.error("Error loading background music tracks:", err));

    fetch(buildUrl('/api/v1/chat/transition-sounds'))
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setTransitionSounds(data);
        }
      })
      .catch(err => console.error("Error loading transition sounds:", err));

    // Reattach to a render that is still running on the server (e.g. after a
    // page reload). If none is active, fall back to showing the last cached video.
    const activeStages = ['starting', 'parsing', 'voiceover', 'downloading', 'rendering', 'finalizing'];
    fetch(buildUrl('/api/v1/chat/generate-status'))
      .then(res => (res.ok ? res.json() : null))
      .then(progress => {
        if (progress && activeStages.includes(progress.stage) && progress.city_name) {
          // A render is in progress — resume tracking it.
          setVideoGenerating(true);
          setRealProgress(progress);
          setCanvasTab('video');
          setVideoElapsed(0);
          videoTimerRef.current = setInterval(() => setVideoElapsed(s => s + 1), 1000);
          startStatusPolling(progress.city_name);
          return;
        }
        // No active render — show the last generated video if one is cached.
        fetch(buildUrl('/api/v1/chat/last-video'), { method: 'HEAD' })
          .then(res => {
            if (res.ok) {
              setVideoUrl(buildUrl('/api/v1/chat/last-video'));
              setCanvasTab('video');
            }
          })
          .catch(err => console.error("Error checking cached video:", err));
      })
      .catch(err => console.error("Error checking render status:", err));

    const refreshDriveStatus = () => {
      fetch(buildUrl('/api/v1/chat/gdrive-status'))
        .then(res => res.ok ? res.json() : { connected: false })
        .then(data => setGdriveConnected(Boolean(data.connected)))
        .catch(() => setGdriveConnected(false));
    };
    refreshDriveStatus();
    window.addEventListener('focus', refreshDriveStatus);
    return () => window.removeEventListener('focus', refreshDriveStatus);
  }, []);

  const toggleMusicPreview = () => {
    if (previewingMusic && previewAudio) {
      previewAudio.pause();
      setPreviewingMusic(false);
    } else {
      if (previewAudio) {
        previewAudio.pause();
        previewAudio.src = '';
      }
      
      const selectedTrack = musicTracks.find(t => t.id === musicMood);
      const filename = selectedTrack ? selectedTrack.filename : `${musicMood}.mp3`;
      const audioUrl = buildUrl(`/api/v1/chat/background-music/file/${filename}`);
      const audio = new Audio(audioUrl);
      audio.volume = musicVolume;
      audio.loop = true;
      setPreviewAudio(audio); // track immediately so volume changes / cleanup apply

      audio.play().then(() => {
        setPreviewingMusic(true);
      }).catch((err) => {
        console.error("Failed to play preview:", err);
        setPreviewAudio(null);
      });
    }
  };

  const handleMusicVolumeChange = (e) => {
    const val = parseFloat(e.target.value);
    setMusicVolume(val);
    if (previewAudio) {
      previewAudio.volume = val;
    }
  };

  const toggleTransitionPreview = () => {
    if (previewingTransition && previewTransitionAudio) {
      previewTransitionAudio.pause();
      setPreviewingTransition(false);
    } else {
      if (previewTransitionAudio) {
        previewTransitionAudio.pause();
        previewTransitionAudio.src = '';
      }
      
      const selectedSound = transitionSounds.find(t => t.id === transitionSound);
      const filename = selectedSound ? selectedSound.filename : `${transitionSound}.wav`;
      const audioUrl = buildUrl(`/api/v1/chat/transition-sounds/file/${filename}`);
      const audio = new Audio(audioUrl);
      audio.volume = 0.8;
      
      audio.play().then(() => {
        setPreviewTransitionAudio(audio);
        setPreviewingTransition(true);
      }).catch((err) => {
        console.error("Failed to play transition preview:", err);
      });
      
      audio.onended = () => {
        setPreviewingTransition(false);
      };
      
      setPreviewTransitionAudio(audio);
    }
  };
  const handleMusicUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      setMediaBusy(true);
      const res = await fetch(buildUrl('/api/v1/chat/background-music/upload'), {
        method: 'POST',
        body: formData
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to upload background music.');
      }

      const result = await res.json();
      
      // Reload tracks
      const listRes = await fetch(buildUrl('/api/v1/chat/background-music'));
      const listData = await listRes.json();
      if (Array.isArray(listData)) {
        setMusicTracks(listData);
        // Find newly uploaded track ID and set it as selected
        const trackId = result.filename.split('.')[0];
        setMusicMood(trackId);
      }
    } catch (err) {
      console.error(err);
      alert(err.message);
    } finally {
      setMediaBusy(false);
    }
  };

  const handleMusicDelete = async () => {
    if (musicMood === 'none') return;
    const selectedTrack = musicTracks.find(t => t.id === musicMood);
    if (!selectedTrack) return;

    if (!confirm(`Are you sure you want to delete "${selectedTrack.name}"?`)) return;

    try {
      setMediaBusy(true);

      // Pause preview if playing
      if (previewAudio) {
        previewAudio.pause();
        setPreviewingMusic(false);
        setPreviewAudio(null);
      }

      const res = await fetch(buildUrl(`/api/v1/chat/background-music/file/${selectedTrack.filename}`), {
        method: 'DELETE'
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to delete track.');
      }

      // Reload tracks list
      const listRes = await fetch(buildUrl('/api/v1/chat/background-music'));
      const listData = await listRes.json();
      if (Array.isArray(listData)) {
        setMusicTracks(listData);
      }
      setMusicMood('none');
    } catch (err) {
      console.error(err);
      alert(err.message);
    } finally {
      setMediaBusy(false);
    }
  };

  const handleTransitionSoundUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
      setMediaBusy(true);
      const res = await fetch(buildUrl('/api/v1/chat/transition-sounds/upload'), {
        method: 'POST',
        body: formData
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to upload sound effect.');
      }

      const result = await res.json();
      
      // Reload transition sounds
      const listRes = await fetch(buildUrl('/api/v1/chat/transition-sounds'));
      const listData = await listRes.json();
      if (Array.isArray(listData)) {
        setTransitionSounds(listData);
        // Find newly uploaded sound ID and set it as selected
        const soundId = result.filename.split('.')[0];
        setTransitionSound(soundId);
      }
    } catch (err) {
      console.error(err);
      alert(err.message);
    } finally {
      setMediaBusy(false);
    }
  };

  const handleTransitionSoundDelete = async () => {
    if (transitionSound === 'none') return;
    
    // Protect defaults
    const defaults = ['whoosh', 'click', 'glitch'];
    if (defaults.includes(transitionSound.toLowerCase())) {
      alert("Cannot delete default system transition sounds.");
      return;
    }

    const selectedSound = transitionSounds.find(s => s.id === transitionSound);
    if (!selectedSound) return;

    if (!confirm(`Are you sure you want to delete "${selectedSound.name}"?`)) return;

    try {
      setMediaBusy(true);

      // Pause preview if playing
      if (previewTransitionAudio) {
        previewTransitionAudio.pause();
        setPreviewingTransition(false);
        setPreviewTransitionAudio(null);
      }

      const res = await fetch(buildUrl(`/api/v1/chat/transition-sounds/file/${selectedSound.filename}`), {
        method: 'DELETE'
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to delete transition sound.');
      }

      // Reload list
      const listRes = await fetch(buildUrl('/api/v1/chat/transition-sounds'));
      const listData = await listRes.json();
      if (Array.isArray(listData)) {
        setTransitionSounds(listData);
      }
      setTransitionSound('none');
    } catch (err) {
      console.error(err);
      alert(err.message);
    } finally {
      setMediaBusy(false);
    }
  };
  const handleGenerateVideo = async () => {
    // Capture the city at generation start so editing the input mid-render
    // doesn't repoint the status poll or the request at a different city.
    const cityName = query;

    setVideoGenerating(true);
    setVideoError(null);
    setVideoUrl(null);
    setGdriveLink(null);
    setGdriveError(null);
    setRealProgress({ percent: 0, stage: 'starting', message: 'Starting video generation...' });
    setCanvasTab('video'); // Switch to video tab to view render progress

    // Start video timer
    setVideoElapsed(0);
    videoTimerRef.current = setInterval(() => setVideoElapsed(s => s + 1), 1000);

    // Extract selected assets from selectedMedia dictionary
    const finalSelectedPics = [];
    const finalSelectedVids = [];
    Object.values(selectedMedia).forEach(assets => {
      if (Array.isArray(assets)) {
        assets.forEach(asset => {
          if (asset.type === 'video') {
            finalSelectedVids.push({ url: asset.url, label: asset.label });
          } else {
            finalSelectedPics.push({ url: asset.url, label: asset.label });
          }
        });
      }
    });

    try {
      // Kick off the background render. This returns immediately — the server
      // keeps rendering even if this tab is closed; we just poll for progress.
      const res = await fetch(buildUrl('/api/v1/chat/generate-video'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          script: videoScript,
          pics: finalSelectedPics,
          videos: finalSelectedVids,
          city_name: cityName,
          aspect_ratio: aspectRatio,
          speaker: selectedSpeaker,
          language_code: selectedLanguage,
          music_mood: musicMood,
          music_volume: musicVolume,
          transition_style: transitionStyle,
          transition_sound: transitionSound,
          caption_theme: captionTheme,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to start video generation.');
      }

      // Poll status until the render completes or fails. The server keeps
      // rendering even if this tab is closed; on reload we reattach on mount.
      startStatusPolling(cityName);
    } catch (err) {
      clearInterval(videoTimerRef.current);
      console.error(err);
      setVideoGenerating(false);
      setVideoError(err.message || 'Video generation failed.');
      setRealProgress({ percent: 0, stage: 'error', message: err.message || 'Generation failed.' });
    }
  };

  return (
    <div className="studio-container font-outfit">
      <div className="glow-spot-1"></div>
      
      {/* Studio Header */}
      <header className="studio-header animate-fade-in">
        <div className="studio-brand">
          <div className="studio-logo-glow">
            <Compass size={28} />
          </div>
          <div>
            <h1 className="studio-title">Voyageur AI Studio</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '2px' }}>Professional Travel Vlog Engine</p>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span className="studio-badge">Bulbul v3 TTS</span>
          <span className="studio-badge" style={{ borderColor: 'rgba(168, 85, 247, 0.2)', color: '#c084fc', background: 'rgba(168, 85, 247, 0.1)' }}>Gemma-4 Agent</span>
        </div>
      </header>

      {/* 2-Column Split Studio Workspace */}
      <div className="studio-workspace">
        
        {/* Left Side: Studio Control Console */}
        <div className="console-panel animate-fade-in" style={{ animationDelay: '0.1s' }}>
          <div className="glass-card console-card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', borderBottom: '1px solid var(--border-glass)', paddingBottom: '10px' }}>
              <Settings size={18} style={{ color: 'var(--primary-color)' }} />
              <h2 style={{ fontSize: '1.1rem', fontWeight: '700', color: 'var(--text-primary)' }}>Studio Console</h2>
            </div>

            <form onSubmit={handleSearch} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {/* Destination Query */}
              <div className="console-input-group">
                <label className="console-input-label">Destination City</label>
                <div className="console-text-input-wrapper">
                  <Search size={18} className="console-input-icon" />
                  <input
                    type="text"
                    placeholder="e.g. Mangalore, Goa, Orchha, Paris..."
                    className="console-input"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    disabled={loading}
                  />
                </div>
              </div>

              {/* Settings Sub-Tab Control Bar */}
              <div className="settings-tab-container">
                <button
                  type="button"
                  onClick={() => setSettingsTab('layout')}
                  className={`settings-tab-btn ${settingsTab === 'layout' ? 'active' : ''}`}
                >
                  📽️ Layout
                </button>
                <button
                  type="button"
                  onClick={() => setSettingsTab('voice')}
                  className={`settings-tab-btn ${settingsTab === 'voice' ? 'active' : ''}`}
                >
                  🗣️ Voice & Subs
                </button>
                <button
                  type="button"
                  onClick={() => setSettingsTab('audio')}
                  className={`settings-tab-btn ${settingsTab === 'audio' ? 'active' : ''}`}
                >
                  🎵 Music & FX
                </button>
              </div>

              {/* Tab Content 1: Video Layout Settings */}
              {settingsTab === 'layout' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '5px' }}>
                  {/* Number of Attractions Slider */}
                  <div className="console-input-group">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <label className="console-input-label">Attractions to Cover</label>
                      <span style={{ fontSize: '0.9rem', color: '#38bdf8', fontWeight: '700' }}>{numPlaces}</span>
                    </div>
                    <input 
                      type="range" 
                      min="3" 
                      max="10" 
                      value={numPlaces}
                      disabled={loading}
                      onChange={(e) => setNumPlaces(parseInt(e.target.value))}
                      style={{
                        width: '100%',
                        accentColor: '#38bdf8',
                        background: 'rgba(15, 23, 42, 0.6)',
                        borderRadius: '6px',
                        height: '6px',
                        outline: 'none',
                        cursor: 'pointer',
                        marginTop: '8px'
                      }}
                    />
                  </div>

                  {/* Length Selector */}
                  <div className="console-input-group">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <label className="console-input-label">Video Length</label>
                      <span style={{ fontSize: '0.75rem', color: '#38bdf8', fontWeight: '700', fontFamily: 'monospace' }}>
                        {videoLength === 'short' ? '~45-60s' : videoLength === 'medium' ? '~1.5-2m' : '~3m'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      {['short', 'medium', 'long'].map((len) => (
                        <button
                          key={len}
                          type="button"
                          disabled={loading}
                          onClick={() => setVideoLength(len)}
                          style={{
                            flex: 1,
                            padding: '8px 4px',
                            borderRadius: '6px',
                            border: videoLength === len ? '1px solid rgba(56, 189, 248, 0.4)' : '1px solid var(--border-glass)',
                            background: videoLength === len ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
                            color: videoLength === len ? '#38bdf8' : '#64748b',
                            fontSize: '0.75rem',
                            fontWeight: '700',
                            textTransform: 'capitalize',
                            cursor: 'pointer'
                          }}
                        >
                          {len}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Script Style Selector */}
                  <div className="console-input-group">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <label className="console-input-label">Script Style</label>
                      <span style={{ fontSize: '0.7rem', color: '#64748b' }}>
                        {scriptStyle === 'reel' ? 'Hook · budget · itinerary · CTA' : 'Professional guide'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      {[
                        { mode: 'reel', label: 'Reel' },
                        { mode: 'classic', label: 'Classic' }
                      ].map((style) => (
                        <button
                          key={style.mode}
                          type="button"
                          disabled={loading}
                          onClick={() => setScriptStyle(style.mode)}
                          style={{
                            flex: 1,
                            padding: '8px 4px',
                            borderRadius: '6px',
                            border: scriptStyle === style.mode ? '1px solid rgba(56, 189, 248, 0.4)' : '1px solid var(--border-glass)',
                            background: scriptStyle === style.mode ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
                            color: scriptStyle === style.mode ? '#38bdf8' : '#64748b',
                            fontSize: '0.75rem',
                            fontWeight: '700',
                            cursor: 'pointer'
                          }}
                        >
                          {style.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Aspect Ratio Selector */}
                  <div className="console-input-group">
                    <label className="console-input-label">Aspect Layout</label>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      {[
                        { mode: 'horizontal', label: '16:9 Wide' },
                        { mode: 'portrait', label: '9:16 Tall' }
                      ].map((aspect) => (
                        <button
                          key={aspect.mode}
                          type="button"
                          disabled={loading}
                          onClick={() => setAspectRatio(aspect.mode)}
                          style={{
                            flex: 1,
                            padding: '8px 4px',
                            borderRadius: '6px',
                            border: aspectRatio === aspect.mode ? '1px solid rgba(251, 191, 36, 0.4)' : '1px solid var(--border-glass)',
                            background: aspectRatio === aspect.mode ? 'rgba(251, 191, 36, 0.15)' : 'transparent',
                            color: aspectRatio === aspect.mode ? '#fbbf24' : '#64748b',
                            fontSize: '0.75rem',
                            fontWeight: '700',
                            cursor: 'pointer'
                          }}
                        >
                          {aspect.label.split(' ')[1]}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Tab Content 2: Voice & Language style */}
              {settingsTab === 'voice' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '5px' }}>
                  {/* Language Selection */}
                  <div className="console-input-group">
                    <label className="console-input-label">Language Accent</label>
                    <select 
                      value={selectedLanguage} 
                      onChange={(e) => setSelectedLanguage(e.target.value)}
                      disabled={loading}
                      style={{
                        background: 'rgba(15, 23, 42, 0.6)',
                        border: '1px solid var(--border-glass)',
                        borderRadius: '8px',
                        padding: '12px 14px',
                        color: '#e2e8f0',
                        fontSize: '0.95rem',
                        outline: 'none',
                        cursor: 'pointer'
                      }}
                    >
                      {languagesList.map((lang) => (
                        <option key={lang.code} value={lang.code} style={{ background: '#0f172a' }}>{lang.name}</option>
                      ))}
                    </select>
                  </div>

                  {/* Speaker Voice Selection */}
                  <div className="console-input-group">
                    <label className="console-input-label">Speaker Voice</label>
                    <select 
                      value={selectedSpeaker} 
                      onChange={(e) => setSelectedSpeaker(e.target.value)}
                      disabled={loading}
                      style={{
                        background: 'rgba(15, 23, 42, 0.6)',
                        border: '1px solid var(--border-glass)',
                        borderRadius: '8px',
                        padding: '12px 14px',
                        color: '#e2e8f0',
                        fontSize: '0.95rem',
                        outline: 'none',
                        cursor: 'pointer'
                      }}
                    >
                      {speakersList.map((spk) => (
                        <option key={spk} value={spk} style={{ background: '#0f172a' }}>{spk}</option>
                      ))}
                    </select>
                  </div>

                  {/* Caption Theme Selection */}
                  <div className="console-input-group">
                    <label className="console-input-label">Caption Style Theme</label>
                    <select 
                      value={captionTheme} 
                      onChange={(e) => setCaptionTheme(e.target.value)}
                      disabled={loading}
                      style={{
                        background: 'rgba(15, 23, 42, 0.6)',
                        border: '1px solid var(--border-glass)',
                        borderRadius: '8px',
                        padding: '12px 14px',
                        color: '#e2e8f0',
                        fontSize: '0.95rem',
                        outline: 'none',
                        cursor: 'pointer'
                      }}
                    >
                      {captionThemesList.map((theme) => (
                        <option key={theme} value={theme} style={{ background: '#0f172a' }}>{theme}</option>
                      ))}
                    </select>
                  </div>
                </div>
              )}

              {/* Tab Content 3: Audio & Sound Effects */}
              {settingsTab === 'audio' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginTop: '5px' }}>
                  {/* Background Music Selection */}
                  <div className="console-input-group">
                    <label className="console-input-label">Background Music</label>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                      <select 
                        value={musicMood} 
                        onChange={(e) => setMusicMood(e.target.value)}
                        disabled={loading}
                        style={{
                          flex: 1,
                          background: 'rgba(15, 23, 42, 0.6)',
                          border: '1px solid var(--border-glass)',
                          borderRadius: '8px',
                          padding: '12px 14px',
                          color: '#e2e8f0',
                          fontSize: '0.95rem',
                          outline: 'none',
                          cursor: 'pointer',
                          minWidth: 0
                        }}
                      >
                        <option value="none" style={{ background: '#0f172a' }}>None (No Background Music)</option>
                        {musicTracks.map((track) => (
                          <option key={track.id} value={track.id} style={{ background: '#0f172a' }}>
                            {track.name}
                          </option>
                        ))}
                      </select>

                      <label 
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          background: 'rgba(56, 189, 248, 0.15)',
                          border: '1px solid rgba(56, 189, 248, 0.4)',
                          color: '#38bdf8',
                          borderRadius: '8px',
                          padding: '12px',
                          cursor: 'pointer',
                          fontSize: '0.95rem',
                          transition: 'all 0.2s',
                          height: '46px',
                          width: '46px'
                        }}
                        title="Upload background music (.mp3, .wav)"
                      >
                        ➕
                        <input 
                          type="file" 
                          accept=".mp3,.wav" 
                          onChange={handleMusicUpload}
                          style={{ display: 'none' }}
                          disabled={mediaBusy}
                        />
                      </label>

                      {musicMood !== 'none' && (
                        <button
                          type="button"
                          onClick={handleMusicDelete}
                          disabled={mediaBusy}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: 'rgba(239, 68, 68, 0.15)',
                            border: '1px solid rgba(239, 68, 68, 0.4)',
                            color: '#ef4444',
                            borderRadius: '8px',
                            padding: '12px',
                            cursor: 'pointer',
                            fontSize: '0.95rem',
                            transition: 'all 0.2s',
                            height: '46px',
                            width: '46px'
                          }}
                          title="Delete selected track"
                        >
                          🗑️
                        </button>
                      )}
                    </div>

                    {musicMood !== 'none' && (
                      <div style={{
                        marginTop: '10px',
                        padding: '10px',
                        borderRadius: '8px',
                        background: 'rgba(15, 23, 42, 0.4)',
                        border: '1px solid rgba(255, 255, 255, 0.05)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '8px'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <button
                            type="button"
                            onClick={toggleMusicPreview}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              background: previewingMusic ? 'rgba(239, 68, 68, 0.15)' : 'rgba(56, 189, 248, 0.15)',
                              border: previewingMusic ? '1px solid rgba(239, 68, 68, 0.4)' : '1px solid rgba(56, 189, 248, 0.4)',
                              color: previewingMusic ? '#ef4444' : '#38bdf8',
                              borderRadius: '6px',
                              padding: '6px 12px',
                              fontSize: '0.75rem',
                              fontWeight: '700',
                              cursor: 'pointer',
                              gap: '6px',
                              transition: 'all 0.2s',
                              borderWidth: '1px',
                              borderStyle: 'solid'
                            }}
                          >
                            {previewingMusic ? (
                              <>
                                <span style={{ 
                                  width: '8px', 
                                  height: '8px', 
                                  borderRadius: '50%', 
                                  background: '#ef4444', 
                                  display: 'inline-block'
                                }}></span>
                                Pause Preview
                              </>
                            ) : (
                              <>
                                <span style={{ fontSize: '0.65rem' }}>▶</span> Play Preview
                              </>
                            )}
                          </button>
                          <span style={{ fontSize: '0.7rem', color: '#64748b', textTransform: 'capitalize' }}>
                            Previewing: {musicMood}
                          </span>
                        </div>

                        {/* Volume slider */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontSize: '0.7rem', color: '#94a3b8', fontWeight: '500' }}>Music Volume</span>
                            <span style={{ fontSize: '0.7rem', color: '#38bdf8', fontWeight: '700' }}>{Math.round(musicVolume * 100)}%</span>
                          </div>
                          <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.01"
                            value={musicVolume}
                            onChange={handleMusicVolumeChange}
                            style={{
                              width: '100%',
                              accentColor: '#38bdf8',
                              background: 'rgba(15, 23, 42, 0.8)',
                              borderRadius: '4px',
                              height: '4px',
                              outline: 'none',
                              cursor: 'pointer'
                            }}
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Transition Style Selection */}
                  <div className="console-input-group">
                    <label className="console-input-label">Visual Transition Card</label>
                    <select 
                      value={transitionStyle} 
                      onChange={(e) => setTransitionStyle(e.target.value)}
                      disabled={loading}
                      style={{
                        background: 'rgba(15, 23, 42, 0.6)',
                        border: '1px solid var(--border-glass)',
                        borderRadius: '8px',
                        padding: '12px 14px',
                        color: '#e2e8f0',
                        fontSize: '0.95rem',
                        outline: 'none',
                        cursor: 'pointer'
                      }}
                    >
                      <option value="none" style={{ background: '#0f172a' }}>None (Direct cut)</option>
                      <option value="fade" style={{ background: '#0f172a' }}>✨ Smooth Fade Card</option>
                      <option value="zoom" style={{ background: '#0f172a' }}>🔍 Dynamic Zoom Card</option>
                      <option value="slide" style={{ background: '#0f172a' }}>↕️ Slide Up Card</option>
                    </select>
                  </div>

                  {/* Transition Sound Selection */}
                  <div className="console-input-group">
                    <label className="console-input-label">Transition Sound Effect</label>
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                      <select 
                        value={transitionSound} 
                        onChange={(e) => setTransitionSound(e.target.value)}
                        disabled={loading}
                        style={{
                          flex: 1,
                          background: 'rgba(15, 23, 42, 0.6)',
                          border: '1px solid var(--border-glass)',
                          borderRadius: '8px',
                          padding: '12px 14px',
                          color: '#e2e8f0',
                          fontSize: '0.95rem',
                          outline: 'none',
                          cursor: 'pointer',
                          minWidth: 0
                        }}
                      >
                        <option value="none" style={{ background: '#0f172a' }}>None (Silent transition)</option>
                        {transitionSounds.map((sound) => (
                          <option key={sound.id} value={sound.id} style={{ background: '#0f172a' }}>
                            {sound.name}
                          </option>
                        ))}
                        {/* Fallbacks if transitionSounds is empty or loading */}
                        {transitionSounds.length === 0 && (
                          <>
                            <option value="whoosh" style={{ background: '#0f172a' }}>💨 Whoosh Swoosh</option>
                            <option value="click" style={{ background: '#0f172a' }}>📸 Camera Click</option>
                            <option value="glitch" style={{ background: '#0f172a' }}>⚡ Sci-Fi Glitch</option>
                          </>
                        )}
                      </select>

                      <label 
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          background: 'rgba(56, 189, 248, 0.15)',
                          border: '1px solid rgba(56, 189, 248, 0.4)',
                          color: '#38bdf8',
                          borderRadius: '8px',
                          padding: '12px',
                          cursor: 'pointer',
                          fontSize: '0.95rem',
                          transition: 'all 0.2s',
                          height: '46px',
                          width: '46px'
                        }}
                        title="Upload transition sound effect (.mp3, .wav)"
                      >
                        ➕
                        <input 
                          type="file" 
                          accept=".mp3,.wav" 
                          onChange={handleTransitionSoundUpload}
                          style={{ display: 'none' }}
                          disabled={mediaBusy}
                        />
                      </label>

                      {transitionSound !== 'none' && !['whoosh', 'click', 'glitch'].includes(transitionSound.toLowerCase()) && (
                        <button
                          type="button"
                          onClick={handleTransitionSoundDelete}
                          disabled={mediaBusy}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: 'rgba(239, 68, 68, 0.15)',
                            border: '1px solid rgba(239, 68, 68, 0.4)',
                            color: '#ef4444',
                            borderRadius: '8px',
                            padding: '12px',
                            cursor: 'pointer',
                            fontSize: '0.95rem',
                            transition: 'all 0.2s',
                            height: '46px',
                            width: '46px'
                          }}
                          title="Delete selected sound effect"
                        >
                          🗑️
                        </button>
                      )}
                    </div>

                    {transitionSound !== 'none' && (
                      <div style={{
                        marginTop: '10px',
                        padding: '10px',
                        borderRadius: '8px',
                        background: 'rgba(15, 23, 42, 0.4)',
                        border: '1px solid rgba(255, 255, 255, 0.05)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px'
                      }}>
                        <button
                          type="button"
                          onClick={toggleTransitionPreview}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: previewingTransition ? 'rgba(239, 68, 68, 0.15)' : 'rgba(56, 189, 248, 0.15)',
                            border: previewingTransition ? '1px solid rgba(239, 68, 68, 0.4)' : '1px solid rgba(56, 189, 248, 0.4)',
                            color: previewingTransition ? '#ef4444' : '#38bdf8',
                            borderRadius: '6px',
                            padding: '6px 12px',
                            fontSize: '0.75rem',
                            fontWeight: '700',
                            cursor: 'pointer',
                            gap: '6px',
                            transition: 'all 0.2s',
                            borderWidth: '1px',
                            borderStyle: 'solid'
                          }}
                        >
                          {previewingTransition ? (
                            <>
                              <span style={{ 
                                width: '8px', 
                                height: '8px', 
                                borderRadius: '50%', 
                                background: '#ef4444', 
                                display: 'inline-block'
                              }}></span>
                              Pause Preview
                            </>
                          ) : (
                            <>
                              <span style={{ fontSize: '0.65rem' }}>▶</span> Play Preview
                            </>
                          )}
                        </button>
                        <span style={{ fontSize: '0.7rem', color: '#64748b', textTransform: 'capitalize' }}>
                          Previewing: {transitionSound}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Submit / Craft Button */}
              <button 
                type="submit" 
                className="console-btn" 
                disabled={loading || !query.trim()}
                style={{ width: '100%', marginTop: '10px' }}
              >
                {loading ? (
                  <>
                    <Loader2 size={18} className="stage-spinner" />
                    <span>Analyzing Destination...</span>
                  </>
                ) : (
                  <>
                    <Sparkles size={18} />
                    <span>Craft Video Project</span>
                  </>
                )}
              </button>
            </form>

            {/* Debug Mode Switcher */}
            <div style={{ borderTop: '1px solid var(--border-glass)', paddingTop: '14px', display: 'flex', justifyContent: 'center' }}>
              <button
                type="button"
                onClick={() => setDebugMode(!debugMode)}
                className={`tab-btn ${debugMode ? 'active' : ''}`}
                style={{ 
                  fontSize: '0.8rem', 
                  padding: '5px 12px', 
                  borderRadius: '6px',
                  border: '1px solid var(--border-glass)',
                  background: debugMode ? 'rgba(168, 85, 247, 0.1)' : 'transparent'
                }}
              >
                <span style={{ 
                  display: 'inline-block', 
                  width: '6px', 
                  height: '6px', 
                  borderRadius: '50%', 
                  background: debugMode ? '#c084fc' : '#64748b', 
                  marginRight: '6px'
                }}></span>
                <span style={{ color: debugMode ? '#c084fc' : 'var(--text-secondary)' }}>Show Agent Dev Logs</span>
              </button>
            </div>
          </div>
        </div>

        {/* Right Side: Studio Preview Canvas */}
        <div className="canvas-panel animate-fade-in" style={{ animationDelay: '0.2s' }}>
          
          {/* Workspace Tabbing Headers */}
          {(videoScript || pics.length > 0 || videos.length > 0 || loading || videoUrl || videoGenerating) && (
            <div className="canvas-tabs-header">
              <button 
                className={`canvas-tab-btn ${canvasTab === 'video' ? 'active' : ''}`}
                onClick={() => setCanvasTab('video')}
              >
                <Tv size={16} />
                <span>Video Output</span>
              </button>
              <button 
                className={`canvas-tab-btn ${canvasTab === 'script' ? 'active' : ''}`}
                onClick={() => setCanvasTab('script')}
              >
                <FileText size={16} />
                <span>Narration & Script</span>
              </button>
              <button 
                className={`canvas-tab-btn ${canvasTab === 'gallery' ? 'active' : ''}`}
                onClick={() => setCanvasTab('gallery')}
              >
                <Layers size={16} />
                <span>Choose Media</span>
              </button>
              {debugMode && toolData.length > 0 && (
                <button 
                  className={`canvas-tab-btn ${canvasTab === 'logs' ? 'active' : ''}`}
                  onClick={() => setCanvasTab('logs')}
                >
                  <Compass size={16} />
                  <span>Agent IO Logs ({toolData.length})</span>
                </button>
              )}
            </div>
          )}

          {/* Active Canvas Board */}
          <div className="glass-card canvas-card">
            
            {/* 1. Empty Project Canvas State */}
            {!loading && !videoGenerating && !videoScript && pics.length === 0 && !videoUrl && (
              <div className="canvas-empty-state">
                <div className="canvas-empty-glow">
                  <Tv size={48} />
                </div>
                <h3 className="canvas-empty-title">Studio Canvas Empty</h3>
                <p className="canvas-empty-desc">
                  No active travel video project loaded. Enter a destination city on the left Console, customize your voice speaker or language, and hit "Craft Video Project" to begin generation!
                </p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <span style={{ fontSize: '0.75rem', fontWeight: '700', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Quick Suggestions</span>
                  <div className="canvas-quick-suggestions">
                    {['Goa beaches', 'Paris landmarks', 'Bali highlights', 'Orchha forts'].map((term) => (
                      <button
                        key={term}
                        onClick={() => handleQuickSearch(term)}
                        className="tab-btn"
                        style={{ fontSize: '0.8rem', padding: '5px 12px' }}
                      >
                        <MapPin size={10} />
                        <span>{term}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* 2. Loading / Compilation Canvas State */}
            {loading && (
              <div className="canvas-empty-state">
                <div className="glass-card agent-loading-card animate-glow" style={{ width: '100%', maxWidth: '550px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
                    <Loader2 size={20} className="stage-spinner" />
                    <span style={{ fontWeight: '700', fontSize: '1rem', color: '#e2e8f0' }}>Crafting Travel Project...</span>
                  </div>
                  <div className="loading-line header" style={{ width: '40%' }}></div>
                  <div className="loading-line body-1"></div>
                  <div className="loading-line body-2"></div>
                  <div className="loading-line body-3" style={{ width: '70%' }}></div>
                  <div className="loading-stages" style={{ marginTop: '20px' }}>
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
                  <div style={{ 
                    marginTop: '20px', 
                    paddingTop: '12px',
                    borderTop: '1px solid rgba(255, 255, 255, 0.05)',
                    display: 'flex', 
                    justifyContent: 'space-between', 
                    alignItems: 'center',
                    fontSize: '0.85rem',
                    color: '#94a3b8'
                  }}>
                    <span>Time Elapsed:</span>
                    <span style={{ fontWeight: '700', color: '#38bdf8', fontFamily: 'monospace', fontSize: '1rem' }}>{chatElapsed}s</span>
                  </div>
                </div>
              </div>
            )}

            {/* 3. Error state */}
            {!loading && error && (
              <div className="canvas-empty-state">
                <AlertCircle size={40} style={{ color: '#ef4444', marginBottom: '14px' }} />
                <h3 className="canvas-empty-title" style={{ color: '#fca5a5' }}>Generation Failed</h3>
                <p className="canvas-empty-desc">{error}</p>
              </div>
            )}

            {/* 4. Active Tab: Video Compilation */}
            {!loading && canvasTab === 'video' && (videoScript || videoUrl || videoGenerating) && (
              <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                
                {/* Generate Video Action Panel if not compiled yet */}
                {!videoUrl && !videoGenerating && (
                  <div className="canvas-empty-state" style={{ flex: 1 }}>
                    <Film size={40} style={{ color: 'var(--primary-color)', marginBottom: '14px' }} />
                    <h3 className="canvas-empty-title">Ready to Compile Video</h3>
                    <p className="canvas-empty-desc">
                      The travel script narration and media assets have been gathered. Click compile below to render the final travel vlog!
                    </p>
                    <button
                      type="button"
                      onClick={handleGenerateVideo}
                      className="console-btn"
                      style={{ padding: '12px 28px' }}
                    >
                      <Film size={16} />
                      <span>Compile Travel Video ({aspectRatio === 'portrait' ? '9:16 Portrait' : '16:9 Wide'})</span>
                    </button>
                  </div>
                )}

                {/* Video Generation Rendering Progress */}
                {videoGenerating && (
                  <div className="canvas-empty-state" style={{ flex: 1 }}>
                    <div style={{ width: '100%', maxWidth: '480px', padding: '20px', background: 'rgba(15, 23, 42, 0.4)', borderRadius: '12px', border: '1px solid var(--border-glass)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
                        <Loader2 size={18} className="stage-spinner" />
                        <span style={{ fontWeight: '700', fontSize: '0.95rem', color: '#e2e8f0' }}>Rendering Vlog Timeline...</span>
                      </div>
                      <div style={{ marginBottom: '16px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                          <span style={{ fontSize: '0.85rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: '700', letterSpacing: '0.05em' }}>
                            {realProgress.stage === 'rendering' ? '🎬 Rendering Video' : '⚙️ Preparing Assets'}
                          </span>
                          <span style={{ fontSize: '0.95rem', fontWeight: '700', color: 'var(--primary-color)' }}>
                            {realProgress.percent}%
                          </span>
                        </div>
                        {/* Progress Bar Container */}
                        <div style={{ width: '100%', height: '8px', background: 'rgba(255,255,255,0.05)', borderRadius: '999px', overflow: 'hidden', border: '1px solid rgba(255,255,255,0.05)' }}>
                          <div style={{
                            width: `${realProgress.percent}%`,
                            height: '100%',
                            background: 'linear-gradient(90deg, var(--primary-color), var(--accent-purple))',
                            borderRadius: '999px',
                            transition: 'width 0.4s cubic-bezier(0.4, 0, 0.2, 1)'
                          }} />
                        </div>
                      </div>

                      {/* Detail Message */}
                      <div style={{ 
                        padding: '10px 14px', 
                        background: 'rgba(0, 0, 0, 0.25)', 
                        border: '1px solid rgba(255, 255, 255, 0.05)', 
                        borderRadius: '8px', 
                        fontSize: '0.85rem', 
                        color: '#cbd5e1',
                        fontFamily: 'monospace',
                        minHeight: '40px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        lineHeight: '1.4'
                      }}>
                        <Loader2 size={12} className="stage-spinner" />
                        <span>{realProgress.message || 'Initializing pipeline...'}</span>
                      </div>
                      <div style={{ 
                        marginTop: '16px', 
                        paddingTop: '10px',
                        borderTop: '1px solid rgba(255, 255, 255, 0.05)',
                        display: 'flex', 
                        justifyContent: 'space-between', 
                        alignItems: 'center',
                        fontSize: '0.85rem',
                        color: '#94a3b8'
                      }}>
                        <span>Total Rendering Time:</span>
                        <span style={{ fontWeight: '600', color: '#fbbf24', fontFamily: 'monospace', fontSize: '0.95rem' }}>{videoElapsed}s</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Compiled Video Player */}
                {videoUrl && !videoGenerating && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', flex: 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <h3 style={{ fontSize: '1.2rem', fontWeight: '700', color: '#e2e8f0' }}>Final Render</h3>
                        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Resolution: {aspectRatio === 'portrait' ? '1080x1920 (Portrait)' : '1920x1080 (Wide)'}</p>
                      </div>
                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <a
                          href={videoUrl}
                          download={`${query.replace(/\s+/g, '_')}_vlog.mp4`}
                          className="console-btn"
                          style={{ padding: '8px 16px', fontSize: '0.85rem', background: 'linear-gradient(135deg, #22c55e, #15803d)' }}
                        >
                          <Download size={14} />
                          <span>Download MP4</span>
                        </a>

                        <button
                          type="button"
                          onClick={handleGDriveUpload}
                          disabled={gdriveUploading || !gdriveConnected}
                          className="console-btn"
                          style={{ 
                            padding: '8px 16px', 
                            fontSize: '0.85rem', 
                            background: gdriveLink ? 'rgba(34, 197, 94, 0.15)' : 'rgba(56, 189, 248, 0.15)',
                            border: gdriveLink ? '1px solid rgba(34, 197, 94, 0.4)' : '1px solid rgba(56, 189, 248, 0.4)',
                            color: gdriveLink ? '#4ade80' : '#38bdf8',
                            cursor: 'pointer'
                          }}
                        >
                          {gdriveUploading ? (
                            <>
                              <Loader2 size={14} className="stage-spinner" />
                              <span>Uploading...</span>
                            </>
                          ) : gdriveLink ? (
                            <>
                              <span style={{ fontSize: '0.9rem' }}>✓</span>
                              <span>Uploaded to Drive</span>
                            </>
                          ) : (
                            <>
                              <Cloud size={14} />
                              <span>Upload to Drive</span>
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          onClick={connectGoogleDrive}
                          className="console-btn"
                          style={{
                            padding: '8px 16px',
                            fontSize: '0.85rem',
                            background: gdriveConnected ? 'rgba(34, 197, 94, 0.15)' : 'rgba(56, 189, 248, 0.15)',
                            border: gdriveConnected ? '1px solid rgba(34, 197, 94, 0.4)' : '1px solid rgba(56, 189, 248, 0.4)',
                            color: gdriveConnected ? '#4ade80' : '#38bdf8',
                          }}
                        >
                          <Cloud size={14} />
                          <span>{gdriveConnected ? 'Drive Connected' : 'Connect Drive'}</span>
                        </button>
                      </div>
                    </div>

                    {!gdriveConnected && (
                      <p style={{ margin: 0, color: '#94a3b8', fontSize: '0.8rem' }}>
                        Connect your personal Google Drive once to enable uploads.
                      </p>
                    )}
                    
                    <div className="canvas-video-wrapper">
                      <video
                        src={videoUrl}
                        controls
                        className="canvas-video-player"
                        style={{
                          maxHeight: aspectRatio === 'portrait' ? '650px' : '480px',
                          aspectRatio: aspectRatio === 'portrait' ? '9/16' : '16/9',
                          objectFit: 'contain'
                        }}
                      />
                    </div>

                    {/* Google Drive Uploading Progress */}
                    {gdriveUploading && (
                      <div style={{
                        padding: '16px',
                        background: 'rgba(56, 189, 248, 0.08)',
                        border: '1px solid rgba(56, 189, 248, 0.25)',
                        borderRadius: '10px',
                        marginTop: '10px'
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <Loader2 size={16} className="stage-spinner" />
                            <span style={{ fontSize: '0.85rem', color: '#cbd5e1', fontWeight: '700' }}>
                              Uploading Vlog to Google Drive...
                            </span>
                          </div>
                          <span style={{ fontSize: '0.9rem', fontWeight: '700', color: '#38bdf8' }}>
                            {uploadProgress.percent}%
                          </span>
                        </div>
                        
                        {/* Progress Bar Track */}
                        <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.05)', borderRadius: '999px', overflow: 'hidden', marginBottom: '8px' }}>
                          <div style={{
                            width: `${uploadProgress.percent}%`,
                            height: '100%',
                            background: 'linear-gradient(90deg, #38bdf8, #0ea5e9)',
                            borderRadius: '999px',
                            transition: 'width 0.3s ease-out'
                          }} />
                        </div>
                        
                        <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontFamily: 'monospace' }}>
                          {uploadProgress.message || 'Connecting to Google Drive API...'}
                        </div>
                      </div>
                    )}

                    {/* Google Drive Status Notification */}
                    {gdriveLink && (
                      <div style={{
                        padding: '12px 16px',
                        background: 'rgba(34, 197, 94, 0.15)',
                        border: '1px solid rgba(34, 197, 94, 0.3)',
                        borderRadius: '8px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '12px',
                        marginTop: '10px'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span style={{ fontSize: '1.2rem' }}>☁️</span>
                          <span style={{ color: '#4ade80', fontSize: '0.9rem', fontWeight: '600' }}>Video successfully uploaded to Google Drive!</span>
                        </div>
                        <a 
                          href={gdriveLink} 
                          target="_blank" 
                          rel="noopener noreferrer"
                          className="tab-btn active"
                          style={{
                            padding: '6px 12px',
                            fontSize: '0.8rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                            border: '1px solid rgba(34, 197, 94, 0.4)',
                            background: 'rgba(34, 197, 94, 0.1)',
                            borderRadius: '6px',
                            textDecoration: 'none',
                            color: '#4ade80',
                            fontWeight: '700'
                          }}
                        >
                          <ExternalLink size={12} />
                          <span>View on Drive</span>
                        </a>
                      </div>
                    )}

                    {gdriveError && (
                      <div style={{
                        padding: '12px 16px',
                        background: 'rgba(239, 68, 68, 0.1)',
                        border: '1px solid rgba(239, 68, 68, 0.3)',
                        borderRadius: '8px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '8px',
                        marginTop: '10px'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <AlertCircle size={16} style={{ color: '#f87171' }} />
                          <span style={{ color: '#fca5a5', fontSize: '0.9rem', fontWeight: '700' }}>Google Drive Upload Failed</span>
                        </div>
                        <pre style={{ 
                          margin: 0, 
                          whiteSpace: 'pre-wrap', 
                          fontFamily: 'monospace', 
                          fontSize: '0.75rem', 
                          color: '#fca5a5', 
                          background: 'rgba(0,0,0,0.3)', 
                          padding: '8px', 
                          borderRadius: '6px' 
                        }}>
                          {gdriveError}
                        </pre>
                      </div>
                    )}
                  </div>
                )}

                {/* Video Generation Error */}
                {videoError && (
                  <div style={{ marginTop: '20px', padding: '12px 16px', borderRadius: '8px', background: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <AlertCircle size={18} style={{ color: '#f87171' }} />
                    <span style={{ color: '#fca5a5', fontSize: '0.9rem' }}>{videoError}</span>
                  </div>
                )}
              </div>
            )}

            {/* 5. Active Tab: Script & Narration */}
            {!loading && canvasTab === 'script' && videoScript && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-glass)', paddingBottom: '14px' }}>
                  <div>
                    <h3 style={{ fontSize: '1.2rem', fontWeight: '700', color: '#e2e8f0' }}>Vlog Script & Description</h3>
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Language: {selectedLanguage} | Voice: {selectedSpeaker}</p>
                  </div>
                  <button
                    type="button"
                    onClick={handleTtsPlay}
                    disabled={ttsLoading}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      fontSize: '0.85rem',
                      padding: '8px 16px',
                      borderRadius: '8px',
                      border: '1px solid rgba(165, 180, 252, 0.3)',
                      background: isPlaying ? 'rgba(239, 68, 68, 0.1)' : 'rgba(99, 102, 241, 0.1)',
                      color: isPlaying ? '#f87171' : '#a5b4fc',
                      cursor: 'pointer',
                      fontWeight: '600'
                    }}
                  >
                    {ttsLoading ? (
                      <>
                        <Loader2 size={14} className="stage-spinner" />
                        <span>Synthesizing...</span>
                      </>
                    ) : isPlaying ? (
                      <>
                        <Square size={14} fill="#f87171" style={{ stroke: 'none' }} />
                        <span>Stop Voiceover</span>
                      </>
                    ) : (
                      <>
                        <Volume2 size={14} />
                        <span>Listen Voiceover</span>
                      </>
                    )}
                  </button>
                </div>

                <div className="glass-card" style={{ padding: '20px', background: 'rgba(15, 23, 42, 0.3)', border: '1px solid var(--border-glass)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <h4 style={{ fontSize: '0.8rem', fontWeight: '700', color: '#818cf8', textTransform: 'uppercase' }}>Voiceover Script Narration</h4>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Editable · keep the [attraction: ...] markers</span>
                  </div>
                  <textarea
                    className="canvas-script-box"
                    value={videoScript}
                    onChange={(e) => setVideoScript(e.target.value)}
                    disabled={editingScript}
                    spellCheck={false}
                    style={{
                      width: '100%',
                      minHeight: '260px',
                      resize: 'vertical',
                      font: 'inherit',
                      lineHeight: '1.7',
                      color: '#e2e8f0',
                      background: 'rgba(2, 6, 23, 0.4)',
                      border: '1px solid var(--border-glass)',
                      borderRadius: '10px',
                      padding: '14px',
                      boxSizing: 'border-box',
                      opacity: editingScript ? 0.6 : 1,
                    }}
                  />

                  {/* Ask the AI agent to revise the script */}
                  <div style={{ marginTop: '14px', display: 'flex', gap: '8px', alignItems: 'stretch' }}>
                    <input
                      type="text"
                      value={editInstruction}
                      onChange={(e) => setEditInstruction(e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleAgentEditScript(); }}
                      disabled={editingScript || !videoScript.trim()}
                      placeholder="Tell the AI how to edit, e.g. 'make it shorter' or 'add more about the food'"
                      style={{
                        flex: 1,
                        font: 'inherit',
                        fontSize: '0.85rem',
                        color: '#e2e8f0',
                        background: 'rgba(2, 6, 23, 0.4)',
                        border: '1px solid var(--border-glass)',
                        borderRadius: '8px',
                        padding: '10px 12px',
                        boxSizing: 'border-box',
                      }}
                    />
                    <button
                      type="button"
                      onClick={handleAgentEditScript}
                      disabled={editingScript || !editInstruction.trim() || !videoScript.trim()}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        fontSize: '0.85rem',
                        padding: '8px 16px',
                        borderRadius: '8px',
                        border: '1px solid rgba(56, 189, 248, 0.3)',
                        background: 'rgba(56, 189, 248, 0.12)',
                        color: '#38bdf8',
                        cursor: (editingScript || !editInstruction.trim() || !videoScript.trim()) ? 'not-allowed' : 'pointer',
                        fontWeight: '600',
                        whiteSpace: 'nowrap',
                        opacity: (editingScript || !editInstruction.trim() || !videoScript.trim()) ? 0.5 : 1,
                      }}
                    >
                      {editingScript ? (
                        <>
                          <Loader2 size={14} className="stage-spinner" />
                          <span>Revising...</span>
                        </>
                      ) : (
                        <>
                          <Sparkles size={14} />
                          <span>Ask AI to Edit</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* 6. Active Tab: Asset Selector Board */}
            {!loading && canvasTab === 'gallery' && (pics.length > 0 || videos.length > 0) && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                <div style={{ borderBottom: '1px solid var(--border-glass)', paddingBottom: '14px' }}>
                  <h3 style={{ fontSize: '1.2rem', fontWeight: '700', color: '#e2e8f0' }}>Choose Segment Media</h3>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                    Select <strong>2 items</strong> (videos/photos) per attraction — or <strong>3 photos</strong> when no video is available. If not chosen, a default selection will be compiled.
                  </p>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
                  {Array.from(new Set([
                    ...videos.map(v => v.label),
                    ...pics.map(p => p.label)
                  ])).filter(Boolean).map((label) => {
                    const placeVideos = videos.filter(v => v.label === label);
                    const placePhotos = pics.filter(p => p.label === label);
                    const selected = selectedMedia[label] || [];
                    // 3 photos allowed when no video exists for this attraction, else 2.
                    const maxSelect = placeVideos.length > 0 ? 2 : 3;
                    const isReady = selected.length === maxSelect;
                    const remaining = maxSelect - selected.length;

                    return (
                      <div 
                        key={label}
                        className="glass-card" 
                        style={{ 
                          padding: '20px', 
                          background: 'rgba(15, 23, 42, 0.25)', 
                          border: isReady ? '1px solid rgba(56, 189, 248, 0.2)' : '1px solid var(--border-glass)',
                          boxShadow: isReady ? '0 8px 30px rgba(56, 189, 248, 0.03)' : 'none'
                        }}
                      >
                        {/* Attraction header with indicator badges */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '1.2rem' }}>📍</span>
                            <h4 style={{ fontSize: '1.05rem', fontWeight: '700', color: '#f1f5f9' }}>{label}</h4>
                          </div>

                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            {isReady ? (
                              <span style={{ 
                                background: 'rgba(34, 197, 94, 0.15)', 
                                border: '1px solid rgba(34, 197, 94, 0.4)', 
                                color: '#4ade80',
                                fontSize: '0.75rem',
                                fontWeight: '700',
                                padding: '4px 10px',
                                borderRadius: '20px'
                              }}>
                                Ready ({selected.length}/{maxSelect} Selected)
                              </span>
                            ) : (
                              <span style={{ 
                                background: 'rgba(245, 158, 11, 0.15)', 
                                border: '1px solid rgba(245, 158, 11, 0.4)', 
                                color: '#fbbf24',
                                fontSize: '0.75rem',
                                fontWeight: '700',
                                padding: '4px 10px',
                                borderRadius: '20px'
                              }}>
                                {`Select ${remaining} more item${remaining > 1 ? 's' : ''} of ${maxSelect} (or fallback will be used)`}
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Combined Grid of Video and Photo candidates */}
                        <div 
                          style={{ 
                            display: 'grid', 
                            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', 
                            gap: '14px' 
                          }}
                        >
                          {/* Video candidates (up to 4) */}
                          {placeVideos.map((vid, i) => {
                            const isSelected = selected.some(item => item.type === 'video' && item.url === vid.url);
                            return (
                              <div
                                key={`vid-${i}`}
                                className="media-asset-card"
                                style={{
                                  position: 'relative',
                                  borderRadius: '10px',
                                  overflow: 'hidden',
                                  background: '#020617',
                                  border: isSelected ? '2px solid #38bdf8' : '1px solid var(--border-glass)',
                                  boxShadow: isSelected ? '0 0 15px rgba(56, 189, 248, 0.35)' : 'none',
                                  cursor: 'pointer',
                                  aspectRatio: '16/10',
                                  transition: 'all 0.2s ease'
                                }}
                                onClick={() => handleToggleMedia(label, { ...vid, type: 'video' })}
                                onMouseEnter={(e) => {
                                  const v = e.currentTarget.querySelector('video');
                                  if (v) v.play().catch(() => {});
                                }}
                                onMouseLeave={(e) => {
                                  const v = e.currentTarget.querySelector('video');
                                  if (v) { v.pause(); v.currentTime = 0; }
                                }}
                              >
                                <video
                                  src={vid.url}
                                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                                  muted
                                  playsInline
                                />
                                <MediaHoverDetails asset={vid} type="video" />
                                
                                {/* Video indicator label */}
                                <div style={{ position: 'absolute', bottom: '6px', left: '6px', background: 'rgba(15, 23, 42, 0.75)', color: '#38bdf8', fontSize: '0.65rem', padding: '2px 6px', borderRadius: '4px', border: '1px solid rgba(56,189,248,0.2)', fontWeight: '700' }}>
                                  📹 Video
                                </div>

                                {/* Magnifier button to enlarge */}
                                <button
                                  type="button"
                                  style={{
                                    position: 'absolute',
                                    bottom: '6px',
                                    right: '6px',
                                    background: 'rgba(15, 23, 42, 0.8)',
                                    color: '#f8fafc',
                                    border: '1px solid rgba(255,255,255,0.1)',
                                    borderRadius: '4px',
                                    padding: '4px',
                                    cursor: 'pointer',
                                    zIndex: 10
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setLightboxItem({ type: 'video', url: vid.url });
                                  }}
                                  title="Enlarge Video"
                                >
                                  🔍
                                </button>

                                {/* Checkmark Overlay */}
                                {isSelected && (
                                  <div style={{
                                    position: 'absolute',
                                    top: '6px',
                                    right: '6px',
                                    background: '#38bdf8',
                                    color: '#0f172a',
                                    width: '20px',
                                    height: '20px',
                                    borderRadius: '50%',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    fontSize: '0.75rem',
                                    fontWeight: '900',
                                    boxShadow: '0 2px 5px rgba(0,0,0,0.3)',
                                    zIndex: 8
                                  }}>
                                    ✓
                                  </div>
                                )}
                              </div>
                            );
                          })}

                          {/* Photo candidates (Up to 3) */}
                          {placePhotos.map((pic, i) => {
                            const isSelected = selected.some(item => item.type === 'photo' && item.url === pic.url);
                            return (
                              <div
                                key={`pic-${i}`}
                                className="media-asset-card"
                                style={{
                                  position: 'relative',
                                  borderRadius: '10px',
                                  overflow: 'hidden',
                                  background: '#020617',
                                  border: isSelected ? '2px solid #38bdf8' : '1px solid var(--border-glass)',
                                  boxShadow: isSelected ? '0 0 15px rgba(56, 189, 248, 0.35)' : 'none',
                                  cursor: 'pointer',
                                  aspectRatio: '16/10',
                                  transition: 'all 0.2s ease'
                                }}
                                onClick={() => handleToggleMedia(label, { ...pic, type: 'photo' })}
                              >
                                <img
                                  src={pic.url}
                                  alt=""
                                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                                  loading="lazy"
                                />
                                <MediaHoverDetails asset={pic} type="photo" />

                                {/* Photo indicator label */}
                                <div style={{ position: 'absolute', bottom: '6px', left: '6px', background: 'rgba(15, 23, 42, 0.75)', color: '#fbbf24', fontSize: '0.65rem', padding: '2px 6px', borderRadius: '4px', border: '1px solid rgba(251,191,36,0.2)', fontWeight: '700' }}>
                                  🖼️ Photo
                                </div>

                                {/* Magnifier button to enlarge */}
                                <button
                                  type="button"
                                  style={{
                                    position: 'absolute',
                                    bottom: '6px',
                                    right: '6px',
                                    background: 'rgba(15, 23, 42, 0.8)',
                                    color: '#f8fafc',
                                    border: '1px solid rgba(255,255,255,0.1)',
                                    borderRadius: '4px',
                                    padding: '4px',
                                    cursor: 'pointer',
                                    zIndex: 10
                                  }}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setLightboxItem({ type: 'photo', url: pic.url });
                                  }}
                                  title="Enlarge Photo"
                                >
                                  🔍
                                </button>

                                {/* Checkmark Overlay */}
                                {isSelected && (
                                  <div style={{
                                    position: 'absolute',
                                    top: '6px',
                                    right: '6px',
                                    background: '#38bdf8',
                                    color: '#0f172a',
                                    width: '20px',
                                    height: '20px',
                                    borderRadius: '50%',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    fontSize: '0.75rem',
                                    fontWeight: '900',
                                    boxShadow: '0 2px 5px rgba(0,0,0,0.3)',
                                    zIndex: 8
                                  }}>
                                    ✓
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 7. Active Tab: Dev Logs */}
            {!loading && canvasTab === 'logs' && debugMode && toolData.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <h3 style={{ fontSize: '1.2rem', fontWeight: '700', color: '#e2e8f0', borderBottom: '1px solid var(--border-glass)', paddingBottom: '14px' }}>
                  Agent Execution Logs (Tools Called)
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {toolData.map((call, idx) => (
                    <details key={idx} style={{ background: 'rgba(15, 23, 42, 0.4)', borderRadius: '10px', border: '1px solid var(--border-glass)', overflow: 'hidden' }}>
                      <summary style={{ padding: '12px 16px', cursor: 'pointer', fontWeight: '600', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', userSelect: 'none' }}>
                        <span style={{ fontFamily: 'monospace', color: '#a855f7' }}>{call.tool_name}</span>
                        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Click to view details</span>
                      </summary>
                      <div style={{ padding: '16px', borderTop: '1px solid var(--border-glass)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        <div>
                          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: '600', marginBottom: '4px' }}>Tool Arguments</div>
                          <pre style={{ background: 'rgba(3, 7, 18, 0.5)', padding: '10px', borderRadius: '6px', overflowX: 'auto', fontFamily: 'monospace', fontSize: '0.8rem', color: '#38bdf8' }}>
                            {JSON.stringify(call.tool_input, null, 2)}
                          </pre>
                        </div>
                        <div>
                          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: '600', marginBottom: '4px' }}>Tool Output</div>
                          <pre style={{ background: 'rgba(3, 7, 18, 0.5)', padding: '10px', borderRadius: '6px', overflowX: 'auto', maxHeight: '200px', overflowY: 'auto', fontFamily: 'monospace', fontSize: '0.8rem', color: '#e2e8f0' }}>
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
        </div>

      </div>

      {/* Full-screen Lightbox Modal */}
      {lightboxItem && (
        <div className="lightbox-modal" onClick={() => setLightboxItem(null)}>
          <button className="lightbox-close" onClick={() => setLightboxItem(null)}>
            <X size={24} />
          </button>
          <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
            {lightboxItem.type === 'photo' ? (
              <img src={lightboxItem.url} alt="Enlarged" className="lightbox-media" />
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
