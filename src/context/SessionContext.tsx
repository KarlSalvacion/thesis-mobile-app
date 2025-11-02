import React, { createContext, useContext, useState, useCallback, ReactNode, useEffect } from 'react';
import { useRoute } from '@react-navigation/native';

type DetectionRow = [
  id: number,
  filename: string,
  timestamp: string,
  file_type: string,
  summary: string | null,
  total_frames: number,
  total_detections: number,
  processing_time: number,
  input_size_bytes: number | null,
  result_size_bytes: number | null,
  has_srt_data: boolean | null
];

interface SessionContextType {
  selectedDetection: DetectionRow | null;
  sessions: DetectionRow[];
  isLoading: boolean;
  error: string;
  navigationLocked: boolean;
  setSelectedDetection: (detection: DetectionRow | null) => void;
  refreshSessions: () => Promise<void>;
  clearSelection: () => void;
  setNavigationLocked: (locked: boolean) => void;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

interface SessionProviderProps {
  children: ReactNode;
}

export const SessionProvider: React.FC<SessionProviderProps> = ({ children }) => {
  const [selectedDetection, setSelectedDetection] = useState<DetectionRow | null>(null);
  const [sessions, setSessions] = useState<DetectionRow[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [navigationLocked, setNavigationLocked] = useState(false);

  const refreshSessions = useCallback(async () => {
    try {
      setIsLoading(true);
      setError('');
      
      // Import API_BASE dynamically to avoid circular dependencies
      const { API_BASE } = await import('../config');
      const res = await fetch(`${API_BASE}/detections/`);
      const json = await res.json();
      const rows: DetectionRow[] = json?.detections ?? [];
      setSessions(rows);
      
      // Don't auto-select any detection - let user explicitly choose
      // This ensures screens start empty when no files are uploaded
    } catch (e: any) {
      setError(e?.message || 'Failed to load sessions');
      setSessions([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedDetection(null);
  }, []);

  const value: SessionContextType = {
    selectedDetection,
    sessions,
    isLoading,
    error,
    navigationLocked,
    setSelectedDetection,
    refreshSessions,
    clearSelection,
    setNavigationLocked,
  };

  return (
    <SessionContext.Provider value={value}>
      {children}
    </SessionContext.Provider>
  );
};

export const useSession = (): SessionContextType => {
  const context = useContext(SessionContext);
  if (context === undefined) {
    throw new Error('useSession must be used within a SessionProvider');
  }
  return context;
};
