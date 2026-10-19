/**
 * InspectionPhoto.tsx — Inspection image via BFF proxy
 *
 * Fetches image via GET /api/photo?record_id=<id>
 * FastAPI proxies the Fulcrum API call server-side — API key never in browser.
 *
 * Error handling:
 *   - Mock mode or mock- record IDs: shows coloured placeholder (no real images)
 *   - 404: "No inspection image available"
 *   - 502: "Fulcrum API unreachable"
 *
 * Memory management:
 *   - blob URL revoked on component unmount (prevents memory leak)
 */

import { useState, useEffect } from 'react';
import type { RiskBand } from '../types';
import { fetchInspectionImage } from '../api/client';

interface Props {
  recordId: string;
  assetId: string;
  riskBand: RiskBand;
}

const MOCK_MODE = import.meta.env.VITE_MOCK_MODE === 'true';
const BAND_COLORS: Record<RiskBand, string> = {
  GREEN: '#22c55e',
  AMBER: '#f59e0b',
  RED:   '#ef4444',
};

export default function InspectionPhoto({ recordId, assetId, riskBand }: Props) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>('loading');
  const [errorMsg, setErrorMsg] = useState<string>('');

  const isMockRecord = MOCK_MODE || recordId.startsWith('mock-');

  useEffect(() => {
    if (isMockRecord) {
      setStatus('error');
      setErrorMsg('Mock mode — no real inspection images');
      return;
    }

    let currentBlobUrl: string | null = null;

    fetchInspectionImage(recordId)
      .then(url => {
        currentBlobUrl = url;
        setBlobUrl(url);
        setStatus('ok');
      })
      .catch((err: Error) => {
        setStatus('error');
        setErrorMsg(err.message.includes('404') ? 'No inspection image available' : err.message);
      });

    // Cleanup: revoke blob URL on unmount to prevent memory leak
    return () => {
      if (currentBlobUrl) {
        URL.revokeObjectURL(currentBlobUrl);
      }
    };
  }, [recordId, isMockRecord]);

  if (status === 'loading') {
    return (
      <div className="photo-placeholder loading">
        <div className="spinner small" />
        <p>Loading inspection image…</p>
      </div>
    );
  }

  if (status === 'error') {
    return (
      <div
        className="photo-placeholder error"
        style={{ borderColor: BAND_COLORS[riskBand] }}
      >
        <div className="photo-icon" style={{ color: BAND_COLORS[riskBand] }}>
          {riskBand === 'RED' ? '🔴' : riskBand === 'AMBER' ? '🟡' : '🟢'}
        </div>
        <p className="photo-asset-id">{assetId}</p>
        <p className="photo-error-msg">{errorMsg}</p>
        <span className={`risk-badge badge-${riskBand.toLowerCase()}`}>{riskBand}</span>
      </div>
    );
  }

  return (
    <div className="photo-container">
      <img
        src={blobUrl!}
        alt={`Inspection photo for ${assetId}`}
        className="inspection-photo"
      />
      <p className="photo-caption">{assetId} · Via Fulcrum BFF proxy</p>
    </div>
  );
}
