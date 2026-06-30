import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { MessageSquare, CloudUpload, BarChart2, DollarSign, SquareTerminal, Building, Send, ChevronDown, ChevronRight, ShieldAlert, Activity, Coins, Clock, Database, AlertCircle, CheckCircle2, Layers, Settings, X, ExternalLink } from 'lucide-react';

const queryClient = new QueryClient();

interface ApartmentContextType {
  apartment: string;
  setApartment: (apt: string) => void;
}

const ApartmentContext = createContext<ApartmentContextType | undefined>(undefined);

export function useApartment() {
  const context = useContext(ApartmentContext);
  if (!context) throw new Error("useApartment must be used within ApartmentProvider");
  return context;
}

function SettingsModal({ onClose }: { onClose: () => void }) {
  const { apartment } = useApartment();
  const [embeddingModel, setEmbeddingModel] = useState('');
  const [extractionModel, setExtractionModel] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState('');
  const [resetMessage, setResetMessage] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['settings', apartment],
    queryFn: async () => {
      const res = await fetch(`/api/${apartment}/settings`);
      return res.json();
    },
    enabled: !!apartment
  });

  useEffect(() => {
    if (data) {
      setEmbeddingModel(data.embedding_model || '');
      setExtractionModel(data.extraction_model || '');
    }
  }, [data]);

  const handleSave = async () => {
    setIsSaving(true);
    setSaveMessage('');
    try {
      const res = await fetch(`/api/${apartment}/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          embedding_model: embeddingModel || null,
          extraction_model: extractionModel || null
        })
      });
      if (!res.ok) throw new Error('Failed to save settings');
      setSaveMessage('Settings saved successfully.');
      queryClient.invalidateQueries({ queryKey: ['status', apartment] });
    } catch (err: any) {
      setSaveMessage(`Error: ${err.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = async () => {
    setResetMessage('');
    try {
      const res = await fetch(`/api/${apartment}/reset-failed`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error('Reset failed');
      setResetMessage(`Success: ${data.message}`);
      queryClient.invalidateQueries({ queryKey: ['status', apartment] });
    } catch (err: any) {
      setResetMessage(`Error: ${err.message}`);
    }
  };

  return (
    <div className="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-lg overflow-hidden">
        <div className="flex justify-between items-center p-4 border-b border-slate-200">
          <h3 className="font-semibold text-lg text-slate-800">Advanced Settings ({apartment})</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600"><X size={20} /></button>
        </div>
        <div className="p-6 space-y-6">
          {isLoading ? (
            <p className="text-sm text-slate-500">Loading settings...</p>
          ) : (
            <>
              <div className="space-y-4">
                <h4 className="text-sm font-medium text-slate-800 border-b border-slate-100 pb-1">Models Configuration</h4>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Embedding Model</label>
                  <input type="text" value={embeddingModel} onChange={e => setEmbeddingModel(e.target.value)} className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2 text-sm focus:ring-blue-500 focus:border-blue-500" placeholder="e.g. text-embedding-3-small" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Extraction Model</label>
                  <input type="text" value={extractionModel} onChange={e => setExtractionModel(e.target.value)} className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2 text-sm focus:ring-blue-500 focus:border-blue-500" placeholder="e.g. gpt-4o-mini" />
                </div>
                <div className="flex items-center gap-4 pt-2">
                  <button onClick={handleSave} disabled={isSaving} className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-50">
                    {isSaving ? 'Saving...' : 'Save'}
                  </button>
                  {saveMessage && <span className={`text-sm ${saveMessage.startsWith('Error') ? 'text-red-600' : 'text-green-600'}`}>{saveMessage}</span>}
                </div>
              </div>

              <div className="space-y-4 pt-4 border-t border-slate-100">
                <h4 className="text-sm font-medium text-slate-800 border-b border-slate-100 pb-1">Error Recovery</h4>
                <p className="text-xs text-slate-500 leading-relaxed">
                  If raw messages failed during the extraction or indexing phase, reset their state to 'new' to requeue them without reprocessing everything.
                </p>
                <div className="flex items-center gap-4">
                  <button onClick={handleReset} className="bg-red-50 text-red-600 border border-red-200 px-4 py-2 rounded-lg text-sm font-medium hover:bg-red-100 transition-colors">
                    Reset Failed Messages
                  </button>
                  {resetMessage && <span className={`text-sm ${resetMessage.startsWith('Error') ? 'text-red-600' : 'text-green-600'}`}>{resetMessage}</span>}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function TopBar() {
  const { apartment, setApartment } = useApartment();
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ['apartments'],
    queryFn: async () => {
      const res = await fetch('/api/apartments');
      if (!res.ok) throw new Error('Failed to fetch apartments');
      return res.json() as Promise<{ apartments: string[] }>;
    }
  });

  // Auto-select first apartment if none selected
  useEffect(() => {
    if (!apartment && data?.apartments && data.apartments.length > 0) {
      setApartment(data.apartments[0]);
    }
  }, [apartment, data, setApartment]);

  return (
    <header className="bg-white border-b border-slate-200 px-8 py-4 flex items-center justify-between shadow-sm z-10">
      <h2 className="text-lg font-semibold text-slate-800">Dashboard</h2>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-3">
          <Building size={18} className="text-slate-500" />
          <select
            value={apartment}
            onChange={(e) => setApartment(e.target.value)}
            className="bg-slate-50 border border-slate-300 text-slate-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-48 p-2 cursor-pointer"
            disabled={isLoading || !!error}
          >
            {isLoading && <option value="">Loading...</option>}
            {error && <option value="">Error loading</option>}
            {!isLoading && !error && data?.apartments.length === 0 && <option value="">No apartments found</option>}
            {!isLoading && data?.apartments.map(apt => (
              <option key={apt} value={apt}>{apt}</option>
            ))}
          </select>
        </div>
        {apartment && (
          <button onClick={() => setIsSettingsOpen(true)} className="p-2 text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-lg transition-colors" title="Advanced Settings">
            <Settings size={20} />
          </button>
        )}
      </div>
      {isSettingsOpen && <SettingsModal onClose={() => setIsSettingsOpen(false)} />}
    </header>
  );
}

interface Citation {
  fact_id: string;
  source_count: number;
  latest_seen: string;
  snippet: string;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  citations?: Citation[];
  confidence?: 'high' | 'medium' | 'low' | 'none';
  privacy_note?: string | null;
}

function CitationView({ citation }: { citation: Citation }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="mt-2 border border-slate-200 rounded-md overflow-hidden bg-white text-sm">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 bg-slate-50 hover:bg-slate-100 text-slate-700 transition-colors"
      >
        <div className="flex items-center gap-2">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          <span className="font-medium text-xs">Source Snippet (Mentions: {citation.source_count})</span>
        </div>
        <span className="text-xs text-slate-500">Last seen: {citation.latest_seen.split('T')[0]}</span>
      </button>
      {expanded && (
        <div className="p-3 text-slate-600 border-t border-slate-200 italic bg-slate-50/50">
          "{citation.snippet}"
        </div>
      )}
    </div>
  );
}

function ChatInterface() {
  const { apartment } = useApartment();
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || !apartment) return;

    const userMsg: ChatMessage = { id: Date.now().toString(), role: 'user', text: query };
    setMessages(prev => [...prev, userMsg]);
    setQuery('');
    setIsLoading(true);

    try {
      const res = await fetch(`/api/${apartment}/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: userMsg.text, top_k: 10, max_facts: 5 })
      });

      if (!res.ok) throw new Error('Failed to fetch answer');
      const data = await res.json();

      const aiMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        text: data.answer,
        citations: data.citations,
        confidence: data.confidence,
        privacy_note: data.privacy_note
      };
      setMessages(prev => [...prev, aiMsg]);
    } catch (err) {
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(), role: 'assistant', text: "Sorry, I encountered an error connecting to the server.",
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  if (!apartment) {
    return <div className="flex items-center justify-center h-full text-slate-500">Please select an apartment to start chatting.</div>;
  }

  return (
    <div className="flex flex-col h-full bg-slate-50">
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {messages.length === 0 && (
          <div className="text-center text-slate-500 mt-10">
            <MessageSquare size={48} className="mx-auto mb-4 opacity-20" />
            <p className="text-lg font-medium">Welcome to AptJeeves</p>
            <p className="text-sm">Ask a question about {apartment}</p>
          </div>
        )}
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-3xl rounded-2xl px-5 py-4 ${msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-white border border-slate-200 shadow-sm text-slate-800'}`}>
              <p className="whitespace-pre-wrap leading-relaxed">{msg.text}</p>
              {msg.role === 'assistant' && (
                <div className="mt-4 flex flex-wrap gap-2 items-center">
                  {msg.confidence && (
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${msg.confidence === 'high' ? 'bg-green-100 text-green-700' : msg.confidence === 'medium' ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>
                      Confidence: {msg.confidence}
                    </span>
                  )}
                  {msg.privacy_note && (
                    <span className="px-2 py-1 rounded-full text-xs font-medium bg-purple-100 text-purple-700 flex items-center gap-1">
                      <ShieldAlert size={14} /> {msg.privacy_note}
                    </span>
                  )}
                </div>
              )}
              {msg.citations && msg.citations.length > 0 && (
                <div className="mt-4 space-y-2">
                  {msg.citations.map((cit, i) => <CitationView key={i} citation={cit} />)}
                </div>
              )}
            </div>
          </div>
        ))}
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-white border border-slate-200 shadow-sm rounded-2xl px-5 py-4 flex items-center gap-2">
              <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" />
              <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce delay-75" />
              <div className="w-2 h-2 bg-blue-400 rounded-full animate-bounce delay-150" />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="p-4 bg-white border-t border-slate-200">
        <form onSubmit={handleAsk} className="max-w-4xl mx-auto relative">
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`Ask about ${apartment}...`} disabled={isLoading} className="w-full bg-slate-50 border border-slate-300 text-slate-900 rounded-full pl-6 pr-14 py-3 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50" />
          <button type="submit" disabled={!query.trim() || isLoading} className="absolute right-2 top-2 p-2 bg-blue-600 text-white rounded-full hover:bg-blue-700 disabled:opacity-50 transition-colors">
            <Send size={18} />
          </button>
        </form>
      </div>
    </div>
  );
}

function IngestionManager() {
  const { apartment } = useApartment();
  const [platform, setPlatform] = useState('whatsapp');
  const [chatFile, setChatFile] = useState<File | null>(null);
  const [attachmentFolder, setAttachmentFolder] = useState<string>('');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string>('');
  const [isResetting, setIsResetting] = useState(false);
  const [resetStatus, setResetStatus] = useState('');
  const [isTriggeringExtraction, setIsTriggeringExtraction] = useState(false);
  const [isTriggeringIndexing, setIsTriggeringIndexing] = useState(false);

  const { data: statusData } = useQuery({
    queryKey: ['status', apartment],
    queryFn: async () => {
      if (!apartment) return null;
      const res = await fetch(`/api/${apartment}/status`);
      if (!res.ok) throw new Error('Failed to fetch status');
      return res.json();
    },
    refetchInterval: 3000,
    enabled: !!apartment,
  });

  const { data: logsData } = useQuery({
    queryKey: ['logs', apartment, 'ingestion-page'],
    queryFn: async () => {
      if (!apartment) return null;
      const res = await fetch(`/api/${apartment}/logs?limit=30`);
      if (!res.ok) throw new Error('Failed to fetch logs');
      return res.json();
    },
    refetchInterval: 3000,
    enabled: !!apartment,
  });

  const handleChatFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setChatFile(e.target.files[0]);
    } else {
      setChatFile(null);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatFile || !apartment) return;

    setIsUploading(true);
    setUploadMessage('');

    const formData = new FormData();
    formData.append('platform', platform);
    formData.append('primary_filename', chatFile.name);
    formData.append('files', chatFile);
    if (attachmentFolder.trim()) {
      formData.append('attachment_folder', attachmentFolder.trim());
    }

    try {
      const res = await fetch(`/api/${apartment}/upload`, {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Upload failed');
      setUploadMessage(data.message || 'Upload started successfully.');
      setChatFile(null);
      setAttachmentFolder('');
      const fileInputs = document.querySelectorAll('input[type="file"]');
      fileInputs.forEach((input: any) => input.value = '');
    } catch (err: any) {
      setUploadMessage(`Error: ${err.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  const handleResetFailed = async () => {
    setIsResetting(true);
    setResetStatus('');
    try {
      const res = await fetch(`/api/${apartment}/reset-failed`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed to reset messages');
      const data = await res.json();
      setResetStatus(`Success: Reset ${data.details?.count || 0} failed messages.`);
      queryClient.invalidateQueries({ queryKey: ['status', apartment] });
    } catch (err: any) {
      setResetStatus(`Error: ${err.message}`);
    } finally {
      setIsResetting(false);
    }
  };

  const handleTriggerExtraction = async () => {
    setIsTriggeringExtraction(true);
    try {
      const res = await fetch(`/api/${apartment}/extract`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed to trigger extraction');
      queryClient.invalidateQueries({ queryKey: ['status', apartment] });
      queryClient.invalidateQueries({ queryKey: ['logs', apartment] });
    } catch (err: any) {
      alert(`Error triggering extraction: ${err.message}`);
    } finally {
      setIsTriggeringExtraction(false);
    }
  };

  const handleTriggerIndexing = async () => {
    setIsTriggeringIndexing(true);
    try {
      const res = await fetch(`/api/${apartment}/index`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed to trigger indexing');
      queryClient.invalidateQueries({ queryKey: ['status', apartment] });
      queryClient.invalidateQueries({ queryKey: ['logs', apartment] });
    } catch (err: any) {
      alert(`Error triggering indexing: ${err.message}`);
    } finally {
      setIsTriggeringIndexing(false);
    }
  };

  if (!apartment) {
    return <div className="flex items-center justify-center h-full text-slate-500">Please select an apartment to manage ingestion.</div>;
  }

  // Evaluate Ingestion Step
  const lastImport = statusData?.history?.[0];
  let ingestStatus = 'idle';
  if (isUploading) {
    ingestStatus = 'uploading';
  } else if (lastImport) {
    ingestStatus = lastImport.messages === 0 ? 'completed-dedup' : 'completed';
  }

  // Check background task activities from logs
  const lastExtractionEvent = logsData?.events?.find(
    (e: any) => e.stage === 'extraction' && e.event_type && e.event_type.startsWith('background_task_')
  );
  const isExtractionActive = lastExtractionEvent?.event_type === 'background_task_started' || lastExtractionEvent?.event_type === 'background_task_progress';

  const lastIndexingEvent = logsData?.events?.find(
    (e: any) => e.stage === 'indexing' && e.event_type && e.event_type.startsWith('background_task_')
  );
  const isIndexingActive = lastIndexingEvent?.event_type === 'background_task_started' || lastIndexingEvent?.event_type === 'background_task_progress';

  // Evaluate Extraction Step
  let extractionStatus = 'idle';
  if (statusData) {
    if (isExtractionActive) {
      extractionStatus = 'in-progress';
    } else if (statusData.messages.total_failed > 0) {
      extractionStatus = 'failed';
    } else if (statusData.messages.total_new > 0) {
      extractionStatus = 'pending-idle';
    } else if (statusData.messages.total_extracted > 0) {
      extractionStatus = 'completed';
    }
  }

  // Parse extraction error details from logs
  const lastExtractionErrorEvent = logsData?.events?.find(
    (e: any) => e.stage === 'extraction' && e.status === 'error'
  );
  let extractionErrorText = '';
  if (lastExtractionErrorEvent) {
    try {
      const parsed = JSON.parse(lastExtractionErrorEvent.details);
      extractionErrorText = parsed.error || lastExtractionErrorEvent.details;
    } catch {
      extractionErrorText = lastExtractionErrorEvent.details;
    }
  }

  // Evaluate Indexing Step
  let indexingStatus = 'idle';
  if (statusData) {
    if (isIndexingActive) {
      indexingStatus = 'in-progress';
    } else if (statusData.facts.pending_indexing > 0) {
      indexingStatus = 'pending-idle';
    } else if (statusData.vectors.active > 0) {
      indexingStatus = 'completed';
    }
  }

  // Parse indexing error details from logs
  const lastIndexingErrorEvent = logsData?.events?.find(
    (e: any) => e.stage === 'indexing' && e.status === 'error'
  );
  let indexingErrorText = '';
  if (lastIndexingErrorEvent) {
    try {
      const parsed = JSON.parse(lastIndexingErrorEvent.details);
      indexingErrorText = parsed.error || lastIndexingErrorEvent.details;
    } catch {
      indexingErrorText = lastIndexingErrorEvent.details;
    }
    if (indexingStatus === 'idle' || indexingStatus === 'completed') {
      // Show failed status if we have error logs but not currently running
    }
  }

  // Parse latest extraction progress
  const latestExtractionProgressEvent = logsData?.events?.find(
    (e: any) => e.stage === 'extraction' && e.event_type === 'background_task_progress'
  );
  let extractionProgressDetails = null;
  if (latestExtractionProgressEvent) {
    try {
      extractionProgressDetails = JSON.parse(latestExtractionProgressEvent.details);
    } catch {}
  }

  // Parse latest indexing progress
  const latestIndexingProgressEvent = logsData?.events?.find(
    (e: any) => e.stage === 'indexing' && e.event_type === 'background_task_progress'
  );
  let indexingProgressDetails = null;
  if (latestIndexingProgressEvent) {
    try {
      indexingProgressDetails = JSON.parse(latestIndexingProgressEvent.details);
    } catch {}
  }

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-slate-800 mb-2">Ingestion & Task Manager</h1>
        <p className="text-slate-600">Upload chat exports and monitor background processing for <span className="font-semibold text-blue-600">{apartment}</span>.</p>
      </div>

      <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6">
        <h2 className="text-xl font-semibold text-slate-800 mb-4">Upload Chat Export</h2>
        <form onSubmit={handleUpload} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Platform</label>
              <select value={platform} onChange={e => setPlatform(e.target.value)} className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-sm focus:ring-blue-500 focus:border-blue-500">
                <option value="whatsapp">WhatsApp</option>
                <option value="telegram">Telegram</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Chat File (Required)</label>
              <input 
                type="file" 
                accept=".txt,.json"
                onChange={handleChatFileSelect} 
                className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2 text-sm file:mr-4 file:py-1 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer"
              />
            </div>
            <div className="col-span-2">
              <label className="block text-sm font-medium text-slate-700 mb-1">Attachments Local Path (Optional)</label>
              <input 
                type="text" 
                placeholder="e.g. C:\Exports\WhatsApp"
                value={attachmentFolder}
                onChange={(e) => setAttachmentFolder(e.target.value)}
                className="w-full bg-slate-50 border border-slate-300 rounded-lg p-2.5 text-sm focus:ring-blue-500 focus:border-blue-500"
              />
              <p className="mt-1 text-xs text-slate-500">Paste the absolute path to the folder containing referenced files. (Browsers block picking local paths directly for security).</p>
            </div>
          </div>

          <div className="pt-2 flex items-center justify-between">
             <button type="submit" disabled={!chatFile || isUploading} className="bg-blue-600 text-white px-6 py-2.5 rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium flex items-center gap-2 transition-colors">
                <CloudUpload size={18} />
                {isUploading ? 'Uploading...' : 'Start Ingestion'}
             </button>
             {uploadMessage && (
               <span className={`text-sm font-medium ${uploadMessage.startsWith('Error') ? 'text-red-600' : 'text-green-600'}`}>
                 {uploadMessage}
               </span>
             )}
          </div>
        </form>
      </div>

      {statusData && (
        <div className="space-y-6">
          {/* Visual Pipeline Flow */}
          <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6">
            <h2 className="text-xl font-semibold text-slate-800 mb-6 flex items-center gap-2">
              <Activity size={20} className="text-blue-500 animate-pulse" />
              Ingestion & Processing Pipeline
            </h2>
            
            <div className="grid grid-cols-1 lg:grid-cols-5 items-stretch gap-4 lg:gap-2">
              {/* Step 1: Ingestion */}
              <div className={`p-5 rounded-2xl border flex flex-col justify-between col-span-1 lg:col-span-1.5 transition-all duration-300 shadow-sm hover:shadow-md ${
                ingestStatus === 'uploading' ? 'border-blue-400 bg-gradient-to-br from-blue-50/20 to-indigo-50/20 shadow-blue-50' :
                ingestStatus.startsWith('completed') ? 'border-emerald-200 bg-gradient-to-br from-emerald-50/10 to-teal-50/10' :
                'border-slate-200 bg-slate-50/20'
              }`}>
                <div>
                  <div className="flex justify-between items-center mb-3">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Step 1</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      ingestStatus === 'uploading' ? 'bg-blue-100 text-blue-800' :
                      ingestStatus === 'completed' ? 'bg-emerald-100 text-emerald-800' :
                      ingestStatus === 'completed-dedup' ? 'bg-amber-100 text-amber-800' :
                      'bg-slate-100 text-slate-600'
                    }`}>
                      {ingestStatus === 'uploading' ? 'Uploading' :
                       ingestStatus === 'completed' ? 'Success' :
                       ingestStatus === 'completed-dedup' ? 'Deduplicated' : 'Idle'}
                    </span>
                  </div>
                  <h3 className="font-bold text-slate-800 text-sm mb-1.5 flex items-center gap-2">
                    <div className={`p-1.5 rounded-lg ${
                      ingestStatus === 'uploading' ? 'bg-blue-100 text-blue-600' :
                      ingestStatus.startsWith('completed') ? 'bg-emerald-100 text-emerald-600' :
                      'bg-slate-100 text-slate-500'
                    }`}>
                      <CloudUpload size={14} />
                    </div>
                    Ingest Chat Export
                  </h3>
                  <p className="text-xs text-slate-500 leading-relaxed">Reads raw export file, fingerprints, and skips duplicate messages.</p>
                </div>
                <div className="mt-4 pt-3 border-t border-slate-100 text-xs">
                  {isUploading ? (
                    <div className="text-blue-600 animate-pulse font-medium">Uploading file<span className="animate-ellipsis"></span></div>
                  ) : lastImport ? (
                    <div>
                      <div className="font-medium text-slate-600">Last Batch: <span className="font-mono text-[10px] bg-slate-100 px-1 py-0.5 rounded">{lastImport.batch_id}</span></div>
                      <div className="text-slate-800 font-bold mt-1.5">
                        {lastImport.messages} new / {lastImport.total} total messages
                      </div>
                      {lastImport.messages === 0 ? (
                        <div className="text-amber-600 mt-1 flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-500" /> Skipped {lastImport.skipped} duplicates.
                        </div>
                      ) : (
                        <div className="text-emerald-600 mt-1 flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> Imported successfully.
                        </div>
                      )}
                    </div>
                  ) : (
                    <span className="text-slate-400">Awaiting file upload...</span>
                  )}
                </div>
              </div>

              {/* Connector 1 */}
              <div className="flex lg:flex-col justify-center items-center py-2 lg:py-0 px-2">
                <div className="hidden lg:flex items-center w-full">
                  <div className="h-0.5 bg-slate-100 flex-1 min-w-[15px]" />
                  <ChevronRight size={16} className={`${extractionStatus === 'in-progress' ? 'text-blue-500 animate-pulse' : 'text-slate-300'}`} />
                  <div className="h-0.5 bg-slate-100 flex-1 min-w-[15px]" />
                </div>
                <ChevronRight className="lg:hidden text-slate-300 rotate-90" size={20} />
              </div>

              {/* Step 2: Extraction */}
              <div className={`p-5 rounded-2xl border flex flex-col justify-between col-span-1 lg:col-span-1.5 transition-all duration-300 shadow-sm hover:shadow-md ${
                extractionStatus === 'in-progress' ? 'border-blue-400 bg-gradient-to-br from-blue-50/20 to-indigo-50/20 shadow-blue-50 shadow-md' :
                extractionStatus === 'pending-idle' ? 'border-amber-200 bg-gradient-to-br from-amber-50/10 to-amber-100/5' :
                extractionStatus === 'failed' ? 'border-red-200 bg-gradient-to-br from-red-50/10 to-red-100/5' :
                extractionStatus === 'completed' ? 'border-emerald-200 bg-gradient-to-br from-emerald-50/10 to-teal-50/10' :
                'border-slate-200 bg-slate-50/20'
              }`}>
                <div>
                  <div className="flex justify-between items-center mb-3">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Step 2</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      extractionStatus === 'in-progress' ? 'bg-blue-100 text-blue-800 animate-pulse' :
                      extractionStatus === 'pending-idle' ? 'bg-amber-100 text-amber-800' :
                      extractionStatus === 'failed' ? 'bg-red-100 text-red-800' :
                      extractionStatus === 'completed' ? 'bg-emerald-100 text-emerald-800' :
                      'bg-slate-100 text-slate-600'
                    }`}>
                      {extractionStatus === 'in-progress' ? 'Running' :
                       extractionStatus === 'pending-idle' ? 'Pending' :
                       extractionStatus === 'failed' ? 'Failed' :
                       extractionStatus === 'completed' ? 'Completed' : 'Idle'}
                    </span>
                  </div>
                  <h3 className="font-bold text-slate-800 text-sm mb-1.5 flex items-center gap-2">
                    <div className={`p-1.5 rounded-lg ${
                      extractionStatus === 'in-progress' ? 'bg-blue-100 text-blue-600' :
                      extractionStatus === 'completed' ? 'bg-emerald-100 text-emerald-600' :
                      extractionStatus === 'failed' ? 'bg-red-100 text-red-600' :
                      'bg-slate-100 text-slate-500'
                    }`}>
                      <SquareTerminal size={14} />
                    </div>
                    LLM Fact Extraction
                  </h3>
                  <p className="text-xs text-slate-500 leading-relaxed">Extracts structured community facts from raw content using OpenAI GPT.</p>
                </div>
                <div className="mt-4 pt-3 border-t border-slate-100 text-xs">
                  {extractionStatus === 'in-progress' ? (
                    <div>
                      <div className="text-blue-600 animate-pulse font-medium">Extracting facts<span className="animate-ellipsis"></span></div>
                      {extractionProgressDetails && (
                        <div className="text-slate-800 font-bold mt-1">
                          {extractionProgressDetails.facts_extracted_so_far} facts extracted
                        </div>
                      )}
                      <div className="text-slate-500 mt-1 flex flex-col gap-0.5">
                        <div>Queue: <span className="font-semibold text-slate-700">{statusData.messages.total_new}</span> remaining.</div>
                        <div>Processed: <span className="font-semibold text-emerald-700">{statusData.messages.total_extracted}</span> successfully.</div>
                      </div>
                      
                      {/* Extraction Progress Bar */}
                      {(() => {
                        const total = (statusData.messages?.total_extracted || 0) + (statusData.messages?.total_new || 0) + (statusData.messages?.total_failed || 0);
                        const progress = total > 0 ? Math.min(100, Math.round((statusData.messages?.total_extracted / total) * 100)) : 0;
                        return (
                          <div className="mt-3">
                            <div className="flex justify-between text-[10px] font-semibold text-slate-400 mb-1">
                              <span>Queue Progress</span>
                              <span>{progress}%</span>
                            </div>
                            <div className="w-full bg-slate-100 h-1.5 rounded-full overflow-hidden">
                              <div className="bg-blue-500 h-full rounded-full transition-all duration-500" style={{ width: `${progress}%` }} />
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  ) : extractionStatus === 'pending-idle' ? (
                    <div>
                      <div className="text-slate-600 font-medium mb-2">Queue has {statusData.messages.total_new} pending messages.</div>
                      <button 
                        onClick={handleTriggerExtraction} 
                        disabled={isTriggeringExtraction || isExtractionActive}
                        className="w-full bg-blue-600 text-white py-1.5 px-2 rounded-lg hover:bg-blue-700 font-bold disabled:bg-slate-100 disabled:text-slate-400 disabled:border disabled:border-slate-200 disabled:cursor-not-allowed text-[11px] transition-all shadow-sm"
                      >
                        {isTriggeringExtraction ? <span>Starting task<span className="animate-ellipsis"></span></span> : 'Trigger Fact Extraction'}
                      </button>
                    </div>
                  ) : extractionStatus === 'failed' ? (
                    <div>
                      <div className="text-red-600 font-semibold">Failed: {statusData.messages.total_failed} messages.</div>
                      {extractionErrorText && (
                        <div className="mt-1.5 p-2 bg-red-50 text-red-700 border border-red-100 rounded-lg text-[10px] break-words whitespace-pre-wrap max-h-16 overflow-y-auto font-mono">
                          {extractionErrorText}
                        </div>
                      )}
                      <div className="flex flex-col gap-2 mt-3">
                        <button 
                          onClick={handleResetFailed} 
                          disabled={isResetting || isExtractionActive}
                          className="w-full bg-red-600 text-white py-1.5 px-2 rounded-lg hover:bg-red-700 font-bold disabled:bg-slate-100 disabled:text-slate-400 disabled:border disabled:border-slate-200 disabled:cursor-not-allowed text-[10px] transition-all"
                        >
                          {isResetting ? 'Resetting...' : 'Retry Failed Extractions'}
                        </button>
                        {statusData.messages.total_new > 0 && (
                          <button 
                            onClick={handleTriggerExtraction} 
                            disabled={isTriggeringExtraction || isExtractionActive}
                            className="w-full bg-blue-600 text-white py-1.5 px-2 rounded-lg hover:bg-blue-700 font-bold disabled:bg-slate-100 disabled:text-slate-400 disabled:border disabled:border-slate-200 disabled:cursor-not-allowed text-[10px] transition-all"
                          >
                            {isTriggeringExtraction ? <span>Resuming task<span className="animate-ellipsis"></span></span> : 'Resume Extraction'}
                          </button>
                        )}
                      </div>
                      {resetStatus && <div className="text-[10px] mt-1.5 text-slate-500 font-medium">{resetStatus}</div>}
                    </div>
                  ) : extractionStatus === 'completed' ? (
                    <div>
                      <div className="text-emerald-600 font-semibold flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> All messages extracted.
                      </div>
                      <div className="text-slate-700 mt-1 font-bold">
                        {statusData.messages.total_extracted} messages processed successfully.
                      </div>
                    </div>
                  ) : (
                    <span className="text-slate-400">Awaiting messages...</span>
                  )}
                </div>
              </div>

              {/* Connector 2 */}
              <div className="flex lg:flex-col justify-center items-center py-2 lg:py-0 px-2">
                <div className="hidden lg:flex items-center w-full">
                  <div className="h-0.5 bg-slate-100 flex-1 min-w-[15px]" />
                  <ChevronRight size={16} className={`${indexingStatus === 'in-progress' ? 'text-blue-500 animate-pulse' : 'text-slate-300'}`} />
                  <div className="h-0.5 bg-slate-100 flex-1 min-w-[15px]" />
                </div>
                <ChevronRight className="lg:hidden text-slate-300 rotate-90" size={20} />
              </div>

              {/* Step 3: Indexing */}
              <div className={`p-5 rounded-2xl border flex flex-col justify-between col-span-1 lg:col-span-1.5 transition-all duration-300 shadow-sm hover:shadow-md ${
                indexingStatus === 'in-progress' ? 'border-blue-400 bg-gradient-to-br from-blue-50/20 to-indigo-50/20 shadow-blue-50 shadow-md' :
                indexingStatus === 'pending-idle' ? 'border-amber-200 bg-gradient-to-br from-amber-50/10 to-amber-100/5' :
                indexingStatus === 'failed' ? 'border-red-200 bg-gradient-to-br from-red-50/10 to-red-100/5' :
                indexingStatus === 'completed' ? 'border-emerald-200 bg-gradient-to-br from-emerald-50/10 to-teal-50/10' :
                'border-slate-200 bg-slate-50/20'
              }`}>
                <div>
                  <div className="flex justify-between items-center mb-3">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Step 3</span>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      indexingStatus === 'in-progress' ? 'bg-blue-100 text-blue-800 animate-pulse' :
                      indexingStatus === 'pending-idle' ? 'bg-amber-100 text-amber-800' :
                      indexingStatus === 'failed' ? 'bg-red-100 text-red-800' :
                      indexingStatus === 'completed' ? 'bg-emerald-100 text-emerald-800' :
                      'bg-slate-100 text-slate-600'
                    }`}>
                      {indexingStatus === 'in-progress' ? 'Running' :
                       indexingStatus === 'pending-idle' ? 'Pending' :
                       indexingStatus === 'failed' ? 'Failed' :
                       indexingStatus === 'completed' ? 'Completed' : 'Idle'}
                    </span>
                  </div>
                  <h3 className="font-bold text-slate-800 text-sm mb-1.5 flex items-center gap-2">
                    <div className={`p-1.5 rounded-lg ${
                      indexingStatus === 'in-progress' ? 'bg-blue-100 text-blue-600' :
                      indexingStatus === 'completed' ? 'bg-emerald-100 text-emerald-600' :
                      indexingStatus === 'failed' ? 'bg-red-100 text-red-600' :
                      'bg-slate-100 text-slate-500'
                    }`}>
                      <Database size={14} />
                    </div>
                    Vector Indexing
                  </h3>
                  <p className="text-xs text-slate-500 leading-relaxed">Embeds community facts and indexes them into the vector search database.</p>
                </div>
                <div className="mt-4 pt-3 border-t border-slate-100 text-xs">
                  {indexingStatus === 'in-progress' ? (
                    <div>
                      <div className="text-blue-600 animate-pulse font-medium">Embedding facts<span className="animate-ellipsis"></span></div>
                      {indexingProgressDetails && (
                        <div className="text-slate-800 font-bold mt-1">
                          {indexingProgressDetails.vectors_indexed_so_far} vectors indexed
                        </div>
                      )}
                      <div className="text-slate-500 mt-1 flex flex-col gap-0.5">
                        <div>Queue: <span className="font-semibold text-slate-700">{statusData.facts.pending_indexing}</span> remaining.</div>
                        <div>Processed: <span className="font-semibold text-emerald-700">{statusData.vectors.active}</span> successfully.</div>
                      </div>
                      
                      {/* Indexing Progress Bar */}
                      {(() => {
                        const total = (statusData.vectors?.active || 0) + (statusData.facts?.pending_indexing || 0);
                        const progress = total > 0 ? Math.min(100, Math.round((statusData.vectors?.active / total) * 100)) : 0;
                        return (
                          <div className="mt-3">
                            <div className="flex justify-between text-[10px] font-semibold text-slate-400 mb-1">
                              <span>Queue Progress</span>
                              <span>{progress}%</span>
                            </div>
                            <div className="w-full bg-slate-100 h-1.5 rounded-full overflow-hidden">
                              <div className="bg-blue-500 h-full rounded-full transition-all duration-500" style={{ width: `${progress}%` }} />
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  ) : indexingStatus === 'pending-idle' ? (
                    <div>
                      <div className="text-slate-600 font-medium mb-2">Queue has {statusData.facts.pending_indexing} pending facts.</div>
                      <button 
                        onClick={handleTriggerIndexing} 
                        disabled={isTriggeringIndexing || isIndexingActive}
                        className="w-full bg-blue-600 text-white py-1.5 px-2 rounded-lg hover:bg-blue-700 font-bold disabled:bg-slate-100 disabled:text-slate-400 disabled:border disabled:border-slate-200 disabled:cursor-not-allowed text-[11px] transition-all shadow-sm"
                      >
                        {isTriggeringIndexing ? <span>Starting task<span className="animate-ellipsis"></span></span> : 'Trigger Vector Indexing'}
                      </button>
                    </div>
                  ) : indexingStatus === 'failed' ? (
                    <div>
                      <div className="text-red-600 font-semibold mb-2">Vector indexer failed.</div>
                      {indexingErrorText && (
                        <div className="mt-1 p-2 bg-red-50 text-red-700 border border-red-100 rounded-lg text-[10px] break-words whitespace-pre-wrap max-h-16 overflow-y-auto font-mono">
                          {indexingErrorText}
                        </div>
                      )}
                      {statusData.facts.pending_indexing > 0 && (
                        <button 
                          onClick={handleTriggerIndexing} 
                          disabled={isTriggeringIndexing || isIndexingActive}
                          className="mt-3 w-full bg-blue-600 text-white py-1.5 px-2 rounded-lg hover:bg-blue-700 font-bold disabled:bg-slate-100 disabled:text-slate-400 disabled:border disabled:border-slate-200 disabled:cursor-not-allowed text-[10px] transition-all"
                        >
                          {isTriggeringIndexing ? <span>Resuming task<span className="animate-ellipsis"></span></span> : 'Resume Indexing'}
                        </button>
                      )}
                    </div>
                  ) : indexingStatus === 'completed' ? (
                    <div>
                      <div className="text-emerald-600 font-semibold flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> All facts indexed.
                      </div>
                      <div className="text-slate-700 mt-1 font-bold">
                        {statusData.vectors.active} active vectors indexed.
                      </div>
                    </div>
                  ) : (
                    <span className="text-slate-400">Awaiting facts...</span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Queue Info & Imports History */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6">
              <h2 className="text-xl font-semibold text-slate-800 mb-4 flex items-center gap-2">
                <SquareTerminal size={20} className="text-slate-500" />
                Pipeline Backlog Metrics
              </h2>
              <div className="space-y-4">
                 <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-slate-600 font-medium">Extraction Queue (New Messages)</span>
                      <span className="text-slate-800 font-bold">{statusData.messages.total_new} pending</span>
                    </div>
                    <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden border border-slate-200">
                      <div className="bg-blue-500 h-2.5 rounded-full transition-all" style={{ width: statusData.messages.total_new > 0 ? '100%' : '0%' }}></div>
                    </div>
                 </div>
                 
                 <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-slate-600 font-medium">Failed Extractions</span>
                      <span className="text-slate-800 font-bold text-red-600">{statusData.messages.total_failed}</span>
                    </div>
                 </div>

                 <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-slate-600 font-medium">Indexing Queue (Pending Facts)</span>
                      <span className="text-slate-800 font-bold">{statusData.facts.pending_indexing} pending</span>
                    </div>
                    <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden border border-slate-200">
                      <div className="bg-purple-500 h-2.5 rounded-full transition-all" style={{ width: statusData.facts.pending_indexing > 0 ? '100%' : '0%' }}></div>
                    </div>
                 </div>

                 <div>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="text-slate-600 font-medium">Total Active Vectors</span>
                      <span className="text-slate-800 font-bold text-green-600">{statusData.vectors.active}</span>
                    </div>
                 </div>
              </div>
            </div>

            <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6">
              <h2 className="text-xl font-semibold text-slate-800 mb-4 flex items-center gap-2">
                <BarChart2 size={20} className="text-slate-500" />
                Recent Imports
              </h2>
              {statusData.history && statusData.history.length > 0 ? (
                <div className="space-y-3">
                  {statusData.history.map((run: any, i: number) => (
                    <div key={i} className="flex items-center justify-between p-3 bg-slate-50 border border-slate-200 rounded-lg">
                      <div>
                        <div className="text-sm font-medium text-slate-800">Batch: {run.batch_id}</div>
                        <div className="text-xs text-slate-500">{run.date} • {run.platform}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-sm font-bold text-blue-600">{run.messages}</div>
                        <div className="text-xs text-slate-500">messages</div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-500 text-center py-4">No recent imports found.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatisticsDashboard() {
  const { apartment } = useApartment();
  const { data, isLoading, error } = useQuery({
    queryKey: ['status', apartment, 'stats-page'],
    queryFn: async () => {
      if (!apartment) return null;
      const res = await fetch(`/api/${apartment}/status`);
      if (!res.ok) throw new Error('Failed to fetch stats');
      return res.json();
    },
    refetchInterval: 5000,
    enabled: !!apartment,
  });

  if (!apartment) return <div className="flex items-center justify-center h-full text-slate-500">Please select an apartment to view statistics.</div>;
  if (isLoading && !data) return <div className="p-8 text-slate-500">Loading statistics...</div>;
  if (error) return <div className="p-8 text-red-500">Error loading statistics.</div>;

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-slate-800 mb-2">System Statistics</h1>
        <p className="text-slate-600">Overview of data processing and storage health for <span className="font-semibold text-blue-600">{apartment}</span>.</p>
      </div>

      {data && (
        <>
          <h3 className="text-lg font-semibold text-slate-800 border-b border-slate-200 pb-2">Extraction Pipeline (Raw Messages)</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6 flex items-start gap-4">
              <div className="p-3 bg-blue-100 text-blue-600 rounded-lg"><Activity size={24} /></div>
              <div>
                <p className="text-sm font-medium text-slate-500">Pending Extraction</p>
                <h4 className="text-2xl font-bold text-slate-800">{data.messages.total_new}</h4>
              </div>
            </div>
            <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6 flex items-start gap-4">
              <div className="p-3 bg-green-100 text-green-600 rounded-lg"><CheckCircle2 size={24} /></div>
              <div>
                <p className="text-sm font-medium text-slate-500">Successfully Extracted</p>
                <h4 className="text-2xl font-bold text-slate-800">{data.messages.total_extracted}</h4>
              </div>
            </div>
            <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6 flex items-start gap-4">
              <div className="p-3 bg-red-100 text-red-600 rounded-lg"><AlertCircle size={24} /></div>
              <div>
                <p className="text-sm font-medium text-slate-500">Failed Extraction</p>
                <h4 className="text-2xl font-bold text-slate-800">{data.messages.total_failed}</h4>
              </div>
            </div>
          </div>

          <h3 className="text-lg font-semibold text-slate-800 border-b border-slate-200 pb-2 mt-8">Indexing Pipeline (Canonical Facts)</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6 flex items-start gap-4">
              <div className="p-3 bg-purple-100 text-purple-600 rounded-lg"><Layers size={24} /></div>
              <div>
                <p className="text-sm font-medium text-slate-500">Total Extracted Facts</p>
                <h4 className="text-2xl font-bold text-slate-800">{data.facts.total}</h4>
              </div>
            </div>
            <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6 flex items-start gap-4">
              <div className="p-3 bg-yellow-100 text-yellow-600 rounded-lg"><Activity size={24} /></div>
              <div>
                <p className="text-sm font-medium text-slate-500">Pending Indexing</p>
                <h4 className="text-2xl font-bold text-slate-800">{data.facts.pending_indexing}</h4>
              </div>
            </div>
            <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6 flex items-start gap-4">
              <div className="p-3 bg-indigo-100 text-indigo-600 rounded-lg"><Database size={24} /></div>
              <div>
                <p className="text-sm font-medium text-slate-500">Active Vectors</p>
                <h4 className="text-2xl font-bold text-slate-800">{data.vectors.active}</h4>
              </div>
            </div>
          </div>

          <div className="bg-slate-100 border border-slate-200 rounded-xl p-6 mt-8 flex gap-8">
            <div>
              <span className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Active Extraction Model</span>
              <span className="font-mono text-sm bg-white px-2 py-1 rounded border border-slate-300">{data.current_models.extraction}</span>
            </div>
            <div>
              <span className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">Active Embedding Model</span>
              <span className="font-mono text-sm bg-white px-2 py-1 rounded border border-slate-300">{data.current_models.embedding}</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function UsageDashboard() {
  const { apartment } = useApartment();
  const { data, isLoading, error } = useQuery({
    queryKey: ['observability', apartment],
    queryFn: async () => {
      if (!apartment) return null;
      const res = await fetch(`/api/${apartment}/observability`);
      if (!res.ok) throw new Error('Failed to fetch observability stats');
      return res.json();
    },
    refetchInterval: 10000,
    enabled: !!apartment,
  });

  if (!apartment) return <div className="flex items-center justify-center h-full text-slate-500">Please select an apartment to view usage.</div>;
  if (isLoading && !data) return <div className="p-8 text-slate-500">Loading usage metrics...</div>;
  if (error) return <div className="p-8 text-red-500">Error loading usage metrics.</div>;

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-slate-800 mb-2">Usage & Billing</h1>
        <p className="text-slate-600">LLM token usage, estimated costs, and API latencies for <span className="font-semibold text-blue-600">{apartment}</span>.</p>
      </div>

      {data && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-8 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-slate-500 mb-1">Total Tokens Used</p>
                <h4 className="text-4xl font-bold text-slate-800">{data.usage.total_tokens.toLocaleString()}</h4>
              </div>
              <div className="p-4 bg-blue-50 text-blue-600 rounded-full"><Database size={32} /></div>
            </div>
            <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-8 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-slate-500 mb-1">Estimated Cost</p>
                <h4 className="text-4xl font-bold text-slate-800">${data.usage.total_cost.toFixed(4)}</h4>
              </div>
              <div className="p-4 bg-green-50 text-green-600 rounded-full"><Coins size={32} /></div>
            </div>
          </div>

          <h3 className="text-lg font-semibold text-slate-800 border-b border-slate-200 pb-2 mt-8">Average Latency by Operation</h3>
          <div className="bg-white border border-slate-200 shadow-sm rounded-xl overflow-hidden">
            {Object.keys(data.latencies).length === 0 ? (
               <p className="p-6 text-sm text-slate-500">No latency data recorded yet.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {Object.entries(data.latencies).map(([purpose, latency]) => (
                  <li key={purpose} className="p-4 flex items-center justify-between hover:bg-slate-50 transition-colors">
                    <span className="font-medium text-slate-700 capitalize">{purpose.replace('_', ' ')}</span>
                    <span className="flex items-center gap-2 text-slate-600 bg-slate-100 px-3 py-1 rounded-full text-sm">
                      <Clock size={16} className="text-slate-400" />
                      {String(latency)} ms
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function LogsViewer() {
  const { apartment } = useApartment();
  const { data, isLoading, error } = useQuery({
    queryKey: ['logs', apartment],
    queryFn: async () => {
      if (!apartment) return null;
      const res = await fetch(`/api/${apartment}/logs`);
      if (!res.ok) throw new Error('Failed to fetch logs');
      return res.json();
    },
    refetchInterval: 5000,
    enabled: !!apartment,
  });

  if (!apartment) return <div className="flex items-center justify-center h-full text-slate-500">Please select an apartment to view logs.</div>;

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-8 flex flex-col h-full">
      <div>
        <h1 className="text-3xl font-bold text-slate-800 mb-2">Logs & Tracing</h1>
        <p className="text-slate-600">View pipeline events and debug LLM traces for <span className="font-semibold text-blue-600">{apartment}</span>.</p>
      </div>

      <div className="bg-white border border-slate-200 shadow-sm rounded-xl p-6 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold text-slate-800">Advanced LLM Tracing</h3>
          <p className="text-sm text-slate-500 mt-1">AptJeeves uses Langfuse to trace complex workflows, track latencies, and monitor prompt inputs/outputs.</p>
        </div>
        <a href="https://cloud.langfuse.com/" target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 bg-slate-900 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-slate-800 transition-colors shadow-sm">
          Open Langfuse Dashboard <ExternalLink size={16} />
        </a>
      </div>

      <div className="flex-1 bg-white border border-slate-200 shadow-sm rounded-xl overflow-hidden flex flex-col min-h-[400px]">
        <div className="p-4 border-b border-slate-200 bg-slate-50">
          <h3 className="font-semibold text-slate-800">Recent Pipeline Events (SQLite)</h3>
        </div>
        <div className="flex-1 overflow-auto">
          {isLoading && !data ? (
            <div className="p-8 text-slate-500 text-center">Loading logs...</div>
          ) : error ? (
            <div className="p-8 text-red-500 text-center">Error loading logs.</div>
          ) : data?.events?.length === 0 ? (
            <div className="p-8 text-slate-500 text-center">No pipeline events recorded yet.</div>
          ) : (
            <table className="w-full text-left text-sm whitespace-nowrap">
              <thead className="bg-slate-50 text-slate-600 sticky top-0 z-10 border-b border-slate-200 shadow-sm">
                <tr><th className="px-6 py-3 font-medium">Timestamp</th><th className="px-6 py-3 font-medium">Event Type</th><th className="px-6 py-3 font-medium">Status</th><th className="px-6 py-3 font-medium w-full">Details</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.events.map((event: any, i: number) => (
                  <tr key={i} className="hover:bg-slate-50/50">
                    <td className="px-6 py-3 text-slate-500">{event.timestamp?.replace('T', ' ').split('.')[0]}</td>
                    <td className="px-6 py-3 font-medium text-slate-700">{event.event_type}</td>
                    <td className="px-6 py-3"><span className={`px-2.5 py-1 rounded-full text-xs font-medium ${event.status === 'success' ? 'bg-green-100 text-green-700' : event.status === 'error' ? 'bg-red-100 text-red-700' : event.status === 'started' ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-700'}`}>{event.status}</span></td>
                    <td className="px-6 py-3 text-slate-500 font-mono text-[11px]">{event.details}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

function Sidebar() {
  const navItems = [
    { to: "/", icon: <MessageSquare size={20} />, label: "Chat" },
    { to: "/ingestion", icon: <CloudUpload size={20} />, label: "Ingestion" },
    { to: "/stats", icon: <BarChart2 size={20} />, label: "Statistics" },
    { to: "/usage", icon: <DollarSign size={20} />, label: "Usage" },
    { to: "/logs", icon: <SquareTerminal size={20} />, label: "Logs" },
  ];

  return (
    <div className="w-64 bg-slate-900 text-slate-300 flex flex-col h-full border-r border-slate-800">
      <div className="p-6">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <MessageSquare className="text-blue-500" />
          AptJeeves 2.0
        </h1>
      </div>
      <nav className="flex-1 px-4 space-y-2 mt-4">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                isActive
                  ? "bg-blue-600 text-white"
                  : "hover:bg-slate-800 hover:text-white"
              }`
            }
          >
            {item.icon}
            <span className="font-medium">{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

function App() {
  const [apartment, setApartment] = useState<string>("");

  return (
    <QueryClientProvider client={queryClient}>
      <ApartmentContext.Provider value={{ apartment, setApartment }}>
        <BrowserRouter>
          <div className="flex h-screen bg-slate-50 font-sans text-slate-900">
            <Sidebar />
            <main className="flex-1 flex flex-col overflow-hidden bg-slate-50">
              <TopBar />
              <div className="flex-1 overflow-y-auto">
                <Routes>
                  <Route path="/" element={<ChatInterface />} />
                  <Route path="/ingestion" element={<IngestionManager />} />
                  <Route path="/stats" element={<StatisticsDashboard />} />
                  <Route path="/usage" element={<UsageDashboard />} />
                  <Route path="/logs" element={<LogsViewer />} />
                </Routes>
              </div>
            </main>
          </div>
        </BrowserRouter>
      </ApartmentContext.Provider>
    </QueryClientProvider>
  );
}

export default App
