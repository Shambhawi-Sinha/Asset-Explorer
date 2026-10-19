/**
 * AssetDrillDown.tsx — Individual asset detail view
 *
 * Loads when user clicks a row in AssetList or a card in FleetOverview.
 *
 * Panels:
 *   1. Asset header — name, ID, health score, risk band, last inspection
 *   2. Five metric trend charts (90 days) — all fetched in parallel via Promise.all
 *      - Thermal Aging Factor (FAA)
 *      - Overload Severity
 *      - Tap Changer Stress
 *      - Mean Winding Temperature
 *   3. Work Order Timeline — most recent first, emergency WOs highlighted
 *   4. Inspection Photo Gallery — images via /api/photo BFF proxy
 *   5. RAG Diagnostic Chatbot — scoped to this asset's data
 */

import { useState, useEffect } from 'react';
import type { TransformerRecord, AssetMetrics } from '../types';
import { fetchAssetMetrics, fetchInspectionImage } from '../api/client';
import MetricChart from './MetricChart';
import WorkOrderTimeline from './WorkOrderTimeline';
import InspectionPhoto from './InspectionPhoto';
import ChatPanel from './ChatPanel';

interface Props {
  asset: TransformerRecord;
  onBack: () => void;
}

export default function AssetDrillDown({ asset, onBack }: Props) {
  const [metrics, setMetrics] = useState<AssetMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);

    // 5 metric endpoints in parallel — key performance design (interview talking point)
    fetchAssetMetrics(asset.asset_id)
      .then(data => { setMetrics(data); setLoading(false); })
      .catch((err: Error) => { setError(err.message); setLoading(false); });
  }, [asset.asset_id]);

  return (
    <div className="asset-drilldown">
      {/* Back navigation */}
      <button className="back-btn" onClick={onBack}>← Back to Asset List</button>

      {/* Asset Header */}
      <div className={`asset-header band-${asset.risk_band.toLowerCase()}`}>
        <div className="asset-title">
          <h2>{asset.substation_name}</h2>
          <span className="asset-id mono">{asset.asset_id}</span>
        </div>
        <div className="asset-vitals">
          <div className="vital">
            <span className="vital-label">Health Score</span>
            <span className="vital-value large">{asset.health_score.toFixed(0)}</span>
          </div>
          <span className={`risk-badge badge-${asset.risk_band.toLowerCase()} large`}>
            {asset.risk_band}
          </span>
          {(asset.open_emergency_wos ?? 0) > 0 && (
            <div className="emergency-alert">
              ⚠ {asset.open_emergency_wos} Open Emergency WO{(asset.open_emergency_wos ?? 0) > 1 ? 's' : ''}
            </div>
          )}
        </div>
        <div className="asset-meta">
          {asset.last_inspection_date && <span>Last inspection: {asset.last_inspection_date}</span>}
          {asset.voltage_kv && <span>{asset.voltage_kv} kV</span>}
          {asset.rating_mva && <span>{asset.rating_mva} MVA</span>}
        </div>
      </div>

      {loading && <div className="loading-metrics">Loading metric trends…</div>}
      {error   && <div className="error-metrics">Failed to load metrics: {error}</div>}

      {metrics && (
        <>
          {/* 5 Metric Trend Charts */}
          <section className="metrics-grid">
            <MetricChart
              title="Thermal Aging Factor (FAA)"
              subtitle="IEC 60076-7 — FAA = 1 normal, FAA > 4 critical"
              data={metrics.thermal}
              color="#ef4444"
              warningThreshold={2}
              criticalThreshold={4}
              yLabel="FAA"
            />
            <MetricChart
              title="Overload Severity"
              subtitle="MVA actual / MVA rated — above 1.0 = overloaded"
              data={metrics.overload}
              color="#f59e0b"
              warningThreshold={0.9}
              criticalThreshold={1.0}
              yLabel="pu load"
            />
            <MetricChart
              title="Tap Changer Stress"
              subtitle="Daily TPOSC operations — above 30/day = elevated wear"
              data={metrics.tap}
              color="#8b5cf6"
              warningThreshold={20}
              criticalThreshold={30}
              yLabel="ops/day"
            />
            <MetricChart
              title="Mean Winding Temperature"
              subtitle="Rolling 24h average — normal 65–85°C, critical >105°C"
              data={metrics.winding}
              color="#60a5fa"
              warningThreshold={85}
              criticalThreshold={105}
              yLabel="°C"
            />
          </section>

          {/* Work Order Timeline */}
          <section className="wo-section">
            <h3 className="section-label">Work Order Timeline</h3>
            <WorkOrderTimeline workorders={metrics.workorders} />
          </section>

          {/* Inspection Photo Gallery */}
          {asset.photo_record_id && (
            <section className="photo-section">
              <h3 className="section-label">Inspection Photos</h3>
              <InspectionPhoto
                recordId={asset.photo_record_id}
                assetId={asset.asset_id}
                riskBand={asset.risk_band}
              />
            </section>
          )}
        </>
      )}

      {/* RAG Chatbot — always shown, scoped to this asset */}
      <section className="chat-section">
        <h3 className="section-label">AI Diagnostic Assistant — {asset.substation_name}</h3>
        <ChatPanel assetId={asset.asset_id} assetName={asset.substation_name} />
      </section>
    </div>
  );
}
